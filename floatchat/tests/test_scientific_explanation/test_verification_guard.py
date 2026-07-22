"""Unit tests for strict numeric grounding of scientific narration."""

import logging
from datetime import UTC, datetime

import pytest

from floatchat.exceptions import NarrationVerificationError
from floatchat.scientific_explanation.schemas import (
    NarratorOutput,
    ProfileMeta,
    QCSummary,
    RetrievalProvenance,
    ScientificFacts,
    VariableStats,
    VerticalFeature,
)
from floatchat.scientific_explanation.verification_guard import VerificationGuard


def _facts(
    *,
    variable: str = "DOXY",
    units: str = "µmol/kg",
    min_val: float = 40.0,
    max_val: float = 1000.0,
) -> ScientificFacts:
    provenance = RetrievalProvenance(
        profile_count=1,
        measurement_count=10,
        dac_list=["test_dac"],
        primary_dac="test_dac",
        average_year=2024.0,
        data_mode_counts={"D": 1},
        qc_mode_summary="delayed-mode",
        gdac_files=["test/file.nc"],
    )
    stats = VariableStats(
        variable=variable,
        units=units,
        n_obs=10,
        min_val=min_val,
        max_val=max_val,
        mean_val=125.5,
        median_val=120.0,
        surface_mean_0_10m=200.0,
        deep_mean_below_200m=60.0,
        deepest_pres_dbar=500.0,
        deepest_val=40.0,
    )
    feature = VerticalFeature(
        feature="oxygen_minimum",
        depth_dbar=500.0,
        strength=0.25,
        value_at_feature=40.0,
        prominence="strong",
        method="minimum_value",
    )
    return ScientificFacts(
        schema_version="1.0.0",
        query_id="guard-test",
        generated_at=datetime(2024, 1, 1, tzinfo=UTC),
        variables_requested=[variable],
        provenance=provenance,
        profiles=[
            ProfileMeta(
                float_id="7900000",
                profile_date="2024-01-01",
                latitude=15.0,
                longitude=-65.0,
                dac="test_dac",
                data_mode="D",
                source_file="test/file.nc",
            )
        ],
        stats=[stats],
        features=[feature],
        qc=QCSummary(
            delayed_mode_pct=100.0,
            qc_good_pct=95.0,
            variables_adjusted=[],
        ),
    )


def _output(explanation: str, findings: list[str] | None = None) -> NarratorOutput:
    return NarratorOutput(
        explanation=explanation,
        key_findings=findings or [],
        confidence="high",
    )


def _grounded_text(body: str) -> str:
    return f"The supplied scientific facts support this statement: {body}"


