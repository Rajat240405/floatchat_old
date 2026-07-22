"""Scientific Feature Extractor – Step 2 (shadow mode).

Wraps the legacy ScientificExplanationEngine._compute_stats() output
into a structured ScientificFacts object.

Design constraints for Step 2:
- Do NOT migrate _compute_stats() yet – use it as reference.
- Reproduce EXACTLY: Thermocline, Halocline, Oxygen Minimum, DCM, BBP700 trend
- No new detectors (MLD, Nitracline, pH min, Euphotic Depth) yet.
- Output must be a compact ScientificFacts JSON (1–3 KB).
- Every numeric value originates from Python legacy stats.
- No DataFrames, arrays, or NetCDF objects cross the LLM boundary.

This extractor runs in SHADOW MODE – results are compared to legacy,
but legacy remains authoritative until LLM narration is validated.
"""

from __future__ import annotations

import logging
import math
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

import numpy as np
import pandas as pd

from ..models.intent import ParsedIntent
from ..models.metadata import MetadataRecord
from .engine import ScientificExplanationEngine
from .schemas import (
    ProfileMeta,
    QCSummary,
    RetrievalProvenance,
    ScientificFacts,
    VariableStats,
    VerticalFeature,
)

logger = logging.getLogger(__name__)

_FLOAT_ID_RE = re.compile(r"/([\d]{7,})/")

# Narration needs representative profile context, not every duplicated file path.
# Aggregate counts in RetrievalProvenance continue to describe the full result set.
_MAX_NARRATION_PROFILES = 3
_MAX_NARRATION_GDAC_FILES = 3

# Units registry – expandable for NITRATE, pH, CDOM, etc. without prompt changes
_UNITS: Dict[str, str] = {
    "TEMP": "°C",
    "TEMP_ADJUSTED": "°C",
    "PSAL": "PSU",
    "PSAL_ADJUSTED": "PSU",
    "DOXY": "µmol/kg",
    "DOXY_ADJUSTED": "µmol/kg",
    "CHLA": "mg/m³",
    "CHLA_ADJUSTED": "mg/m³",
    "BBP700": "m^-1",
    "BBP700_ADJUSTED": "m^-1",
    # Future BGC – schema already supports them, extractor just needs units:
    "NITRATE": "µmol/kg",
    "NITRATE_ADJUSTED": "µmol/kg",
    "PH_IN_SITU_TOTAL": "total scale",
    "PH_IN_SITU_TOTAL_ADJUSTED": "total scale",
    "DOWNWELLING_PAR": "µmol quanta/m²/s",
    "DOWNWELLING_PAR_ADJUSTED": "µmol quanta/m²/s",
    "CDOM": "ppb",
    "CDOM_ADJUSTED": "ppb",
}

# ------------------------------------------------------------------
# Phase 1: deterministic feature classifications
# ------------------------------------------------------------------
# These thresholds encode widely cited oceanographic conventions and
# are deliberately conservative. Every classification is computed in
# Python from the observed DataFrame before the LLM is invoked, so the
# LLM receives pre-classified features as input rather than being asked
# to invent the classification itself.
#
# References:
#   - Thermocline gradient thresholds: Levitus (1982) standard thermocline
#     definition; 0.1 °C/dbar is the conventional minimum gradient,
#     0.3 °C/dbar is commonly used as a "sharp" thermocline boundary.
#   - Oxygen Minimum Zone thresholds: Paulmier & Ruiz-Pino (2009),
#     hypoxic boundary at ~60 µmol/kg, suboxic below ~20 µmol/kg.
#   - Deep Chlorophyll Maximum: Cullen (2015); subsurface chlorophyll
#     maxima occur at depths > 20 m with surface-depleted contrast.
# ------------------------------------------------------------------

# Thermocline: temperature gradient in °C/dbar
_THERMOCLINE_STRONG_GRADIENT_C_PER_DBAR: float = 0.3
_THERMOCLINE_MODERATE_GRADIENT_C_PER_DBAR: float = 0.1

# Halocline: salinity gradient in PSU/dbar (typically weaker than thermocline)
_HALOCLINE_STRONG_GRADIENT_PSU_PER_DBAR: float = 0.05
_HALOCLINE_MODERATE_GRADIENT_PSU_PER_DBAR: float = 0.02

# Oxygen Minimum Zone: minimum oxygen concentration in µmol/kg
_OMZ_STRONG_MIN_UMOLKG: float = 60.0
_OMZ_MODERATE_MIN_UMOLKG: float = 150.0

# Deep Chlorophyll Maximum: depth threshold and contrast ratio.
# Note: the legacy ``_compute_stats`` filters ``max_val_depth`` to
# depths strictly greater than 20 dbar, so a "weak" prominence is
# reserved for shallow subsurface peaks (between 20 and 30 dbar) that
# lack strong surface contrast. A "strong" DCM requires both a depth
# ≥ 30 dbar (Cullen 2015 subsurface criterion) and a chlorophyll
# contrast ≥ 1.5×.
_DCM_STRONG_DEPTH_DBAR: float = 30.0
_DCM_SUBSURFACE_DEPTH_DBAR: float = 20.0
_DCM_STRONG_CONTRAST_RATIO: float = 1.5

