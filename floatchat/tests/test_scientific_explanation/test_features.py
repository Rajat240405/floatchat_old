"""Unit tests for deterministic feature classification in ScientificFacts.

Phase 1 of the enrichment plan: every numeric value still originates from
Python, but the ``ScientificFeatureExtractor`` now also populates
``strength`` and ``prominence`` on each ``VerticalFeature`` using
documented oceanographic thresholds.

These tests exercise the extractor directly to verify that:

- Thermocline gradient magnitude is computed and classified by Levitus (1982).
- Halocline gradient magnitude is computed and classified analogously.
- Oxygen Minimum severity follows Paulmier & Ruiz-Pino (2009).
- Deep Chlorophyll Maximum prominence follows Cullen (2015).
- Per-profile aggregation is performed when ``source_file`` is present.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from floatchat.models import MetadataRecord, ParsedIntent
from floatchat.scientific_explanation.features import ScientificFeatureExtractor
from floatchat.scientific_explanation.schemas import ScientificFacts


def _record(file_path: str = "coriolis/7900000/profiles/BR7900000_001.nc") -> MetadataRecord:
    return MetadataRecord(
        file=file_path,
        date=datetime(2024, 1, 1, tzinfo=UTC),
        latitude=15.0,
        longitude=65.0,
        ocean="I",
        profiler_type="test",
        institution="coriolis",
        parameters="PRES TEMP PSAL DOXY CHLA",
        parameter_data_mode="D D D D D",
        date_update=datetime(2024, 1, 2, tzinfo=UTC),
    )


def _build_dataframe(
    *,
    temp: list[float] | None = None,
    psal: list[float] | None = None,
    doxy: list[float] | None = None,
    chla: list[float] | None = None,
    bbp700: list[float] | None = None,
    pres: list[float] | None = None,
    source_files: list[str] | None = None,
) -> pd.DataFrame:
    """Build a synthetic Argo-like DataFrame.

    All variable columns default to ``None`` (i.e. omitted) so the caller
    can request exactly the variables it needs. ``pres`` defaults to a
    standard Argo-like 5–1000 dbar range.
    """
    if pres is None:
        pres = [5.0, 10.0, 20.0, 30.0, 50.0, 75.0, 100.0, 150.0, 200.0, 300.0, 500.0, 1000.0]
    n = len(pres)
    if source_files is None:
        source_files = ["coriolis/7900000/profiles/BR7900000_001.nc"] * n
    if len(source_files) != n:
        raise ValueError("source_files must have one entry per PRES row")
    data: dict[str, list[float] | list[str]] = {
        "PRES": list(pres),
        "source_file": list(source_files),
        "float_id": ["7900000"] * n,
    }
    if temp is not None:
        if len(temp) != n:
            raise ValueError("temp must have one entry per PRES row")
        data["TEMP"] = list(temp)
    if psal is not None:
        if len(psal) != n:
            raise ValueError("psal must have one entry per PRES row")
        data["PSAL"] = list(psal)
    if doxy is not None:
        if len(doxy) != n:
            raise ValueError("doxy must have one entry per PRES row")
        data["DOXY"] = list(doxy)
    if chla is not None:
        if(len(chla) != n):
            raise ValueError("chla must have one entry per PRES row")
        data["CHLA"] = list(chla)
    if bbp700 is not None:
        if len(bbp700) != n:
            raise ValueError("bbp700 must have one entry per PRES row")
        data["BBP700"] = list(bbp700)
    return pd.DataFrame(data)


def _extract(df: pd.DataFrame, variables: list[str]) -> ScientificFacts:
    intent = ParsedIntent(
        intent="profile_plot",
        variables=variables,
        region="arabian_sea",
    )
    records = [_record()]
    return ScientificFeatureExtractor(use_legacy=True).extract(
        df,
        variables,
        intent,
        records,
    )


class TestThermoclineClassification:
    """Thermocline strength is the strongest temperature-decrease rate
    observed below 20 dbar, expressed in °C/dbar. Prominence is
    classified by Levitus (1982) thresholds.
    """

    def test_thermocline_strength_computed_from_dataframe(self) -> None:
        # Strongest gradient is between PRES=30 (T=25) and PRES=50 (T=20):
        # gradient = (20-25)/(50-30) = -0.25 °C/dbar → |strength| = 0.25.
        df = _build_dataframe(
            temp=[28.5, 28.3, 27.5, 25.0, 20.0, 14.0, 11.0, 8.5, 7.0, 5.5, 4.5, 3.5],
        )
        facts = _extract(df, ["TEMP"])

        thermo = next(f for f in facts.features if f.feature == "thermocline")
        assert thermo.depth_dbar == pytest.approx(50.0, abs=1e-6)
        assert thermo.strength == pytest.approx(0.25, abs=1e-6)
        assert thermo.prominence == "moderate"  # 0.1 <= 0.25 < 0.3
        assert thermo.method == "max_gradient_20m_plus"

    @pytest.mark.parametrize(
        ("temps", "expected_prominence"),
        [
            # Sharp thermocline: gradient ≈ 0.5 °C/dbar → "strong".
            ([28.0, 28.0, 28.0, 28.0, 22.0, 10.0, 9.0, 8.0, 7.0, 6.0, 5.0, 4.0], "strong"),
            # Moderate: gradient ≈ 0.2 °C/dbar.
            ([28.0, 28.0, 27.0, 25.0, 23.0, 21.0, 19.0, 16.0, 14.0, 11.0, 8.0, 5.0], "moderate"),
            # Diffuse: gradient ≈ 0.05 °C/dbar.
            ([28.0, 28.0, 28.0, 27.5, 27.0, 26.5, 26.0, 24.0, 22.0, 18.0, 14.0, 10.0], "weak"),
        ],
    )
    def test_thermocline_prominence_threshold_classification(
        self,
        temps: list[float],
        expected_prominence: str,
    ) -> None:
        df = _build_dataframe(temp=temps)
        facts = _extract(df, ["TEMP"])

        thermo = next(f for f in facts.features if f.feature == "thermocline")
        assert thermo.prominence == expected_prominence

    def test_thermocline_strength_none_when_column_missing(self) -> None:
        df = _build_dataframe()  # No TEMP column.
        facts = _extract(df, ["TEMP"])

        # No TEMP column → no thermocline feature (legacy behavior).
        assert not any(f.feature == "thermocline" for f in facts.features)


class TestAdjustedColumnFallback:
    """Use adjusted measurements only when the column contains usable data."""

    @pytest.mark.parametrize(
        ("variable", "values", "feature"),
        [
            (
                "TEMP",
                [28.0, 28.0, 27.0, 25.0, 20.0, 14.0, 11.0, 8.5, 7.0, 5.5, 4.5, 3.5],
                "thermocline",
            ),
            (
                "PSAL",
                [36.2, 36.2, 36.1, 36.0, 35.9, 35.8, 35.5, 35.2, 35.0, 34.9, 34.8, 34.7],
                "halocline",
            ),
        ],
    )
    def test_all_missing_adjusted_column_falls_back_to_base_column(
        self,
        variable: str,
        values: list[float],
        feature: str,
    ) -> None:
        df = _build_dataframe(**{variable.lower(): values})
        df[f"{variable}_ADJUSTED"] = [float("nan")] * len(df)

        facts = _extract(df, [variable])

        assert facts.stats[0].variable == variable
        assert facts.stats[0].n_obs == len(values)
        assert facts.stats[0].mean_val == pytest.approx(sum(values) / len(values))
        assert any(item.feature == feature for item in facts.features)

    def test_partially_populated_adjusted_column_remains_preferred(self) -> None:
        base = [28.0, 28.0, 27.0, 25.0, 20.0, 14.0, 11.0, 8.5, 7.0, 5.5, 4.5, 3.5]
        adjusted = [float("nan")] + [value + 1.0 for value in base[1:]]
        df = _build_dataframe(temp=base)
        df["TEMP_ADJUSTED"] = adjusted

        facts = _extract(df, ["TEMP"])

        assert facts.stats[0].variable == "TEMP_ADJUSTED"
        assert facts.stats[0].n_obs == len(adjusted) - 1
        assert facts.stats[0].mean_val == pytest.approx(sum(adjusted[1:]) / (len(adjusted) - 1))

    def test_fully_populated_adjusted_column_remains_preferred(self) -> None:
        base = [28.0, 28.0, 27.0, 25.0, 20.0, 14.0, 11.0, 8.5, 7.0, 5.5, 4.5, 3.5]
        adjusted = [value + 1.0 for value in base]
        df = _build_dataframe(temp=base)
        df["TEMP_ADJUSTED"] = adjusted

        facts = _extract(df, ["TEMP"])

        assert facts.stats[0].variable == "TEMP_ADJUSTED"
        assert facts.stats[0].n_obs == len(adjusted)
        assert facts.stats[0].mean_val == pytest.approx(sum(adjusted) / len(adjusted))

    def test_adjusted_column_is_used_when_base_column_is_missing(self) -> None:
        adjusted = [28.0, 28.0, 27.0, 25.0, 20.0, 14.0, 11.0, 8.5, 7.0, 5.5, 4.5, 3.5]
        df = _build_dataframe()
        df["TEMP_ADJUSTED"] = adjusted

        facts = _extract(df, ["TEMP"])

        assert facts.stats[0].variable == "TEMP_ADJUSTED"
        assert facts.stats[0].n_obs == len(adjusted)


class TestHaloclineClassification:
    """Halocline strength is the largest absolute salinity gradient
    observed below 20 dbar, expressed in PSU/dbar. Prominence is
    classified by analogy with the thermal thresholds.
    """

    def test_halocline_strength_computed_from_dataframe(self) -> None:
        # Strongest |gradient| is between PRES=75 (S=35.8) and PRES=100 (S=35.5):
        # gradient = (35.5-35.8)/(100-75) = -0.012 PSU/dbar → strength = 0.012.
        df = _build_dataframe(
            psal=[36.2, 36.2, 36.1, 36.0, 35.9, 35.8, 35.5, 35.2, 35.0, 34.9, 34.8, 34.7],
        )
        facts = _extract(df, ["PSAL"])

        halo = next(f for f in facts.features if f.feature == "halocline")
        assert halo.depth_dbar == pytest.approx(100.0, abs=1e-6)
        assert halo.strength == pytest.approx(0.012, abs=1e-6)
        assert halo.prominence == "weak"  # 0.012 < 0.02 (moderate threshold)
        assert halo.method == "max_gradient_20m_plus"

    def test_halocline_prominence_strong_for_strong_gradient(self) -> None:
        # Sharp halocline: largest |gradient| ≈ 0.08 PSU/dbar (at PRES=75)
        # exceeds the 0.05 strong threshold.
        df = _build_dataframe(
            psal=[37.0, 37.0, 37.0, 37.0, 36.0, 34.0, 33.5, 33.3, 33.2, 33.1, 33.0, 32.9],
        )
        facts = _extract(df, ["PSAL"])

        halo = next(f for f in facts.features if f.feature == "halocline")
        assert halo.strength is not None
        assert halo.strength >= 0.05
        assert halo.prominence == "strong"


class TestOxygenMinimumClassification:
    """OMZ severity follows Paulmier & Ruiz-Pino (2009): < 60 µmol/kg
    hypoxic; 60–150 µmol/kg moderate; ≥ 150 µmol/kg weak/absent.
    """

    @pytest.mark.parametrize(
        ("doxy_min", "expected_prominence"),
        [
            (25.0, "strong"),    # Hypoxic.
            (59.9, "strong"),    # Boundary – hypoxic.
            (60.0, "moderate"),  # Boundary – moderate.
            (120.0, "moderate"), # Intermediate.
            (149.9, "moderate"), # Boundary – moderate.
            (150.0, "weak"),     # Boundary – weak.
            (210.0, "weak"),     # Well-oxygenated.
        ],
    )
    def test_oxygen_minimum_prominence_by_minimum_value(
        self,
        doxy_min: float,
        expected_prominence: str,
    ) -> None:
        # Build a profile where the minimum oxygen is `doxy_min` at depth 200 dbar.
        doxy = [210.0] * 9 + [doxy_min] + [doxy_min + 20.0, doxy_min + 60.0]
        df = _build_dataframe(doxy=doxy)
        facts = _extract(df, ["DOXY"])

        oxy = next(f for f in facts.features if f.feature == "oxygen_minimum")
        assert oxy.value_at_feature == pytest.approx(doxy_min, abs=1e-6)
        assert oxy.prominence == expected_prominence


class TestDcmClassification:
    """DCM contrast ratio is ``subsurface_max / surface_mean``; prominence
    is "strong" when depth ≥ 20 dbar AND contrast ≥ 1.5×, "moderate"
    when subsurface without strong contrast, and "weak" otherwise.
    """

    def test_dcm_strength_is_contrast_ratio(self) -> None:
        # Surface (≤10 dbar) values: 0.05, 0.06, 0.08 → surface_mean ≈ 0.0633.
        # Subsurface max: 0.55 at PRES=75.
        # Expected contrast ≈ 0.55 / 0.0633 ≈ 8.7.
        df = _build_dataframe(
            chla=[0.05, 0.06, 0.08, 0.15, 0.35, 0.55, 0.45, 0.20, 0.10, 0.05, 0.03, 0.02],
        )
        facts = _extract(df, ["CHLA"])

        dcm = next(f for f in facts.features if f.feature == "dcm")
        assert dcm.depth_dbar == pytest.approx(75.0, abs=1e-6)
        assert dcm.strength is not None
        assert dcm.strength > 1.5  # strong contrast.
        assert dcm.prominence == "strong"

    def test_dcm_prominence_moderate_for_subsurface_without_contrast(self) -> None:
        # Surface mean ≈ max → contrast ≈ 1.0 (< 1.5) but depth > 20 → "moderate".
        chla = [0.50, 0.50, 0.50, 0.50, 0.50, 0.50, 0.50, 0.40, 0.30, 0.20, 0.10, 0.05]
        df = _build_dataframe(chla=chla)
        facts = _extract(df, ["CHLA"])

        dcm = next(f for f in facts.features if f.feature == "dcm")
        assert dcm.depth_dbar is not None and dcm.depth_dbar >= 20.0
        assert dcm.strength is not None
        assert dcm.strength < 1.5  # weak contrast.
        assert dcm.prominence == "moderate"

    def test_dcm_prominence_weak_for_shallow_subsurface_peak(self) -> None:
        # The legacy ``max_val_depth`` filter (``PRES > 20``) means depths
        # are always strictly greater than 20 dbar. A "weak" DCM is
        # therefore a shallow subsurface peak (depth between 20 and 30
        # dbar) without strong surface contrast.
        pres = [5.0, 10.0, 20.0, 25.0, 50.0, 75.0, 100.0, 150.0, 200.0, 300.0, 500.0, 1000.0]
        # Maximum below 30 dbar is at PRES=25 (CHLA=0.50). The surface
        # mean over the first three levels (≤ 10 dbar) is high (0.30),
        # so the contrast is below the strong threshold.
        chla = [0.20, 0.30, 0.40, 0.50, 0.40, 0.30, 0.20, 0.10, 0.05, 0.03, 0.02, 0.01]
        df = _build_dataframe(chla=chla, pres=pres)
        facts = _extract(df, ["CHLA"])

        dcm = next(f for f in facts.features if f.feature == "dcm")
        assert dcm.depth_dbar is not None and 20.0 <= dcm.depth_dbar < 30.0
        assert dcm.prominence == "weak"

    def test_dcm_strength_none_when_surface_is_non_positive(self) -> None:
        # Synthetic scenario: all CHLA = 0. The surface_mean is 0, so
        # the contrast ratio is undefined and strength must be None.
        df = _build_dataframe(chla=[0.0] * 12)
        facts = _extract(df, ["CHLA"])

        dcm = next(f for f in facts.features if f.feature == "dcm")
        assert dcm.strength is None
        assert dcm.depth_dbar is not None  # depth is still computed by legacy.


class TestPerProfileAggregation:
    """Strength is averaged across profiles when ``source_file`` is
    present in the DataFrame.
    """

    def test_strength_is_mean_of_per_profile_maxima(self) -> None:
        # Two profiles. Each has its own max gradient.
        pres = [5.0, 10.0, 20.0, 30.0, 50.0, 75.0, 100.0, 150.0, 200.0, 300.0, 500.0, 1000.0]
        # Profile A: gradient of -0.4 °C/dbar at PRES=50 (T drops 26→18).
        temp_a = [28.0, 28.0, 27.0, 26.0, 18.0, 14.0, 10.0, 8.0, 6.0, 5.0, 4.0, 3.0]
        # Profile B: gradient of -0.1 °C/dbar at PRES=50 (T drops 28→26).
        temp_b = [28.0, 28.0, 28.0, 28.0, 26.0, 24.0, 22.0, 20.0, 18.0, 16.0, 14.0, 12.0]
        temp = temp_a + temp_b
        source_files = (
            ["coriolis/7900001/profiles/BR7900001_001.nc"] * len(pres)
            + ["coriolis/7900002/profiles/BR7900002_001.nc"] * len(pres)
        )
        df = _build_dataframe(
            temp=temp,
            source_files=source_files,
            pres=pres + pres,
        )
        records = [
            _record("coriolis/7900001/profiles/BR7900001_001.nc"),
            _record("coriolis/7900002/profiles/BR7900002_001.nc"),
        ]
        intent = ParsedIntent(
            intent="profile_plot",
            variables=["TEMP"],
            region="arabian_sea",
        )
        facts = ScientificFeatureExtractor(use_legacy=True).extract(
            df, ["TEMP"], intent, records,
        )

        thermo = next(f for f in facts.features if f.feature == "thermocline")
        # Mean of 0.4 and 0.1 = 0.25 °C/dbar.
        assert thermo.strength == pytest.approx(0.25, abs=1e-6)
        assert thermo.prominence == "moderate"

    def test_variable_stats_reports_total_valid_observation_count(self) -> None:
        pres = [5.0, 10.0, 25.0, 50.0]
        df = _build_dataframe(
            pres=pres + pres,
            temp=[28.0, 27.0, 20.0, 10.0] * 2,
            source_files=["a/7900001/profiles/R7900001_001.nc"] * len(pres)
            + ["a/7900002/profiles/R7900002_001.nc"] * len(pres),
        )
        facts = _extract(df, ["TEMP"])

        assert facts.stats[0].n_obs == 8


class TestRegression:
    """Backward compatibility: feature names, depth locations, and
    payload size must remain stable.
    """

    def test_feature_names_unchanged(self) -> None:
        df = _build_dataframe(
            temp=[28.5, 28.3, 27.5, 25.0, 20.0, 14.0, 11.0, 8.5, 7.0, 5.5, 4.5, 3.5],
            psal=[36.2, 36.2, 36.1, 36.0, 35.9, 35.8, 35.5, 35.2, 35.0, 34.9, 34.8, 34.7],
            doxy=[210, 210, 205, 180, 130, 90, 60, 35, 25, 30, 50, 80],
            chla=[0.05, 0.06, 0.08, 0.15, 0.35, 0.55, 0.45, 0.20, 0.10, 0.05, 0.03, 0.02],
        )
        facts = _extract(df, ["TEMP", "PSAL", "DOXY", "CHLA"])

        assert {f.feature for f in facts.features} == {
            "thermocline",
            "halocline",
            "oxygen_minimum",
            "dcm",
        }

    def test_payload_size_remains_within_budget(self) -> None:
        df = _build_dataframe(
            temp=[28.5, 28.3, 27.5, 25.0, 20.0, 14.0, 11.0, 8.5, 7.0, 5.5, 4.5, 3.5],
            psal=[36.2, 36.2, 36.1, 36.0, 35.9, 35.8, 35.5, 35.2, 35.0, 34.9, 34.8, 34.7],
            doxy=[210, 210, 205, 180, 130, 90, 60, 35, 25, 30, 50, 80],
            chla=[0.05, 0.06, 0.08, 0.15, 0.35, 0.55, 0.45, 0.20, 0.10, 0.05, 0.03, 0.02],
        )
        facts = _extract(df, ["TEMP", "PSAL", "DOXY", "CHLA"])

        payload = facts.to_llm_payload(max_bytes=4096)
        assert len(payload.encode("utf-8")) <= 4096

    def test_cross_variable_notes_populated_for_multi_variable_query(self) -> None:
        """Phase 2 populates cross_variable_notes for multi-variable queries.

        The deterministic relationships — DCM relative to thermocline,
        Oxygen minimum relative to thermocline, surface T/S regime —
        must all be present for a stratified Arabian Sea profile with
        all four variables requested.
        """
        df = _build_dataframe(
            temp=[28.5, 28.3, 27.5, 25.0, 20.0, 14.0, 11.0, 8.5, 7.0, 5.5, 4.5, 3.5],
            psal=[36.2, 36.2, 36.1, 36.0, 35.9, 35.8, 35.5, 35.2, 35.0, 34.9, 34.8, 34.7],
            doxy=[210, 210, 205, 180, 130, 90, 60, 35, 25, 30, 50, 80],
            chla=[0.05, 0.06, 0.08, 0.15, 0.35, 0.55, 0.45, 0.20, 0.10, 0.05, 0.03, 0.02],
        )
        facts = _extract(df, ["TEMP", "PSAL", "DOXY", "CHLA"])

        # Multi-variable query → cross_variable_notes is non-empty.
        assert len(facts.cross_variable_notes) > 0

        # DCM-thermocline alignment must be reported with a depth value.
        dcm_note = next(
            (n for n in facts.cross_variable_notes if "chlorophyll" in n.lower()),
            None,
        )
        assert dcm_note is not None
        assert "thermocline" in dcm_note.lower()
        assert "dbar" in dcm_note

        # OMZ-thermocline alignment must be reported with a depth value.
        oxy_note = next(
            (
                n
                for n in facts.cross_variable_notes
                if "oxygen minimum" in n.lower()
            ),
            None,
        )
        assert oxy_note is not None
        assert "thermocline" in oxy_note.lower()

        # Evaporative regime must be reported for warm + saline surface.
        regime_note = next(
            (
                n
                for n in facts.cross_variable_notes
                if "evaporative" in n.lower() or "fresh" in n.lower()
            ),
            None,
        )
        assert regime_note is not None


class TestCrossVariableNotes:
    """Phase 2: deterministic cross-variable relationship notes.

    Notes are emitted only when both relevant features or stats are
    present in the same query. Every note is descriptive and grounded
    in observed numeric values; no mechanism is inferred.
    """

    def test_single_variable_query_emits_no_relationship_notes(self) -> None:
        """A single-variable query cannot emit any cross-variable note.

        All relationships require at least two features/stats; a TEMP-only
        query has no DCM, no OMZ, no PSAL, so all relationship slots
        are empty.
        """
        df = _build_dataframe(
            temp=[28.5, 28.3, 27.5, 25.0, 20.0, 14.0, 11.0, 8.5, 7.0, 5.5, 4.5, 3.5],
        )
        facts = _extract(df, ["TEMP"])

        assert facts.cross_variable_notes == []

    def test_dcm_alignment_with_thermocline_reported(self) -> None:
        """DCM must be reported relative to thermocline when both are present."""
        df = _build_dataframe(
            temp=[28.5, 28.3, 27.5, 25.0, 20.0, 14.0, 11.0, 8.5, 7.0, 5.5, 4.5, 3.5],
            chla=[0.05, 0.06, 0.08, 0.15, 0.35, 0.55, 0.45, 0.20, 0.10, 0.05, 0.03, 0.02],
        )
        facts = _extract(df, ["TEMP", "CHLA"])

        dcm_note = next(
            (
                n
                for n in facts.cross_variable_notes
                if "chlorophyll" in n.lower() and "thermocline" in n.lower()
            ),
            None,
        )
        assert dcm_note is not None
        # Direction must be present ("below" or "above").
        assert "below" in dcm_note.lower() or "above" in dcm_note.lower()
        # Depth value must be present.
        assert "dbar" in dcm_note

    def test_dcm_alignment_with_halocline_reported(self) -> None:
        """DCM must be reported relative to halocline when both are present."""
        df = _build_dataframe(
            psal=[36.2, 36.2, 36.1, 36.0, 35.9, 35.8, 35.5, 35.2, 35.0, 34.9, 34.8, 34.7],
            chla=[0.05, 0.06, 0.08, 0.15, 0.35, 0.55, 0.45, 0.20, 0.10, 0.05, 0.03, 0.02],
        )
        facts = _extract(df, ["PSAL", "CHLA"])

        halo_note = next(
            (
                n
                for n in facts.cross_variable_notes
                if "chlorophyll" in n.lower() and "halocline" in n.lower()
            ),
            None,
        )
        assert halo_note is not None

    def test_oxygen_minimum_alignment_with_thermocline_reported(self) -> None:
        """OMZ must be reported relative to thermocline when both are present."""
        df = _build_dataframe(
            temp=[28.5, 28.3, 27.5, 25.0, 20.0, 14.0, 11.0, 8.5, 7.0, 5.5, 4.5, 3.5],
            doxy=[210, 210, 205, 180, 130, 90, 60, 35, 25, 30, 50, 80],
        )
        facts = _extract(df, ["TEMP", "DOXY"])

        oxy_note = next(
            (
                n
                for n in facts.cross_variable_notes
                if "oxygen minimum" in n.lower() and "thermocline" in n.lower()
            ),
            None,
        )
        assert oxy_note is not None
        assert "below" in oxy_note.lower() or "above" in oxy_note.lower()
        assert "dbar" in oxy_note

    def test_oxygen_minimum_alignment_with_dcm_reported(self) -> None:
        """OMZ must be reported relative to DCM when both are present."""
        df = _build_dataframe(
            doxy=[210, 210, 205, 180, 130, 90, 60, 35, 25, 30, 50, 80],
            chla=[0.05, 0.06, 0.08, 0.15, 0.35, 0.55, 0.45, 0.20, 0.10, 0.05, 0.03, 0.02],
        )
        facts = _extract(df, ["DOXY", "CHLA"])

        oxy_dcm_note = next(
            (
                n
                for n in facts.cross_variable_notes
                if "oxygen minimum" in n.lower() and "chlorophyll" in n.lower()
            ),
            None,
        )
        assert oxy_dcm_note is not None

    def test_coincident_alignment_uses_coincide_wording(self) -> None:
        """When two features are within 10 dbar, the note says they coincide.

        Engineered profile: thermocline and DCM at exactly the same depth.
        """
        # Force both thermocline and DCM to ~75 dbar.
        # Thermocline: gradient peak at PRES=75 (T drops sharply 14→11).
        # DCM: max chla at PRES=75.
        df = _build_dataframe(
            temp=[28.5, 28.3, 27.5, 25.0, 20.0, 11.0, 11.0, 8.5, 7.0, 5.5, 4.5, 3.5],
            chla=[0.05, 0.06, 0.08, 0.15, 0.35, 0.55, 0.45, 0.20, 0.10, 0.05, 0.03, 0.02],
        )
        facts = _extract(df, ["TEMP", "CHLA"])

        dcm_note = next(
            (
                n
                for n in facts.cross_variable_notes
                if "chlorophyll" in n.lower() and "thermocline" in n.lower()
            ),
            None,
        )
        assert dcm_note is not None
        # Both at ~75 dbar → "coincide" wording.
        assert "coincide" in dcm_note.lower()

    def test_close_alignment_uses_closely_aligned_wording(self) -> None:
        """When two features are within 30 dbar, the note says closely aligned."""
        # Engineered profile: thermocline at PRES=50, DCM at PRES=75.
        # Difference 25 dbar → closely aligned.
        df = _build_dataframe(
            temp=[28.5, 28.3, 27.5, 25.0, 20.0, 14.0, 11.0, 8.5, 7.0, 5.5, 4.5, 3.5],
            chla=[0.05, 0.06, 0.08, 0.15, 0.35, 0.55, 0.45, 0.20, 0.10, 0.05, 0.03, 0.02],
        )
        facts = _extract(df, ["TEMP", "CHLA"])

        dcm_note = next(
            (
                n
                for n in facts.cross_variable_notes
                if "chlorophyll" in n.lower() and "thermocline" in n.lower()
            ),
            None,
        )
        assert dcm_note is not None
        # Difference 25 dbar → "closely aligned" wording.
        assert "closely aligned" in dcm_note.lower()

    def test_distant_alignment_reports_absolute_separation(self) -> None:
        """When two features are more than 30 dbar apart, the absolute
        depth difference is reported."""
        # Engineered profile: thermocline at PRES=50, OMZ at PRES=200.
        # Difference 150 dbar → far apart.
        df = _build_dataframe(
            temp=[28.5, 28.3, 27.5, 25.0, 20.0, 14.0, 11.0, 8.5, 7.0, 5.5, 4.5, 3.5],
            doxy=[210, 210, 205, 180, 130, 90, 60, 35, 25, 30, 50, 80],
        )
        facts = _extract(df, ["TEMP", "DOXY"])

        oxy_note = next(
            (
                n
                for n in facts.cross_variable_notes
                if "oxygen minimum" in n.lower() and "thermocline" in n.lower()
            ),
            None,
        )
        assert oxy_note is not None
        # Should NOT say "coincide" or "closely aligned".
        assert "coincide" not in oxy_note.lower()
        assert "closely aligned" not in oxy_note.lower()
        # Should report the depth difference.
        assert "dbar" in oxy_note
        assert "150" in oxy_note  # absolute depth difference

    def test_evaporative_regime_reported_for_warm_saline_surface(self) -> None:
        """Warm + saline surface waters must trigger the evaporative note."""
        df = _build_dataframe(
            temp=[28.5, 28.3, 27.5, 25.0, 20.0, 14.0, 11.0, 8.5, 7.0, 5.5, 4.5, 3.5],
            psal=[36.2, 36.2, 36.1, 36.0, 35.9, 35.8, 35.5, 35.2, 35.0, 34.9, 34.8, 34.7],
        )
        facts = _extract(df, ["TEMP", "PSAL"])

        regime_note = next(
            (
                n
                for n in facts.cross_variable_notes
                if "evaporative" in n.lower()
            ),
            None,
        )
        assert regime_note is not None
        # Surface temperature (25.x °C) and salinity (36.x PSU) both present.
        assert "°C" in regime_note
        assert "PSU" in regime_note
        assert "36" in regime_note  # surface salinity starts with 36

    def test_fresh_surface_regime_reported_for_low_salinity(self) -> None:
        """Fresh surface waters (< 33 PSU) must trigger the fresh note."""
        df = _build_dataframe(
            temp=[28.0, 27.8, 27.0, 25.0, 20.0, 14.0, 11.0, 8.5, 7.0, 5.5, 4.5, 3.5],
            psal=[30.5, 30.5, 30.8, 31.0, 32.0, 32.5, 33.0, 33.5, 34.0, 34.5, 34.7, 34.8],
        )
        facts = _extract(df, ["TEMP", "PSAL"])

        regime_note = next(
            (
                n
                for n in facts.cross_variable_notes
                if "fresh" in n.lower()
            ),
            None,
        )
        assert regime_note is not None
        assert "precipitation" in regime_note.lower() or "river" in regime_note.lower()

    def test_no_regime_note_for_neutral_surface(self) -> None:
        """A neutral surface (warm but not saline enough OR cool but not
        fresh enough) must NOT emit a regime note."""
        df = _build_dataframe(
            temp=[16.0, 15.8, 15.0, 14.0, 12.0, 10.0, 8.0, 7.0, 6.0, 5.0, 4.0, 3.5],
            psal=[34.0, 34.0, 34.1, 34.2, 34.3, 34.5, 34.7, 34.8, 34.9, 34.95, 35.0, 35.05],
        )
        facts = _extract(df, ["TEMP", "PSAL"])

        regime_note = next(
            (
                n
                for n in facts.cross_variable_notes
                if "evaporative" in n.lower() or "fresh" in n.lower()
            ),
            None,
        )
        assert regime_note is None

    def test_no_relationship_emitted_when_other_variable_missing(self) -> None:
        """If only one feature is present, no relationship note is emitted.

        e.g. TEMP-only: no DCM, no OMZ → no cross-variable notes.
        """
        df = _build_dataframe(
            temp=[28.5, 28.3, 27.5, 25.0, 20.0, 14.0, 11.0, 8.5, 7.0, 5.5, 4.5, 3.5],
            psal=[36.2, 36.2, 36.1, 36.0, 35.9, 35.8, 35.5, 35.2, 35.0, 34.9, 34.8, 34.7],
        )
        facts = _extract(df, ["TEMP", "PSAL"])

        # No DCM, no OMZ → no relationship notes.
        assert not any(
            "chlorophyll" in n.lower() or "oxygen minimum" in n.lower()
            for n in facts.cross_variable_notes
        )

    def test_chla_bbp_co_location_emitted_when_within_threshold(self) -> None:
        """When BBP700 max depth is within 30 dbar of the DCM, a co-location
        note must be emitted."""
        bbp_profile = [
            0.0005, 0.0006, 0.0008, 0.0010, 0.0012, 0.0015, 0.0014, 0.0010,
            0.0008, 0.0006, 0.0004, 0.0003,
        ]
        df = _build_dataframe(
            chla=[0.05, 0.06, 0.08, 0.15, 0.35, 0.55, 0.45, 0.20, 0.10, 0.05, 0.03, 0.02],
            bbp700=bbp_profile,
        )
        facts = _extract(df, ["CHLA", "BBP700"])

        co_loc_note = next(
            (
                n
                for n in facts.cross_variable_notes
                if "backscatter" in n.lower() and "chlorophyll" in n.lower()
            ),
            None,
        )
        # Both peaks should be near PRES=75 → co-location note expected.
        assert co_loc_note is not None

    def test_no_chla_bbp_note_when_far_apart(self) -> None:
        """When BBP700 max depth is far from the DCM, no co-location note."""
        # CHLA max at PRES=50 (shallow DCM).
        # BBP700 max at PRES=300 (deep particle peak) — distant.
        # Build CHLA so max is at PRES=50:
        chla = [0.05, 0.05, 0.05, 0.05, 0.55, 0.40, 0.30, 0.20, 0.10, 0.05, 0.03, 0.02]
        # Build BBP700 so max is at PRES=300 (below the surface):
        bbp700 = [
            0.0005, 0.0005, 0.0005, 0.0005, 0.0005, 0.0005, 0.0005, 0.0008,
            0.0010, 0.0012, 0.0008, 0.0005,
        ]
        df = _build_dataframe(chla=chla, bbp700=bbp700)
        facts = _extract(df, ["CHLA", "BBP700"])

        co_loc_note = next(
            (
                n
                for n in facts.cross_variable_notes
                if "backscatter" in n.lower() and "chlorophyll" in n.lower()
            ),
            None,
        )
        # Far apart → no co-location note emitted.
        assert co_loc_note is None

    def test_notes_list_capped_at_schema_maximum(self) -> None:
        """The number of notes must never exceed the schema max_length (8)."""
        bbp_profile = [
            0.0005, 0.0006, 0.0008, 0.0010, 0.0012, 0.0015, 0.0014, 0.0010,
            0.0008, 0.0006, 0.0004, 0.0003,
        ]
        df = _build_dataframe(
            temp=[28.5, 28.3, 27.5, 25.0, 20.0, 14.0, 11.0, 8.5, 7.0, 5.5, 4.5, 3.5],
            psal=[36.2, 36.2, 36.1, 36.0, 35.9, 35.8, 35.5, 35.2, 35.0, 34.9, 34.8, 34.7],
            doxy=[210, 210, 205, 180, 130, 90, 60, 35, 25, 30, 50, 80],
            chla=[0.05, 0.06, 0.08, 0.15, 0.35, 0.55, 0.45, 0.20, 0.10, 0.05, 0.03, 0.02],
            bbp700=bbp_profile,
        )
        facts = _extract(df, ["TEMP", "PSAL", "DOXY", "CHLA", "BBP700"])

        assert len(facts.cross_variable_notes) <= 8

    def test_payload_size_within_budget_when_notes_populated(self) -> None:
        """The 4 KB payload budget must be respected even with notes populated."""
        df = _build_dataframe(
            temp=[28.5, 28.3, 27.5, 25.0, 20.0, 14.0, 11.0, 8.5, 7.0, 5.5, 4.5, 3.5],
            psal=[36.2, 36.2, 36.1, 36.0, 35.9, 35.8, 35.5, 35.2, 35.0, 34.9, 34.8, 34.7],
            doxy=[210, 210, 205, 180, 130, 90, 60, 35, 25, 30, 50, 80],
            chla=[0.05, 0.06, 0.08, 0.15, 0.35, 0.55, 0.45, 0.20, 0.10, 0.05, 0.03, 0.02],
        )
        facts = _extract(df, ["TEMP", "PSAL", "DOXY", "CHLA"])

        payload = facts.to_llm_payload(max_bytes=4096)
        assert len(payload.encode("utf-8")) <= 4096

    def test_notes_are_deterministic(self) -> None:
        """Running the extractor twice on the same input must produce
        identical cross_variable_notes (no LLM, no randomness)."""
        df = _build_dataframe(
            temp=[28.5, 28.3, 27.5, 25.0, 20.0, 14.0, 11.0, 8.5, 7.0, 5.5, 4.5, 3.5],
            psal=[36.2, 36.2, 36.1, 36.0, 35.9, 35.8, 35.5, 35.2, 35.0, 34.9, 34.8, 34.7],
            doxy=[210, 210, 205, 180, 130, 90, 60, 35, 25, 30, 50, 80],
            chla=[0.05, 0.06, 0.08, 0.15, 0.35, 0.55, 0.45, 0.20, 0.10, 0.05, 0.03, 0.02],
        )
        facts_1 = _extract(df, ["TEMP", "PSAL", "DOXY", "CHLA"])
        facts_2 = _extract(df, ["TEMP", "PSAL", "DOXY", "CHLA"])

        assert facts_1.cross_variable_notes == facts_2.cross_variable_notes
