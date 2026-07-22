"""Scientific Facts schema – LLM narration data contract.

Phase 26 / Step 1: LLM-driven scientific explanation.

Design principles:
- Python computes ALL numbers – LLM only narrates.
- No DataFrames, no NumPy arrays, no NetCDF objects cross the LLM boundary.
- Payload is compact deterministic JSON (target 1–3 KB, configurable max).
- Every numeric value originates from the Python computation pipeline.
- Schema is versioned for forward compatibility.
- Adding NITRATE, pH, CDOM, DOWNWELLING_PAR etc. requires NO prompt changes –
  new features appear as new VerticalFeature.feature strings.

Safety:
- Pydantic extra="forbid" – rejects unexpected array/timeseries fields.
- Models are frozen (immutable) after construction.
- Explicit runtime validation – no assert statements.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Core scientific measurement structures
# ---------------------------------------------------------------------------


class VariableStats(BaseModel):
    """Descriptive statistics for a single Argo variable – all scalars."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    variable: str = Field(..., description="Canonical Argo variable, e.g. TEMP_ADJUSTED")
    units: str = Field(..., description="Display units: °C, PSU, µmol/kg, mg/m³, m^-1, etc.")
    n_obs: int = Field(..., ge=0)

    min_val: Optional[float] = None
    max_val: Optional[float] = None
    mean_val: Optional[float] = None
    median_val: Optional[float] = None

    surface_mean_0_10m: Optional[float] = Field(
        default=None, description="Mean over ~0–10 m / first 5 levels"
    )
    deep_mean_below_200m: Optional[float] = None

    deepest_pres_dbar: Optional[float] = None
    deepest_val: Optional[float] = None

    @field_validator("variable")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper() if v else v


class VerticalFeature(BaseModel):
    """A detected vertical oceanographic feature – scalar-only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    feature: str = Field(
        ...,
        description=(
            "Feature name: thermocline, halocline, oxygen_minimum, oxycline, "
            "DCM, mixed_layer_depth, nitracline, ph_minimum, euphotic_depth, "
            "cdom_max, particle_max, etc. Open vocabulary – LLM reads literally."
        ),
    )
    depth_dbar: Optional[float] = Field(default=None, ge=0)
    strength: Optional[float] = Field(
        default=None, description="Gradient strength, e.g. °C per 10 dbar"
    )
    value_at_feature: Optional[float] = None
    prominence: Optional[Literal["strong", "moderate", "weak"]] = None
    method: str = Field(..., description="Detection method, e.g. max_gradient_20_300m")

    @field_validator("feature")
    @classmethod
    def _norm(cls, v: str) -> str:
        if not v:
            raise ValueError("feature name required")
        return v.strip().lower()


class ProfileMeta(BaseModel):
    """Minimal profile identification – no measurement arrays."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    float_id: str
    profile_date: Optional[str] = Field(
        default=None, description="ISO-8601 date, e.g. 2024-03-14"
    )
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    dac: Optional[str] = None
    data_mode: Optional[str] = Field(
        default=None, description="D=delayed, R=real-time, A=adjusted"
    )
    profile_number: Optional[int] = Field(default=None, ge=0)
    source_file: Optional[str] = None


class QCSummary(BaseModel):
    """Data-quality summary – scalar only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    delayed_mode_pct: float = Field(..., ge=0, le=100)
    qc_good_pct: Optional[float] = Field(default=None, ge=0, le=100)
    variables_adjusted: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Retrieval provenance – traceability for LLM narratives
# ---------------------------------------------------------------------------


class RetrievalProvenance(BaseModel):
    """Where the data came from – enables traceable scientific narratives."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str = Field(
        default="Argo GDAC (https://data-argo.ifremer.fr)",
        description="Authoritative data source",
    )
    dac_list: List[str] = Field(
        default_factory=list, description="Distinct DAC institutions, e.g. ['incois','coriolis']"
    )
    primary_dac: Optional[str] = None

    profile_count: int = Field(..., ge=0)
    measurement_count: int = Field(..., ge=0)

    date_start: Optional[str] = Field(default=None, description="ISO date, earliest profile")
    date_end: Optional[str] = Field(default=None, description="ISO date, latest profile")
    average_year: Optional[float] = Field(default=None, ge=1900, le=2100)

    data_mode_counts: Dict[str, int] = Field(
        default_factory=dict, description='e.g. {"D":2,"R":0,"A":1}'
    )
    qc_mode_summary: Optional[str] = Field(
        default=None, description='e.g. "delayed-mode dominant", "mixed R/D"'
    )
    gdac_files: List[str] = Field(default_factory=list, max_length=10)

    @field_validator("dac_list", "gdac_files", mode="before")
    @classmethod
    def _dedupe_preserve_order(cls, v):
        if not isinstance(v, list):
            return v
        seen = set()
        out = []
        for item in v:
            if item not in seen:
                seen.add(item)
                out.append(item)
        return out

    @model_validator(mode="after")
    def _check_counts(self):
        if self.profile_count < 0 or self.measurement_count < 0:
            raise ValueError("profile_count/measurement_count must be >=0")
        return self