class TestVerificationGuard:
    def test_accepts_narration_without_numeric_claims(self) -> None:
        facts = _facts()
        output = _output(
            "The supplied facts describe a documented oxygen pattern with quality context."
        )

        result = VerificationGuard().verify(output, facts)

        assert result is output

    def test_accepts_all_exact_allowlisted_numeric_formats(self) -> None:
        facts = _facts()
        output = _output(
            _grounded_text(
                "values include 40, 1,000.0, 125.5, 120, 2e2, 6e1, 500, .25, "
                "2024, +15, and −65."
            )
        )

        assert VerificationGuard().verify(output, facts) is output

    def test_checks_numeric_claims_in_key_findings(self) -> None:
        facts = _facts()
        output = _output(
            "The supplied facts describe a documented oxygen pattern with quality context.",
            ["The oxygen minimum is 40 µmol/kg at 500 dbar."],
        )

        assert VerificationGuard().verify(output, facts) is output

    def test_rejects_hallucinated_number_in_explanation(self) -> None:
        facts = _facts()
        output = _output(_grounded_text("the unsupported reported value is 999."))

        with pytest.raises(NarrationVerificationError, match="not grounded") as exc_info:
            VerificationGuard().verify(output, facts)

        assert exc_info.value.details["unsupported_numbers"] == ["999"]

    def test_rejection_logs_numeric_diagnostics_and_parsed_output(
        self,
        caplog,
    ) -> None:
        facts = _facts()
        output = _output(_grounded_text("supported 40 and unsupported 999."))
        caplog.set_level(
            logging.DEBUG,
            logger="floatchat.scientific_explanation.verification_guard",
        )

        with pytest.raises(NarrationVerificationError):
            VerificationGuard().verify(output, facts)

        warning = next(
            record.message
            for record in caplog.records
            if record.levelno == logging.WARNING
        )
        debug = next(
            record.message
            for record in caplog.records
            if record.levelno == logging.DEBUG
        )
        assert "unsupported_numbers=['999']" in warning
        assert "numeric_claim_count=2" in warning
        assert "allowlist_size=" in warning
        assert "Rejected parsed NarratorOutput" in debug
        assert output.explanation in debug

    def test_rejects_hallucinated_number_in_key_findings(self) -> None:
        facts = _facts()
        output = _output(
            "The supplied facts describe a documented oxygen pattern with quality context.",
            ["An unsupported value of 777 is asserted."],
        )

        with pytest.raises(NarrationVerificationError) as exc_info:
            VerificationGuard().verify(output, facts)

        assert exc_info.value.details["unsupported_numbers"] == ["777"]

    def test_rejects_ungrounded_depth_reference(self) -> None:
        """A depth value remains a measurement claim unless facts ground it."""
        facts = _facts()
        output = _output(
            "The supplied facts describe a documented oxygen pattern with quality context.",
            ["An unsupported depth of 777 dbar is claimed."],
        )

        with pytest.raises(NarrationVerificationError) as exc_info:
            VerificationGuard().verify(output, facts)

        assert exc_info.value.details["unsupported_numbers"] == ["777"]

    def test_rejects_rounded_value_not_present_in_allowlist(self) -> None:
        facts = _facts()
        output = _output(_grounded_text("the mean value is 125.4."))

        with pytest.raises(NarrationVerificationError) as exc_info:
            VerificationGuard().verify(output, facts)

        assert exc_info.value.details["unsupported_numbers"] == ["125.4"]

    def test_accepts_equivalent_decimal_representation_without_tolerance(self) -> None:
        facts = _facts()
        output = _output(_grounded_text("the mean value is 125.500."))

        assert VerificationGuard().verify(output, facts) is output

    @pytest.mark.parametrize(
        ("grounded", "narrated"),
        [
            (89.6, "90"),
            (134.7, "135"),
            (0.1684, "0.17"),
            (68.635, "68.6"),
        ],
    )
    def test_accepts_deterministic_decimal_rounding(
        self,
        grounded: float,
        narrated: str,
    ) -> None:
        facts = _facts(min_val=grounded, max_val=grounded)
        output = _output(_grounded_text(f"the displayed value is {narrated}."))

        assert VerificationGuard().verify(output, facts) is output

    @pytest.mark.parametrize(
        ("grounded", "narrated"),
        [
            (331.0, "330"),
            (1480.0, "1500"),
        ],
    )
    def test_accepts_deterministic_power_of_ten_presentation_rounding(
        self,
        grounded: float,
        narrated: str,
    ) -> None:
        facts = _facts(min_val=grounded, max_val=grounded)
        output = _output(_grounded_text(f"the displayed value is {narrated}."))

        assert VerificationGuard().verify(output, facts) is output

    @pytest.mark.parametrize(
        ("grounded", "narrated"),
        [
            (331.0, "340"),
            (1480.0, "1400"),
        ],
    )
    def test_rejects_non_deterministic_power_of_ten_rounding(
        self,
        grounded: float,
        narrated: str,
    ) -> None:
        facts = _facts(min_val=grounded, max_val=grounded)
        output = _output(_grounded_text(f"the displayed value is {narrated}."))

        with pytest.raises(NarrationVerificationError):
            VerificationGuard().verify(output, facts)

    @pytest.mark.parametrize(
        ("grounded", "narrated"),
        [
            (84.4, "90"),
            (134.4, "135"),
            (0.164, "0.17"),
            (68.66, "68.6"),
        ],
    )
    def test_rejects_values_that_are_not_deterministic_roundings(
        self,
        grounded: float,
        narrated: str,
    ) -> None:
        facts = _facts(min_val=grounded, max_val=grounded)
        output = _output(_grounded_text(f"the displayed value is {narrated}."))

        with pytest.raises(NarrationVerificationError):
            VerificationGuard().verify(output, facts)

    def test_rejects_ungrounded_percentage_reference(self) -> None:
        facts = _facts(min_val=80.0, max_val=80.0)
        output = _output(_grounded_text("the quality value is 90%."))

        with pytest.raises(NarrationVerificationError) as exc_info:
            VerificationGuard().verify(output, facts)

        assert exc_info.value.details["unsupported_numbers"] == ["90"]

    def test_accepts_grounded_percentage_reference(self) -> None:
        facts = _facts()
        output = _output(_grounded_text("100% of profiles are delayed-mode."))

        assert VerificationGuard().verify(output, facts) is output

    def test_accepts_literature_year_citation_as_masked(self) -> None:
        """Literature citation years are masked.

        Phase 26 masking protects legitimate literature citations like
        ``(1982)``, ``Levitus (1982)``, ``Paulmier 2009`` from
        false-positive hallucination rejections.
        """
        facts = _facts()
        output = _output(
            _grounded_text(
                "Following Levitus (1982), the thermocline definition is "
                "documented in Paulmier & Ruiz-Pino (2009)."
            )
        )

        assert VerificationGuard().verify(output, facts) is output

    def test_accepts_grounded_depth_reference_with_unit(self) -> None:
        facts = _facts()
        output = _output(
            _grounded_text("The oxygen minimum occurs at 500 dbar.")
        )

        assert VerificationGuard().verify(output, facts) is output

    def test_rejects_derived_arithmetic_not_explicitly_allowlisted(self) -> None:
        facts = _facts()
        output = _output(
            _grounded_text("values 200 and 125.5 imply a derived difference of 74.5.")
        )

        with pytest.raises(NarrationVerificationError) as exc_info:
            VerificationGuard().verify(output, facts)

        assert exc_info.value.details["unsupported_numbers"] == ["74.5"]

    def test_accepts_allowlisted_numbers_attached_to_units(self) -> None:
        facts = _facts()
        output = _output(_grounded_text("oxygen is 40µmol/kg at 500dbar."))

        assert VerificationGuard().verify(output, facts) is output

    def test_range_separator_does_not_turn_second_value_negative(self) -> None:
        facts = _facts()
        output = _output(_grounded_text("the documented interval is 40-60 µmol/kg."))

        assert VerificationGuard().verify(output, facts) is output

    @pytest.mark.parametrize("separator", ["-", "–", "—", " to "])
    def test_accepts_populated_surface_reference_horizon(self, separator: str) -> None:
        facts = _facts()
        stat = facts.stats[0].model_copy(
            update={"surface_mean_0_10m": 201.0, "deep_mean_below_200m": 61.0}
        )
        facts = facts.model_copy(update={"stats": [stat]})
        output = _output(
            _grounded_text(f"the surface reference layer is 0{separator}10 m.")
        )

        assert VerificationGuard().verify(output, facts) is output

    @pytest.mark.parametrize(
        "surface_phrase",
        [
            "surface layer (10 m)",
            "surface-layer 10 m",
            "surface waters within 10 m",
            "upper 10 m",
            "top 10 m",
            "first 10 m",
            "10 m surface layer",
        ],
    )
    def test_accepts_equivalent_surface_layer_ten_meter_phrasing(
        self,
        surface_phrase: str,
    ) -> None:
        facts = _facts()
        stat = facts.stats[0].model_copy(
            update={"surface_mean_0_10m": 201.0, "deep_mean_below_200m": 61.0}
        )
        facts = facts.model_copy(update={"stats": [stat]})
        output = _output(_grounded_text(f"the reference is the {surface_phrase}."))

        assert VerificationGuard().verify(output, facts) is output

    def test_accepts_populated_deep_reference_horizon(self) -> None:
        facts = _facts()
        stat = facts.stats[0].model_copy(
            update={"surface_mean_0_10m": 201.0, "deep_mean_below_200m": 61.0}
        )
        facts = facts.model_copy(update={"stats": [stat]})
        output = _output(_grounded_text("the deep reference mean is below 200 m."))

        assert VerificationGuard().verify(output, facts) is output

    @pytest.mark.parametrize(
        "claim",
        [
            "the unrelated value is 11 m.",
            "the observation is at 201 m.",
        ],
    )
    def test_does_not_globally_allow_reference_numbers(self, claim: str) -> None:
        facts = _facts()
        stat = facts.stats[0].model_copy(
            update={"surface_mean_0_10m": 260.0, "deep_mean_below_200m": 61.0}
        )
        facts = facts.model_copy(update={"stats": [stat]})
        output = _output(_grounded_text(claim))

        with pytest.raises(NarrationVerificationError):
            VerificationGuard().verify(output, facts)

    @pytest.mark.parametrize(
        ("field", "claim"),
        [
            ("surface_mean_0_10m", "the surface reference layer is 0–10 m."),
            ("deep_mean_below_200m", "the deep reference mean is below 200 m."),
        ],
    )
    def test_reference_horizon_requires_populated_schema_field(
        self,
        field: str,
        claim: str,
    ) -> None:
        facts = _facts()
        values = {"surface_mean_0_10m": 260.0, "deep_mean_below_200m": 61.0}
        values[field] = None
        stat = facts.stats[0].model_copy(update={**values, "n_obs": 15})
        provenance = facts.provenance.model_copy(update={"measurement_count": 15})
        feature = facts.features[0].model_copy(update={"strength": 0.75})
        facts = facts.model_copy(
            update={"stats": [stat], "provenance": provenance, "features": [feature]}
        )
        output = _output(_grounded_text(claim))

        with pytest.raises(NarrationVerificationError):
            VerificationGuard().verify(output, facts)

    def test_known_numeric_variable_name_and_unit_exponent_are_not_measurements(self) -> None:
        facts = _facts(variable="BBP700", units="m^-1", min_val=0.001, max_val=0.01)
        output = _output(
            "The supplied BBP700 variable is reported using m^-1 in the scientific facts."
        )

        assert VerificationGuard().verify(output, facts) is output

    def test_unknown_numeric_identifier_is_rejected(self) -> None:
        facts = _facts(variable="BBP700", units="m^-1", min_val=0.001, max_val=0.01)
        output = _output(
            "The narration introduces unknown variable BBP999 without supporting facts."
        )

        with pytest.raises(NarrationVerificationError) as exc_info:
            VerificationGuard().verify(output, facts)

        assert exc_info.value.details["unsupported_numbers"] == ["999"]

    def test_masks_grounded_float_id(self) -> None:
        facts = _facts()
        output = _output(
            "The supplied scientific profile belongs to grounded Argo float 7900000."
        )

        assert VerificationGuard().verify(output, facts) is output

    @pytest.mark.parametrize(
        "identifier",
        [
            "coriolis/7900000/profiles/BR7900000_001.nc",
            "BR7900000_001.nc",
        ],
    )
    def test_masks_grounded_gdac_path_and_filename(self, identifier: str) -> None:
        facts = _facts()
        file_path = "coriolis/7900000/profiles/BR7900000_001.nc"
        profile = facts.profiles[0].model_copy(update={"source_file": file_path})
        provenance = facts.provenance.model_copy(update={"gdac_files": [file_path]})
        facts = facts.model_copy(
            update={"profiles": [profile], "provenance": provenance}
        )
        output = _output(
            _grounded_text(f"the source identifier is {identifier}.")
        )

        assert VerificationGuard().verify(output, facts) is output

    def test_unknown_float_identifier_is_rejected(self) -> None:
        facts = _facts()
        output = _output(
            "The narration introduces unsupported Argo float identifier 7900001."
        )

        with pytest.raises(NarrationVerificationError) as exc_info:
            VerificationGuard().verify(output, facts)

        assert exc_info.value.details["unsupported_numbers"] == ["7900001"]

    def test_accepts_grounded_observation_count(self) -> None:
        facts = _facts()
        output = _output(
            _grounded_text("there are 10 observations in the retrieved profile.")
        )

        assert VerificationGuard().verify(output, facts) is output

    def test_rejects_fabricated_observation_count(self) -> None:
        facts = _facts()
        output = _output(
            _grounded_text("there are 11 observations in the retrieved profile.")
        )

        with pytest.raises(NarrationVerificationError) as exc_info:
            VerificationGuard().verify(output, facts)

        assert exc_info.value.details["unsupported_numbers"] == ["11"]


    def test_masks_only_a_date_present_in_facts(self) -> None:
        facts = _facts()
        grounded = _output(_grounded_text("The profile was observed on 2024-01-01."))
        fabricated = _output(_grounded_text("The profile was observed on 2023-01-01."))

        assert VerificationGuard().verify(grounded, facts) is grounded
        with pytest.raises(NarrationVerificationError):
            VerificationGuard().verify(fabricated, facts)

    def test_accepts_display_value_from_cross_variable_note(self) -> None:
        facts = _facts().model_copy(
            update={"cross_variable_notes": ["Features are separated by 25 dbar."]}
        )
        output = _output(_grounded_text("The supplied features are separated by 25 dbar."))

        assert VerificationGuard().verify(output, facts) is output

    def test_reports_each_distinct_unsupported_numeric_token(self) -> None:
        facts = _facts()
        output = _output(_grounded_text("unsupported values are 999, 999, and 888.0."))

        with pytest.raises(NarrationVerificationError) as exc_info:
            VerificationGuard().verify(output, facts)

        assert exc_info.value.details["unsupported_numbers"] == ["999", "888.0"]
        assert exc_info.value.details["numeric_claim_count"] == 3

    def test_rejects_non_narrator_output_input(self) -> None:
        with pytest.raises(TypeError, match="NarratorOutput"):
            VerificationGuard().verify("not parsed", _facts())  # type: ignore[arg-type]

    def test_rejects_non_scientific_facts_input(self) -> None:
        output = _output(
            "The supplied facts describe a documented oxygen pattern with quality context."
        )

        with pytest.raises(TypeError, match="ScientificFacts"):
            VerificationGuard().verify(output, {})  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        ("allowlist", "reason"),
        [
            ([], "allowlist_not_object"),
            ({"all": "not a list"}, "allowlist_group_not_list"),
            ({"all": [True]}, "allowlist_value_not_numeric"),
            ({"all": ["40"]}, "allowlist_value_not_numeric"),
            ({"all": [float("nan")]}, "allowlist_value_not_finite"),
            ({"all": [float("inf")]}, "allowlist_value_not_finite"),
        ],
    )
    def test_rejects_invalid_numeric_allowlist(
        self,
        monkeypatch,
        allowlist: object,
        reason: str,
    ) -> None:
        facts = _facts()
        output = _output(_grounded_text("the documented value is 40."))
        monkeypatch.setattr(ScientificFacts, "numeric_allowlist", lambda self: allowlist)

        with pytest.raises(NarrationVerificationError) as exc_info:
            VerificationGuard().verify(output, facts)

        assert exc_info.value.details == {"reason": reason}

    def test_validation_error_does_not_echo_full_narration(self) -> None:
        facts = _facts()
        secret = "UNTRUSTED_NARRATION_MUST_NOT_BE_ECHOED"
        output = _output(_grounded_text(f"{secret} claims 999."))

        with pytest.raises(NarrationVerificationError) as exc_info:
            VerificationGuard().verify(output, facts)

        assert secret not in str(exc_info.value)
        assert secret not in repr(exc_info.value.details)