ProminenceLabel = Literal["strong", "moderate", "weak"]

# ------------------------------------------------------------------
# Phase 2: deterministic cross-variable relationship notes
# ------------------------------------------------------------------
# Every note is derived from observed numeric values and depth
# locations, with no mechanism inference. Notes are emitted only when
# both relevant features/stats are present in the same query and the
# relationship is supported by the data.
# ------------------------------------------------------------------

# Maximum number of notes – matches ScientificFacts.cross_variable_notes
# ``max_length=8``.
_MAX_CROSS_NOTES: int = 8

# Vertical alignment thresholds (dbar). Two features whose depths differ
# by less than ``_ALIGNMENT_COINCIDENT_DBAR`` are reported as coincident;
# less than ``_ALIGNMENT_CLOSE_DBAR`` as closely aligned; otherwise the
# absolute separation is reported.
_ALIGNMENT_COINCIDENT_DBAR: float = 10.0
_ALIGNMENT_CLOSE_DBAR: float = 30.0

# Surface regime thresholds (well-established oceanographic limits).
_EVAPORATIVE_TEMP_C: float = 20.0
_EVAPORATIVE_SAL_PSU: float = 35.0
_FRESH_SAL_PSU: float = 33.0

# CHLA–BBP700 subsurface peak co-location threshold (dbar). Two peaks
# whose depths differ by less than this are reported as coincident;
# otherwise the note is suppressed (no speculative co-location claim).
_CHLA_BBP_COINCIDENT_DBAR: float = 30.0

# Depth filter for BBP700 max depth – matches legacy ``max_val_depth``
# filter (``PRES > 20``).
_BBP700_DEPTH_FILTER_DBAR: float = 20.0

# Human-readable names for ``VerticalFeature.feature`` strings. The
# schema vocabulary is open (e.g. "particle_max"), so unknown values
# fall back to a title-cased rendering.
_FEATURE_HUMAN_NAME: dict[str, str] = {
    "thermocline": "thermocline",
    "halocline": "halocline",
    "oxygen_minimum": "Oxygen minimum",
    "dcm": "Deep chlorophyll maximum",
}


def _humanize_feature(feature: str) -> str:
    """Render a ``VerticalFeature.feature`` token for narrative prose."""
    return _FEATURE_HUMAN_NAME.get(
        feature, feature.replace("_", " ").title()
    )


def _extract_float_id(file_path: str) -> Optional[str]:
    m = _FLOAT_ID_RE.search(file_path or "")
    return m.group(1) if m else None


def _get_units(var_name: str) -> str:
    # Try exact, then base without _ADJUSTED
    if var_name in _UNITS:
        return _UNITS[var_name]
    base = var_name.replace("_ADJUSTED", "")
    return _UNITS.get(base, "unknown")


def _has_finite_values(df: pd.DataFrame, column: str) -> bool:
    """Return whether *column* contains at least one finite numeric value."""
    values = pd.to_numeric(df[column], errors="coerce")
    return bool(np.isfinite(values).any())


def _resolve_column(df: pd.DataFrame, var: str) -> Optional[str]:
    """Resolve a variable, preferring usable adjusted data over the base data."""
    adj = f"{var}_ADJUSTED"
    if adj in df.columns and _has_finite_values(df, adj):
        return adj
    if var in df.columns:
        return var

    # Preserve the existing case-insensitive fallback and its adjusted-data
    # preference, but do not select an all-missing adjusted column.
    adj_upper = adj.upper()
    var_upper = var.upper()
    for column in df.columns:
        if column.upper() == adj_upper and _has_finite_values(df, column):
            return column
    for column in df.columns:
        if column.upper() == var_upper:
            return column
    return None