# ---------------------------------------------------------------------------
# Top-level ScientificFacts – the ONLY object sent to the LLM
# ---------------------------------------------------------------------------


class ScientificFacts(BaseModel):
    """
    Compact, deterministic scientific facts – the sole LLM input.

    Contains NO DataFrames, NO NumPy arrays, NO raw timeseries.
    Typical serialized size: 1–3 KB.
    Every numeric value originates from Python feature extraction.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, validate_assignment=True)

    # Versioning / traceability
    schema_version: str = Field(
        default="1.0.0", description="Semantic version of ScientificFacts schema"
    )
    prompt_version: Optional[str] = Field(
        default="sci_narrator_v1_2026-07", description="LLM prompt template version"
    )
    query_id: str = Field(..., description="Unique request ID for audit")
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    # Query context
    variables_requested: List[str]
    region: Optional[str] = None
    float_id: Optional[str] = None
    year_filter: Optional[int] = Field(default=None, ge=1900, le=2100)

    # Retrieval provenance – non-negotiable traceability
    provenance: RetrievalProvenance

    # Scientific content – scalar only
    profiles: List[ProfileMeta] = Field(default_factory=list, max_length=20)
    stats: List[VariableStats]
    features: List[VerticalFeature] = Field(default_factory=list)
    qc: QCSummary

    # Cross-variable synthesis hints (Python-computed)
    cross_variable_notes: List[str] = Field(
        default_factory=list,
        max_length=8,
        description="Pre-computed relationships, e.g. 'oxycline 23 dbar below thermocline'",
    )

    # ------------------------------------------------------------------
    # Validation – explicit, no assert
    # ------------------------------------------------------------------

    @field_validator("variables_requested", mode="before")
    @classmethod
    def _norm_vars(cls, v):
        if isinstance(v, list):
            out = []
            seen = set()
            for item in v:
                u = str(item).strip().upper()
                if u and u not in seen:
                    seen.add(u)
                    out.append(u)
            return out
        raise ValueError("variables_requested must be a list")

    @field_validator("schema_version")
    @classmethod
    def _check_schema_version(cls, v: str) -> str:
        if not v or not isinstance(v, str):
            raise ValueError("schema_version must be non-empty string")
        # allow e.g. "1.0.0", "1.1", "2.0.0-beta"
        parts = v.split(".")
        if len(parts) < 2:
            raise ValueError("schema_version should be semantic, e.g. '1.0.0'")
        return v

    @model_validator(mode="after")
    def _validate_internal_consistency(self):
        # Provenance counts must be consistent
        prov = self.provenance
        if prov.profile_count != len(self.profiles):
            # Allow profiles to be truncated for payload size (keep first N),
            # but profile_count must be >= len(profiles)
            if prov.profile_count < len(self.profiles):
                raise ValueError(
                    f"provenance.profile_count ({prov.profile_count}) "
                    f"cannot be < len(profiles) ({len(self.profiles)})"
                )
        # variables_requested should cover stats
        stat_vars = {s.variable.split("_ADJUSTED")[0] for s in self.stats}
        # not a hard error – some variables may fail QC – just ensure overlap exists
        req_set = set(self.variables_requested)
        if stat_vars and req_set and stat_vars.isdisjoint(req_set):
            # allow, but log-worthy – do not raise to keep fallback smooth
            pass
        return self

    # ------------------------------------------------------------------
    # Convenience / safety helpers – explicit validation, no assert
    # ------------------------------------------------------------------

    def to_llm_payload(self, max_bytes: Optional[int] = None) -> str:
        """
        Serialize to compact JSON for LLM input.
        Raises ValueError if payload exceeds max_bytes.
        Never includes arrays / DataFrames.
        """
        # Use Pydantic JSON mode so stdlib serialization also handles dates.
        data = self.model_dump(mode="json", exclude_none=True)
        try:
            import orjson

            payload_bytes = orjson.dumps(data)
        except (ImportError, TypeError, ValueError):
            # ``orjson`` is optional; use compact stdlib JSON when unavailable.
            import json

            payload_bytes = json.dumps(data, separators=(",", ":")).encode("utf-8")

        if max_bytes is not None:
            size = len(payload_bytes)
            if size > max_bytes:
                raise ValueError(
                    f"ScientificFacts payload {size} bytes exceeds limit {max_bytes} bytes – "
                    f"truncate profiles/features before LLM call"
                )
        return payload_bytes.decode("utf-8")

    def numeric_allowlist(self) -> dict[str, list[float]]:
        """Build the scalar numeric grounding boundary for narration.

        Every value in this allowlist is already present in, or is a direct
        deterministic rendering of, this ``ScientificFacts`` object.  The
        verifier may therefore accept an exact value or its deterministic
        display rounding, while rejecting fabricated measurements, counts,
        coordinates, and quality percentages.
        """
        nums: list[float] = []

        def add(value: object) -> None:
            if value is None or isinstance(value, bool):
                return
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                return
            if numeric == numeric and numeric not in (float("inf"), float("-inf")):
                nums.append(numeric)

        # Per-variable scalar observations and their explicit observation counts.
        for stat in self.stats:
            add(stat.n_obs)
            for attr in (
                "min_val",
                "max_val",
                "mean_val",
                "median_val",
                "surface_mean_0_10m",
                "deep_mean_below_200m",
                "deepest_pres_dbar",
                "deepest_val",
            ):
                add(getattr(stat, attr))

        # Detected-feature values.
        for feature in self.features:
            add(feature.depth_dbar)
            add(feature.value_at_feature)
            add(feature.strength)

        # Retrieval/QC scalar facts.  These were previously omitted even
        # though they are serialized in ScientificFacts, causing valid count
        # and percentage statements to be rejected by the verifier.
        provenance = self.provenance
        add(provenance.profile_count)
        add(provenance.measurement_count)
        add(provenance.average_year)
        for count in provenance.data_mode_counts.values():
            add(count)
        add(self.qc.delayed_mode_pct)
        add(self.qc.qc_good_pct)

        # Profile scalar facts.
        for profile in self.profiles:
            add(profile.latitude)
            add(profile.longitude)
            add(profile.profile_number)

        # Cross-variable notes are computed by Python and supplied verbatim to
        # the narrator. Their embedded display values are therefore grounded
        # deterministic observations, not LLM arithmetic.
        for note in self.cross_variable_notes:
            for token in re.findall(r"(?<![\w.])[+\-]?(?:\d+(?:\.\d+)?|\.\d+)(?![\w.])", note):
                add(token)

        # Keep full precision values; VerificationGuard applies the only
        # permitted formatting rule (decimal-quantum rounding).
        return {"all": sorted(set(nums))}

    def validate_no_arrays(self) -> None:
        """
        Explicit runtime check: ensure no list-of-lists / array-like
        structures leaked into the payload. Raises ValueError on violation.
        """
        import json

        payload_str = self.model_dump_json(exclude_none=True)
        # Heuristic guards – these strings would indicate raw timeseries leakage
        forbidden_tokens = [
            "profile_idx",
            "level_idx",
            "N_PROF",
            "N_LEVELS",
            "float64",
            "ndarray",
            '"PRES": [',
            '"TEMP": [',
        ]
        lowered = payload_str.lower()
        for tok in forbidden_tokens:
            if tok.lower() in lowered:
                raise ValueError(
                    f"ScientificFacts payload failed array-leak check: "
                    f"forbidden token '{tok}' found – raw arrays must never reach LLM"
                )
        # Size sanity – should be compact
        size = len(payload_str.encode("utf-8"))
        # Soft warning threshold at 8KB – hard limit enforced by caller via max_bytes
        if size > 8192:
            raise ValueError(
                f"ScientificFacts payload unusually large ({size} bytes) – "
                f"likely contains array data; rejected"
            )


# ---------------------------------------------------------------------------
# LLM output contract
# ---------------------------------------------------------------------------


class NarratorOutput(BaseModel):
    """Structured output expected from the LLM narrator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    explanation: str = Field(..., min_length=40, max_length=5000)
    key_findings: List[str] = Field(default_factory=list, max_length=4)
    confidence: Literal["high", "medium", "low"] = "medium"

    @field_validator("explanation")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 40:
            raise ValueError("explanation too short – likely incomplete")
        return v


# ---------------------------------------------------------------------------
# Helper: build a minimal valid ScientificFacts for tests / fallback
# ---------------------------------------------------------------------------


def build_minimal_facts(
    variables_requested: List[str],
    region: Optional[str] = None,
    query_id: str = "test-query",
) -> ScientificFacts:
    """Factory for tests – produces a schema-valid, array-free object."""
    prov = RetrievalProvenance(
        profile_count=1,
        measurement_count=10,
        dac_list=["test_dac"],
        primary_dac="test_dac",
        average_year=2024.0,
        data_mode_counts={"D": 1},
        qc_mode_summary="delayed-mode",
        gdac_files=["test/file.nc"],
    )
    qc = QCSummary(delayed_mode_pct=100.0, qc_good_pct=100.0, variables_adjusted=[])
    return ScientificFacts(
        schema_version="1.0.0",
        query_id=query_id,
        variables_requested=variables_requested,
        region=region,
        provenance=prov,
        profiles=[
            ProfileMeta(
                float_id="7900000",
                profile_date="2024-01-01",
                latitude=15.0,
                longitude=65.0,
                dac="test_dac",
                data_mode="D",
            )
        ],
        stats=[],
        features=[],
        qc=qc,
    )


__all__ = [
    "VariableStats",
    "VerticalFeature",
    "ProfileMeta",
    "QCSummary",
    "RetrievalProvenance",
    "ScientificFacts",
    "NarratorOutput",
    "build_minimal_facts",
]