class ScientificFeatureExtractor:
    """
    Wraps legacy _compute_stats() into a typed ScientificFacts object.

    Step 2 policy:
    - use_legacy=True (default) → call ScientificExplanationEngine._compute_stats
    - output is ScientificFacts – array-free, 1–3KB
    - no new scientific detectors yet
    """

    def __init__(self, use_legacy: bool = True):
        self.use_legacy = use_legacy
        # Legacy engine is the reference implementation – do NOT modify it
        self._legacy_engine = ScientificExplanationEngine() if use_legacy else None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(
        self,
        df: pd.DataFrame,
        variables: List[str],
        intent: ParsedIntent,
        records: List[MetadataRecord],
        query_id: Optional[str] = None,
    ) -> ScientificFacts:
        """
        Produce a ScientificFacts object from a DataFrame.
        In Step 2 this wraps the legacy _compute_stats() exactly.
        """
        if not variables:
            raise ValueError("variables list must not be empty")

        # --- Step 2: use legacy stats as ground truth ---
        if self.use_legacy and self._legacy_engine is not None:
            legacy_stats = self._legacy_engine._compute_stats(df, variables)
        else:
            # Future native implementation placeholder – not used in Step 2
            raise NotImplementedError("Native extractor not yet enabled in Step 2")

        # Build provenance first (needed for ScientificFacts)
        provenance = self._build_provenance(records, df)

        # Build profile metadata
        profiles = self._build_profiles(records)

        # Convert legacy stats dict → List[VariableStats]
        stats = self._stats_to_variable_stats(legacy_stats, variables, df)

        # Convert legacy feature depths → List[VerticalFeature]
        features = self._stats_to_features(legacy_stats, variables, df)

        # QC summary
        qc = self._build_qc_summary(records, variables, df)

        # Phase 2: deterministic cross-variable relationship notes.
        # Only emitted when both relevant features/stats are present.
        cross_notes = self._build_cross_variable_notes(features, stats, df)

        facts = ScientificFacts(
            schema_version="1.0.0",
            prompt_version="sci_narrator_v1_2026-07",
            query_id=query_id or uuid.uuid4().hex[:12],
            generated_at=datetime.now(timezone.utc),
            variables_requested=[v.upper() for v in variables],
            region=intent.region,
            float_id=intent.float_id,
            year_filter=intent.year,
            provenance=provenance,
            profiles=profiles,
            stats=stats,
            features=features,
            qc=qc,
            cross_variable_notes=cross_notes,
        )

        # Explicit runtime validation – no assert
        # 1. Ensure no arrays leaked
        try:
            facts.validate_no_arrays()
        except ValueError as e:
            logger.error("ScientificFacts array-leak validation failed: %s", e)
            raise

        # 2. Size check – use configurable limit if available
        try:
            from ..config import settings  # local import to avoid circular
            max_bytes = getattr(settings, "sci_narrator_max_payload_bytes", 4096)
        except Exception:
            max_bytes = 4096

        try:
            payload = facts.to_llm_payload(max_bytes=max_bytes)
            logger.info(
                "ScientificFacts JSON size_bytes=%d variables=%d features=%d",
                len(payload.encode("utf-8")),
                len(stats),
                len(features),
            )
        except ValueError as e:
            logger.warning("ScientificFacts payload exceeds limit: %s", e)
            # Do not crash the pipeline – caller decides fallback
            raise

        return facts

    # ------------------------------------------------------------------
    # Legacy → schema converters
    # ------------------------------------------------------------------

    def _stats_to_variable_stats(
        self, legacy_stats: Dict[str, Any], variables: List[str], df: pd.DataFrame
    ) -> List[VariableStats]:
        out: List[VariableStats] = []
        for var in variables:
            if var not in legacy_stats:
                # Try to find case-insensitive match
                match = next((k for k in legacy_stats if k.upper() == var.upper()), None)
                if not match:
                    continue
                var_key = match
            else:
                var_key = var

            s = legacy_stats[var_key]
            col = _resolve_column(df, var_key) or var_key
            units = _get_units(col)

            # Defensive: legacy stats are always present per Phase 25, but guard anyway
            try:
                vs = VariableStats(
                    variable=col.upper(),
                    units=units,
                    n_obs=int(s.get("count", 0)),
                    min_val=self._safe_float(s.get("min")),
                    max_val=self._safe_float(s.get("max")),
                    mean_val=self._safe_float(s.get("mean")),
                    median_val=self._safe_float(s.get("median")),
                    surface_mean_0_10m=self._safe_float(s.get("surface")),
                    deep_mean_below_200m=self._safe_float(s.get("deep")),
                    deepest_pres_dbar=self._safe_float(s.get("deepest_pres")),
                    deepest_val=self._safe_float(s.get("deepest_val")),
                )
                out.append(vs)
            except Exception as e:
                logger.warning("Skipping VariableStats for %s: %s", var_key, e)
                continue
        return out

    def _stats_to_features(
        self,
        legacy_stats: Dict[str, Any],
        variables: List[str],
        df: pd.DataFrame,
    ) -> List[VerticalFeature]:
        """
        Map legacy depth keys to VerticalFeature objects and enrich each
        feature with deterministic strength and prominence classifications.

        Step 2 supported features:
        - Thermocline (TEMP grad_depth) – strength = max °C/dbar gradient;
          prominence is strong / moderate / weak by Levitus (1982) thresholds.
        - Halocline (PSAL grad_depth) – strength = max |PSU/dbar| gradient;
          prominence classified by analogous thresholds.
        - Oxygen Minimum (DOXY min_val_depth) – prominence is strong / moderate
          / weak by Paulmier & Ruiz-Pino (2009) hypoxic boundary at 60 µmol/kg.
        - DCM (CHLA max_val_depth) – strength = chlorophyll contrast ratio
          (subsurface max / surface mean); prominence classified by
          Cullen (2015) subsurface threshold and contrast criterion.
        - BBP700: no depth feature in legacy – intentionally skipped.
        """
        features: List[VerticalFeature] = []

        for var in variables:
            # resolve case-insensitive
            stat_key = var if var in legacy_stats else next(
                (k for k in legacy_stats if k.upper() == var.upper()), None
            )
            if not stat_key:
                continue
            s = legacy_stats[stat_key]
            vu = stat_key.upper()

            # Thermocline
            if "TEMP" in vu and "grad_depth" in s:
                depth = self._safe_float(s.get("grad_depth"))
                if depth is not None:
                    strength = self._max_gradient_magnitude(df, stat_key)
                    prominence = self._classify_thermocline_prominence(strength)
                    features.append(
                        VerticalFeature(
                            feature="thermocline",
                            depth_dbar=depth,
                            strength=strength,
                            value_at_feature=None,
                            prominence=prominence,
                            method="max_gradient_20m_plus",
                        )
                    )

            # Halocline
            if "PSAL" in vu and "grad_depth" in s:
                depth = self._safe_float(s.get("grad_depth"))
                if depth is not None:
                    strength = self._max_gradient_magnitude(df, stat_key)
                    prominence = self._classify_halocline_prominence(strength)
                    features.append(
                        VerticalFeature(
                            feature="halocline",
                            depth_dbar=depth,
                            strength=strength,
                            value_at_feature=None,
                            prominence=prominence,
                            method="max_gradient_20m_plus",
                        )
                    )

            # Oxygen Minimum
            if "DOXY" in vu and "min_val_depth" in s:
                depth = self._safe_float(s.get("min_val_depth"))
                val = self._safe_float(s.get("min"))
                if depth is not None:
                    prominence = self._classify_oxygen_minimum_prominence(val)
                    features.append(
                        VerticalFeature(
                            feature="oxygen_minimum",
                            depth_dbar=depth,
                            strength=None,
                            value_at_feature=val,
                            prominence=prominence,
                            method="min_value_below_20m",
                        )
                    )

            # DCM
            if "CHLA" in vu and "max_val_depth" in s:
                depth = self._safe_float(s.get("max_val_depth"))
                val = self._safe_float(s.get("max"))
                surface = self._safe_float(s.get("surface"))
                if depth is not None:
                    contrast = self._dcm_contrast_ratio(val, surface)
                    prominence = self._classify_dcm_prominence(depth, contrast)
                    features.append(
                        VerticalFeature(
                            feature="dcm",
                            depth_dbar=depth,
                            strength=contrast,
                            value_at_feature=val,
                            prominence=prominence,
                            method="max_value_below_20m",
                        )
                    )

            # BBP700 – legacy has no depth feature, only trend text.
            # Intentionally omit VerticalFeature to stay faithful to Step 2 scope.
            # Future steps will add particle_max feature.

        return features

    # ------------------------------------------------------------------
    # Phase 1: deterministic feature classification helpers
    # ------------------------------------------------------------------

    def _max_gradient_magnitude(
        self,
        df: pd.DataFrame,
        var: str,
    ) -> float | None:
        """Compute mean of per-profile maximum gradient magnitudes.

        For TEMP variables, returns the mean (across profiles) of the
        strongest temperature-decrease rate observed below 20 dbar,
        expressed in °C/dbar.

        For PSAL variables, returns the mean (across profiles) of the
        largest absolute salinity gradient observed below 20 dbar,
        expressed in PSU/dbar.

        Returns ``None`` when the variable column or the ``PRES`` column
        is missing, when fewer than two valid samples are present, or
        when the gradient cannot be computed.
        """
        col = _resolve_column(df, var)
        if col is None or "PRES" not in df.columns:
            return None

        magnitudes: list[float] = []
        group_col = self._profile_group_column(df)
        profile_ids = (
            df[group_col].dropna().unique().tolist() if group_col is not None else [None]
        )
        for pid in profile_ids:
            pdf = df if pid is None else df[df[group_col] == pid]
            magnitude = self._profile_max_gradient(pdf, col, var)
            if magnitude is not None:
                magnitudes.append(magnitude)

        if not magnitudes:
            return None
        return float(np.mean(magnitudes))

    @staticmethod
    def _profile_group_column(df: pd.DataFrame) -> str | None:
        """Return the column that uniquely identifies a profile in *df*.

        Prefers ``source_file`` (always added by the QueryEngine),
        falls back to ``float_id``, and returns ``None`` when neither
        column is present (treated as a single profile).
        """
        if "source_file" in df.columns:
            return "source_file"
        if "float_id" in df.columns:
            return "float_id"
        return None

    @staticmethod
    def _profile_max_gradient(
        pdf: pd.DataFrame,
        col: str,
        var: str,
    ) -> float | None:
        """Compute the maximum absolute gradient for a single profile.

        Matches the depth-filter used by
        :py:meth:`ScientificExplanationEngine._compute_stats`
        (samples deeper than 20 dbar) so that the resulting strength is
        consistent with the legacy ``grad_depth`` location.
        """
        if "PRES" not in pdf.columns or col not in pdf.columns:
            return None
        subset = pdf.loc[pdf["PRES"] > 20, ["PRES", col]].dropna()
        if len(subset) < 2:
            return None
        subset = subset.sort_values("PRES")
        p = subset["PRES"].to_numpy(dtype=float)
        v = subset[col].to_numpy(dtype=float)
        dp = np.diff(p)
        dv = np.diff(v)
        with np.errstate(divide="ignore", invalid="ignore"):
            gradient = np.where(dp > 0, dv / dp, np.nan)

        vu = var.upper()
        if "TEMP" in vu:
            # Strongest temperature decrease = most negative gradient.
            strongest = float(np.nanmin(gradient))
            if math.isnan(strongest):
                return None
            return abs(strongest)
        if "PSAL" in vu:
            # Largest absolute salinity gradient.
            abs_grad = np.abs(gradient)
            strongest = float(np.nanmax(abs_grad))
            if math.isnan(strongest):
                return None
            return strongest
        return None

    @staticmethod
    def _classify_thermocline_prominence(
        strength: float | None,
    ) -> ProminenceLabel | None:
        """Classify thermocline prominence from gradient strength (°C/dbar).

        Thresholds based on Levitus (1982) standard thermocline
        definition, as adopted by standard Argo QC criteria.
        """
        if strength is None:
            return None
        if strength >= _THERMOCLINE_STRONG_GRADIENT_C_PER_DBAR:
            return "strong"
        if strength >= _THERMOCLINE_MODERATE_GRADIENT_C_PER_DBAR:
            return "moderate"
        return "weak"

    @staticmethod
    def _classify_halocline_prominence(
        strength: float | None,
    ) -> ProminenceLabel | None:
        """Classify halocline prominence from gradient strength (PSU/dbar).

        Thresholds chosen by analogy with the thermocline thresholds,
        acknowledging that halocline gradients are typically an order
        of magnitude weaker than thermal gradients.
        """
        if strength is None:
            return None
        if strength >= _HALOCLINE_STRONG_GRADIENT_PSU_PER_DBAR:
            return "strong"
        if strength >= _HALOCLINE_MODERATE_GRADIENT_PSU_PER_DBAR:
            return "moderate"
        return "weak"

    @staticmethod
    def _classify_oxygen_minimum_prominence(
        min_oxygen_umolkg: float | None,
    ) -> ProminenceLabel | None:
        """Classify Oxygen Minimum Zone severity from minimum oxygen.

        Thresholds based on Paulmier & Ruiz-Pino (2009) hypoxic
        boundary at ~60 µmol/kg, with a moderate category up to
        150 µmol/kg (the canonical oligotrophic boundary).
        """
        if min_oxygen_umolkg is None:
            return None
        if min_oxygen_umolkg < _OMZ_STRONG_MIN_UMOLKG:
            return "strong"
        if min_oxygen_umolkg < _OMZ_MODERATE_MIN_UMOLKG:
            return "moderate"
        return "weak"

    @staticmethod
    def _dcm_contrast_ratio(
        max_val: float | None,
        surface_val: float | None,
    ) -> float | None:
        """Compute Deep Chlorophyll Maximum contrast ratio.

        The contrast ratio is ``subsurface_max / surface_mean``. A
        value of ``None`` is returned when either input is missing
        or when the surface mean is non-positive (which would yield
        a meaningless ratio).
        """
        if max_val is None or surface_val is None:
            return None
        if surface_val <= 0:
            return None
        return max_val / surface_val

    @staticmethod
    def _classify_dcm_prominence(
        depth_dbar: float | None,
        contrast: float | None,
    ) -> ProminenceLabel | None:
        """Classify Deep Chlorophyll Maximum prominence.

        ``strong`` requires both a depth ≥ 30 dbar (Cullen 2015
        subsurface criterion) and a clear surface-to-subsurface
        contrast (≥ 1.5×). ``moderate`` is a deeper subsurface peak
        without strong surface contrast (depth ≥ 30 dbar but
        contrast < 1.5×). ``weak`` is a shallow subsurface peak
        (depth between 20 and 30 dbar). The 20 dbar lower bound
        is the legacy ``max_val_depth`` filter; depths strictly
        less than 20 dbar cannot be reached through this
        extractor.
        """
        if depth_dbar is None:
            return None
        if depth_dbar < _DCM_STRONG_DEPTH_DBAR:
            return "weak"
        if (
            contrast is not None
            and contrast >= _DCM_STRONG_CONTRAST_RATIO
        ):
            return "strong"
        return "moderate"

    # ------------------------------------------------------------------
    # Phase 2: deterministic cross-variable relationship notes
    # ------------------------------------------------------------------

    def _build_cross_variable_notes(
        self,
        features: list[VerticalFeature],
        stats: list[VariableStats],
        df: pd.DataFrame | None,
    ) -> list[str]:
        """Build deterministic cross-variable relationship notes.

        Notes are emitted only when both relevant features or stats are
        present in the same query and the relationship is fully supported
        by deterministic observations. No mechanism is inferred; the
        wording is descriptive.

        Currently supported relationships (all deterministic):

        - DCM relative to thermocline.
        - DCM relative to halocline.
        - Oxygen minimum relative to thermocline.
        - Oxygen minimum relative to halocline.
        - Oxygen minimum relative to DCM.
        - Surface temperature + salinity regime (evaporative or fresh).
        - CHLA + BBP700 subsurface peak co-location.

        Single-variable queries naturally emit no notes because each
        pair requires both features/stats to be present.
        """
        notes: list[str] = []

        features_by_name: dict[str, VerticalFeature] = {f.feature: f for f in features}
        stats_by_name: dict[str, VariableStats] = {
            s.variable.replace("_ADJUSTED", ""): s for s in stats
        }

        # Vertical feature alignments.
        pairs: list[tuple[str, str]] = [
            ("dcm", "thermocline"),
            ("dcm", "halocline"),
            ("oxygen_minimum", "thermocline"),
            ("oxygen_minimum", "halocline"),
            ("oxygen_minimum", "dcm"),
        ]
        for upper_key, lower_key in pairs:
            upper = features_by_name.get(upper_key)
            lower = features_by_name.get(lower_key)
            if upper is None or lower is None:
                continue
            note = self._vertical_alignment_note(upper, lower)
            if note is not None:
                notes.append(note)
                if len(notes) >= _MAX_CROSS_NOTES:
                    return notes

        # Surface regime from T + S.
        if "TEMP" in stats_by_name and "PSAL" in stats_by_name:
            note = self._surface_regime_note(
                stats_by_name["TEMP"], stats_by_name["PSAL"]
            )
            if note is not None:
                notes.append(note)
                if len(notes) >= _MAX_CROSS_NOTES:
                    return notes

        # CHLA + BBP700 subsurface peak co-location.
        if (
            "CHLA" in stats_by_name
            and "BBP700" in stats_by_name
            and df is not None
        ):
            dcm = features_by_name.get("dcm")
            if dcm is not None and dcm.depth_dbar is not None:
                bbp_depth = self._bbp700_max_depth(df)
                if bbp_depth is not None:
                    note = self._chla_bbp_co_location_note(
                        dcm.depth_dbar, bbp_depth
                    )
                    if note is not None:
                        notes.append(note)

        return notes

    @staticmethod
    def _vertical_alignment_note(
        upper: VerticalFeature,
        lower: VerticalFeature,
    ) -> str | None:
        """Build a deterministic note describing the vertical alignment
        of two ``VerticalFeature`` instances.

        Returns ``None`` when either depth is unavailable. The wording
        is purely descriptive: it reports the depth difference and
        direction without invoking any mechanism.
        """
        if upper.depth_dbar is None or lower.depth_dbar is None:
            return None
        upper_name = _humanize_feature(upper.feature)
        lower_name = _humanize_feature(lower.feature)
        diff = upper.depth_dbar - lower.depth_dbar
        abs_diff = abs(diff)

        if abs_diff < _ALIGNMENT_COINCIDENT_DBAR:
            return (
                f"{upper_name} and {lower_name} coincide in depth at "
                f"{upper.depth_dbar:.0f} dbar."
            )
        if abs_diff < _ALIGNMENT_CLOSE_DBAR:
            direction = "below" if diff > 0 else "above"
            return (
                f"{upper_name} is closely aligned with {lower_name}, "
                f"occurring {abs_diff:.0f} dbar {direction} it."
            )
        direction = "below" if diff > 0 else "above"
        return (
            f"{upper_name} occurs {abs_diff:.0f} dbar {direction} the {lower_name}."
        )

    @staticmethod
    def _surface_regime_note(
        temp_stat: VariableStats,
        psal_stat: VariableStats,
    ) -> str | None:
        """Build a deterministic note describing the surface T/S regime.

        Returns ``None`` when either surface value is unavailable or
        when the values do not cross a well-established oceanographic
        regime threshold. The wording follows the example given in
        the engineering brief: "consistent with evaporative surface
        forcing" / "consistent with precipitation or river input".
        """
        if temp_stat.surface_mean_0_10m is None or psal_stat.surface_mean_0_10m is None:
            return None
        t = temp_stat.surface_mean_0_10m
        s = psal_stat.surface_mean_0_10m
        if t > _EVAPORATIVE_TEMP_C and s > _EVAPORATIVE_SAL_PSU:
            return (
                f"Surface waters are warm ({t:.1f} °C) and saline "
                f"({s:.2f} PSU), consistent with evaporative surface forcing."
            )
        if s < _FRESH_SAL_PSU:
            return (
                f"Surface waters are fresh ({s:.2f} PSU), "
                f"consistent with precipitation or river input."
            )
        return None

    @staticmethod
    def _chla_bbp_co_location_note(
        chla_depth_dbar: float,
        bbp_depth_dbar: float,
    ) -> str | None:
        """Build a deterministic note for CHLA/BBP700 subsurface peaks.

        Returns ``None`` when the peaks are not sufficiently co-located
        to support a meaningful co-location statement; in that case
        no speculative claim is emitted. The wording follows the
        engineering brief: "Elevated particle backscatter coincides
        with enhanced chlorophyll concentrations".
        """
        diff = abs(chla_depth_dbar - bbp_depth_dbar)
        if diff < _CHLA_BBP_COINCIDENT_DBAR:
            return (
                "Particle backscatter peak coincides with the deep "
                f"chlorophyll maximum (within {diff:.0f} dbar)."
            )
        return None

    @staticmethod
    def _bbp700_max_depth(df: pd.DataFrame) -> float | None:
        """Compute the mean of per-profile BBP700 subsurface peak depths.

        Returns ``None`` when the ``BBP700`` (or ``BBP700_ADJUSTED``)
        column or the ``PRES`` column is missing, when no valid
        samples exist below 20 dbar, or when no profile identifier is
        available. Mirrors the legacy ``_compute_stats`` aggregation
        pattern (``PRES > 20``, per-profile max, mean across profiles).
        """
        col = _resolve_column(df, "BBP700")
        if col is None or "PRES" not in df.columns:
            return None

        depths: list[float] = []
        group_col = ScientificFeatureExtractor._profile_group_column(df)
        profile_ids = (
            df[group_col].dropna().unique().tolist()
            if group_col is not None
            else [None]
        )
        for pid in profile_ids:
            pdf = df if pid is None else df[df[group_col] == pid]
            subset = pdf.loc[
                pdf["PRES"] > _BBP700_DEPTH_FILTER_DBAR, ["PRES", col]
            ].dropna()
            if subset.empty:
                continue
            subset = subset.sort_values("PRES")
            max_pres = float(subset.loc[subset[col].idxmax(), "PRES"])
            depths.append(max_pres)

        if not depths:
            return None
        return float(np.mean(depths))

    # ------------------------------------------------------------------
    # Provenance / QC builders
    # ------------------------------------------------------------------

    def _build_provenance(
        self, records: List[MetadataRecord], df: pd.DataFrame
    ) -> RetrievalProvenance:
        dac_list = []
        seen = set()
        for r in records:
            dac = getattr(r, "institution", None)
            if dac and dac not in seen:
                seen.add(dac)
                dac_list.append(dac)

        primary_dac = dac_list[0] if dac_list else None

        # Dates
        dates = [r.date for r in records if getattr(r, "date", None) is not None]
        date_start = min(dates).date().isoformat() if dates else None
        date_end = max(dates).date().isoformat() if dates else None
        average_year = None
        if dates:
            try:
                average_year = sum(d.year for d in dates) / len(dates)
            except Exception:
                average_year = None

        # Data mode counts – parse parameter_data_mode
        mode_counts: Dict[str, int] = {"D": 0, "R": 0, "A": 0}
        for r in records:
            mode_str = getattr(r, "parameter_data_mode", "") or ""
            # Count delayed-mode if 'D' present, else real-time 'R', else adjusted 'A'
            if "D" in mode_str:
                mode_counts["D"] += 1
            elif "R" in mode_str:
                mode_counts["R"] += 1
            else:
                # fallback – treat as adjusted/other
                mode_counts["A"] += 1

        # Remove zero entries for cleanliness (schema allows empty dict default, but we keep keys)
        # keep all keys – schema expects Dict[str,int]

        if mode_counts["D"] >= mode_counts["R"]:
            qc_mode_summary = "delayed-mode dominant"
        elif mode_counts["R"] > 0:
            qc_mode_summary = "real-time present"
        else:
            qc_mode_summary = "mixed"

        gdac_files = []
        seen_files = set()
        for r in records:
            f = getattr(r, "file", None)
            if f and f not in seen_files:
                seen_files.add(f)
                gdac_files.append(f)
            if len(gdac_files) >= _MAX_NARRATION_GDAC_FILES:
                break

        measurement_count = int(len(df)) if df is not None else 0

        return RetrievalProvenance(
            source="Argo GDAC (https://data-argo.ifremer.fr)",
            dac_list=dac_list,
            primary_dac=primary_dac,
            profile_count=len(records),
            measurement_count=measurement_count,
            date_start=date_start,
            date_end=date_end,
            average_year=average_year,
            data_mode_counts=mode_counts,
            qc_mode_summary=qc_mode_summary,
            gdac_files=gdac_files,
        )

    def _build_profiles(self, records: List[MetadataRecord]) -> List[ProfileMeta]:
        profiles: List[ProfileMeta] = []
        seen_floats = set()
        for r in records:
            # Deduplicate by file to avoid duplicate profile entries
            src = getattr(r, "file", None)
            if src in seen_floats:
                continue
            seen_floats.add(src)

            float_id = _extract_float_id(src or "")
            date_str = r.date.isoformat() if getattr(r, "date", None) else None
            # data_mode – first token of parameter_data_mode
            pdm = getattr(r, "parameter_data_mode", "") or ""
            data_mode = pdm.split()[0] if pdm.split() else None

            try:
                pm = ProfileMeta(
                    float_id=float_id or "unknown",
                    profile_date=date_str,
                    latitude=getattr(r, "latitude", None),
                    longitude=getattr(r, "longitude", None),
                    dac=getattr(r, "institution", None),
                    data_mode=data_mode,
                    profile_number=None,
                    # File paths are already represented compactly in provenance.
                    source_file=None,
                )
                profiles.append(pm)
            except Exception as e:
                logger.debug("Skipping profile meta for %s: %s", src, e)
                continue
            if len(profiles) >= _MAX_NARRATION_PROFILES:
                break
        return profiles

    def _build_qc_summary(
        self, records: List[MetadataRecord], variables: List[str], df: pd.DataFrame
    ) -> QCSummary:
        total = len(records) or 1
        delayed = 0
        for r in records:
            mode_str = getattr(r, "parameter_data_mode", "") or ""
            if "D" in mode_str:
                delayed += 1
        delayed_pct = round(delayed / total * 100.0, 1)

        # variables_adjusted – check which requested variables have _ADJUSTED column present
        adjusted: List[str] = []
        if df is not None:
            cols_upper = {c.upper(): c for c in df.columns}
            for v in variables:
                adj = f"{v.upper()}_ADJUSTED"
                if adj in cols_upper:
                    adjusted.append(adj)

        return QCSummary(
            delayed_mode_pct=delayed_pct,
            qc_good_pct=None,
            variables_adjusted=adjusted,
        )

    # ------------------------------------------------------------------
    # Shadow comparison helper
    # ------------------------------------------------------------------

    def compare_with_legacy(
        self,
        df: pd.DataFrame,
        variables: List[str],
        intent: ParsedIntent,
        records: List[MetadataRecord],
    ) -> Dict[str, Any]:
        """
        Run extractor and compare numeric outputs to legacy _compute_stats.
        Returns a dict with match status – used for shadow-mode logging.
        Does NOT raise – logs differences only.
        """
        try:
            # Legacy stats
            legacy_stats = self._legacy_engine._compute_stats(df, variables) if self._legacy_engine else {}
            # New facts
            facts = self.extract(df, variables, intent, records, query_id="shadow-compare")

            # Compare each variable stat
            diffs = []
            for vs in facts.stats:
                # map back to legacy key (strip _ADJUSTED)
                base_var = vs.variable.replace("_ADJUSTED", "")
                # find legacy entry – try exact, upper, base
                legacy_entry = (
                    legacy_stats.get(base_var)
                    or legacy_stats.get(vs.variable)
                    or legacy_stats.get(base_var.upper())
                )
                if not legacy_entry:
                    diffs.append(f"{vs.variable}: no legacy entry")
                    continue

                # compare key numeric fields with tolerance
                checks = [
                    ("mean_val", "mean"),
                    ("min_val", "min"),
                    ("max_val", "max"),
                    ("median_val", "median"),
                    ("surface_mean_0_10m", "surface"),
                    ("deep_mean_below_200m", "deep"),
                ]
                for new_key, old_key in checks:
                    new_v = getattr(vs, new_key)
                    old_v = legacy_entry.get(old_key)
                    if new_v is None or old_v is None:
                        continue
                    # tolerance: 1e-6 relative or 1e-9 absolute
                    if abs(new_v - float(old_v)) > 1e-6 * max(1.0, abs(old_v)):
                        diffs.append(
                            f"{vs.variable} {new_key}: facts={new_v} legacy={old_v}"
                        )

            # Feature count check
            legacy_feature_count = sum(
                1
                for v, s in legacy_stats.items()
                if any(k in s for k in ("grad_depth", "min_val_depth", "max_val_depth"))
            )

            result = {
                "match": len(diffs) == 0,
                "differences": diffs,
                "legacy_vars": list(legacy_stats.keys()),
                "facts_vars": [s.variable for s in facts.stats],
                "legacy_feature_hits": legacy_feature_count,
                "facts_features": len(facts.features),
                "payload_bytes": len(facts.to_llm_payload().encode("utf-8")),
            }
            return result
        except Exception as e:
            logger.exception("Shadow comparison failed: %s", e)
            return {"match": False, "error": str(e), "differences": [str(e)]}

    @staticmethod
    def _safe_float(x: Any) -> Optional[float]:
        try:
            if x is None:
                return None
            import math

            f = float(x)
            if math.isnan(f) or math.isinf(f):
                return None
            return f
        except Exception:
            return None
