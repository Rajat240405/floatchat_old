"""Phase 3 — Semantic Reasoner tests (deterministic objective interpretation).

The reasoner is the single authority for execution-intent selection in the
semantic pipeline. It consumes GroundedUtterances (facts from the grounding
stage) and returns ReasoningDecisions with a rule name + resolutions trace.
These tests pin every rule in the deterministic rule table — no LLM anywhere.
"""

from __future__ import annotations

import logging

import pytest

from floatchat.understanding import (
    SemanticUnderstanding,
    SemanticUnderstandingService,
    convert_to_parsed_intent,
)
from floatchat.understanding.reasoner import (
    GroundedUtterance,
    ReasoningDecision,
    SemanticReasoner,
)

from .conftest import CannedLLM

REASONER = SemanticReasoner()


def utter(**overrides) -> GroundedUtterance:
    base = dict(
        intent_hint=None,
        variables=(),
        regions=(),
        comparison_regions=(),
        float_ids=(),
        lat=None,
        lon=None,
        radius_km=None,
        place_mentioned=False,
        profile_number=None,
        existence_check=False,
        operational_filter=None,
    )
    base.update(overrides)
    return GroundedUtterance(**base)


def convert(understanding_fields: dict):
    u = SemanticUnderstanding.model_validate({"confidence": 0.95, **understanding_fields})
    return convert_to_parsed_intent(u)


_LEVELS_8 = ["TEMP", "PSAL", "DOXY", "CHLA", "BBP700", "NITRATE", "PH_IN_SITU_TOTAL", "DOWNWELLING_PAR"]


# --------------------------------------------------------------------------- #
# Discovery vs Measurement
# --------------------------------------------------------------------------- #


class TestDiscoveryVsMeasurement:
    def test_variables_reinterpret_discovery_as_measurement(self):
        decision = REASONER.reason(
            utter(intent_hint="radius_search", variables=("DOXY",), lat=15.3, lon=73.9)
        )
        assert decision.intent == "profile_plot"
        assert decision.rule == "discovery_vs_measurement"
        assert decision.lat == 15.3 and decision.lon == 73.9
        assert any("measurement objective" in r for r in decision.resolutions)

    def test_no_variables_keeps_discovery(self):
        decision = REASONER.reason(
            utter(intent_hint="radius_search", lat=15.3, lon=73.9, radius_km=100.0)
        )
        assert decision.intent == "radius_search"
        assert decision.rule == "discovery_objective"

    def test_nearest_float_keeps_discovery(self):
        decision = REASONER.reason(utter(intent_hint="nearest_float", lat=15.3, lon=73.9))
        assert decision.intent == "nearest_float"

    def test_radius_search_default_radius_applied(self):
        decision = REASONER.reason(utter(intent_hint="radius_search", lat=15.3, lon=73.9))
        assert decision.radius_km == 500.0
        assert any("500" in r for r in decision.resolutions)

    def test_near_goa_battery_pair_through_converter(self):
        measurement = convert(
            {"intent_name": "radius_search", "variable_mentions": ["oxygen"], "place_mentions": ["goa"]}
        )
        discovery = convert({"intent_name": "radius_search", "place_mentions": ["goa"]})
        assert measurement.parsed_intent.intent == "profile_plot"  # NOT radius_search
        assert measurement.parsed_intent.variables == ["DOXY"]
        assert discovery.parsed_intent.intent == "radius_search"    # NOT profile_plot
        assert discovery.parsed_intent.variables == []


# --------------------------------------------------------------------------- #
# Metadata vs Data
# --------------------------------------------------------------------------- #


class TestMetadataVsData:
    def test_metadata_hint_is_metadata(self):
        decision = REASONER.reason(utter(intent_hint="metadata_lookup", float_ids=("5906969",)))
        assert decision.intent == "metadata_lookup"
        assert decision.float_id == "5906969"
        assert decision.rule == "metadata_objective"

    def test_float_without_variables_or_profile_infers_metadata(self):
        decision = REASONER.reason(utter(float_ids=("5906969",)))
        assert decision.intent == "metadata_lookup"
        assert decision.rule == "metadata_vs_data"

    def test_float_plus_variables_is_measurement(self):
        decision = REASONER.reason(utter(float_ids=("5906969",), variables=("DOXY",)))
        assert decision.intent == "profile_plot"
        assert decision.rule == "entity_inference"

    def test_float_with_profile_number_is_measurement_not_metadata(self):
        decision = REASONER.reason(utter(float_ids=("5906969",), profile_number=142))
        assert decision.intent != "metadata_lookup"

    def test_battery_pair_through_converter(self):
        about = convert({"intent_name": "unknown", "float_ids": ["5906969"]})
        plot = convert(
            {"intent_name": "profile_plot", "variable_mentions": ["oxygen"], "float_ids": ["5906969"]}
        )
        assert about.parsed_intent.intent == "metadata_lookup"
        assert plot.parsed_intent.intent == "profile_plot"
        assert plot.parsed_intent.variables == ["DOXY"]


# --------------------------------------------------------------------------- #
# Intent prioritization — specificity precedence
# --------------------------------------------------------------------------- #


class TestSpecificityPrecedence:
    def test_float_plus_place_drops_place_coordinates(self):
        decision = REASONER.reason(
            utter(
                intent_hint="profile_plot",
                variables=("PSAL",),
                float_ids=("1902190",),
                lat=15.3,
                lon=73.9,
                place_mentioned=True,
                profile_number=284,
            )
        )
        assert decision.intent == "profile_plot"
        assert decision.float_id == "1902190"
        assert decision.lat is None and decision.lon is None and decision.radius_km is None
        assert any("specificity precedence" in r and "1902190" in r for r in decision.resolutions)

    def test_full_conflict_case_through_converter(self):
        """'Show salinity near Goa for float 1902190 profile 284' — the float
        + profile + variable objective outranks the location noise."""
        outcome = convert(
            {
                "intent_name": "profile_plot",
                "variable_mentions": ["salinity"],
                "place_mentions": ["goa"],
                "float_ids": ["1902190"],
                "profile_number": 284,
            }
        )
        i = outcome.parsed_intent
        assert (i.intent, i.float_id, i.profile_number) == ("profile_plot", "1902190", 284)
        assert i.variables == ["PSAL"]
        assert i.lat is None and i.lon is None
        assert outcome.reasoning_resolutions and any("specificity" in r for r in outcome.reasoning_resolutions)

    def test_place_only_measurement_keeps_coordinates(self):
        decision = REASONER.reason(
            utter(intent_hint="profile_plot", variables=("DOXY",), lat=15.3, lon=73.9, place_mentioned=True)
        )
        assert (decision.lat, decision.lon) == (15.3, 73.9)

    def test_region_is_kept_alongside_float(self):
        """Named region mentions stay (parser/engine parity); only place-
        derived coordinate scope loses to a float."""
        decision = REASONER.reason(
            utter(
                intent_hint="profile_plot",
                variables=("DOXY",),
                float_ids=("1902190",),
                regions=("arabian_sea",),
            )
        )
        assert decision.region == "arabian_sea"
        assert decision.float_id == "1902190"

    def test_discovery_intent_ignores_specificity_drop(self):
        decision = REASONER.reason(
            utter(intent_hint="nearest_float", float_ids=("1902190",), lat=15.3, lon=73.9)
        )
        assert (decision.lat, decision.lon) == (15.3, 73.9)


# --------------------------------------------------------------------------- #
# Multi-concept reasoning — comparisons & named forms
# --------------------------------------------------------------------------- #


class TestComparisonOrganization:
    def test_region_vs_region(self):
        decision = REASONER.reason(
            utter(
                intent_hint="comparison_plot",
                variables=("DOXY",),
                comparison_regions=("arabian_sea", "bay_of_bengal"),
                existence_comparison_hint=True,
            )
        )
        assert decision.intent == "comparison_plot"
        assert decision.comparison_regions == ("arabian_sea", "bay_of_bengal")
        assert decision.region == "arabian_sea"
        assert decision.variables == ("DOXY",)
        assert decision.rule == "comparison_organization"

    def test_float_vs_float_defaults_variables(self):
        decision = REASONER.reason(
            utter(intent_hint="comparison_plot", float_ids=("5906969", "1902190"))
        )
        assert decision.intent == "comparison_plot"
        assert decision.comparison_float_ids == ("1902190", "5906969")  # sorted
        assert decision.float_id == "1902190"  # primary mirrors engine contract
        assert decision.variables == tuple(_LEVELS_8)

    def test_comparison_followup_skips_variable_default(self):
        decision = REASONER.reason(
            utter(
                intent_hint="comparison_plot",
                comparison_regions=("arabian_sea", "bay_of_bengal"),
                follow_up_reference=True,
            )
        )
        assert decision.variables == ()
        assert any("inherit" in r for r in decision.resolutions)

    def test_two_floats_alone_imply_comparison(self):
        decision = REASONER.reason(utter(intent_hint="profile_plot", float_ids=("1902190", "5906969")))
        assert decision.intent == "comparison_plot"
        assert decision.comparison_float_ids == ("1902190", "5906969")

    def test_ts_diagram_default_variables(self):
        decision = REASONER.reason(utter(intent_hint="ts_diagram", regions=("bay_of_bengal",)))
        assert decision.variables == ("TEMP", "PSAL")
        assert decision.rule == "named_scientific_form"

    def test_time_form_default_variable(self):
        for hint in ("time_series", "hovmoller"):
            decision = REASONER.reason(utter(intent_hint=hint, regions=("arabian_sea",)))
            assert decision.variables == ("TEMP",)

    def test_named_form_with_explicit_variables_not_defaulted(self):
        decision = REASONER.reason(
            utter(intent_hint="hovmoller", variables=("DOXY",), regions=("indian_ocean",))
        )
        assert decision.variables == ("DOXY",)


# --------------------------------------------------------------------------- #
# Ambiguity resolution — rank deterministically, clarify only when stuck
# --------------------------------------------------------------------------- #


class TestAmbiguityResolution:
    def test_comparison_without_second_side_clarifies(self):
        decision = REASONER.reason(
            utter(intent_hint="comparison_plot", variables=("DOXY",), existence_comparison_hint=True)
        )
        assert decision.clarification is not None
        assert decision.rule == "comparison_incomplete"
        assert "compare" in decision.clarification.question.lower()

    def test_incomplete_comparison_through_converter(self):
        outcome = convert(
            {
                "intent_name": "comparison_plot",
                "variable_mentions": ["oxygen"],
                "comparison": {"is_comparison": True},
            }
        )
        assert outcome.kind == "clarification"
        assert outcome.reasoning_rule == "comparison_incomplete"

    def test_unusable_hint_with_only_scopeless_nothing_stays_unknown(self):
        decision = REASONER.reason(utter())
        assert decision.intent == "unknown"
        assert decision.rule == "unresolved_hint"

    def test_variables_plus_region_without_hint_infers_region_measurement(self):
        decision = REASONER.reason(utter(variables=("DOXY",), regions=("arabian_sea",)))
        assert decision.intent == "region_search"
        assert decision.rule == "entity_inference"

    def test_variables_only_without_hint_infers_profile_measurement(self):
        decision = REASONER.reason(utter(variables=("PSAL",)))
        assert decision.intent == "profile_plot"

    def test_deterministic_reasoning_is_repeatable(self):
        g = utter(intent_hint="radius_search", variables=("DOXY",), lat=15.3, lon=73.9)
        assert REASONER.reason(g) == REASONER.reason(g)


# --------------------------------------------------------------------------- #
# Reasoner purity + single-authority observability
# --------------------------------------------------------------------------- #


class TestReasonerPurity:
    def test_reasoner_module_has_no_service_or_engine_imports(self):
        import ast
        import inspect

        from floatchat.understanding import reasoner as reasoner_module

        tree = ast.parse(inspect.getsource(reasoner_module))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        for forbidden in (
            "floatchat.llm_service",
            "floatchat.data_lake",
            "floatchat.query_engine",
            "floatchat.retrieval_planner",
            "duckdb",
        ):
            assert not any(
                mod == forbidden or mod.startswith(forbidden + ".")
                for mod in imported
            ), forbidden

    def test_reasoner_accepts_grounded_facts_not_understanding(self):
        with pytest.raises(TypeError):
            REASONER.reason(SemanticUnderstanding())  # type: ignore[arg-type]

    def test_grounded_utterance_is_frozen(self):
        g = utter()
        with pytest.raises(Exception):
            g.variables = ("HACK",)  # type: ignore[misc]


class TestSingleAuthorityTrace:
    def test_conversion_outcome_carries_rule_and_resolutions(self):
        outcome = convert(
            {"intent_name": "radius_search", "variable_mentions": ["oxygen"], "place_mentions": ["goa"]}
        )
        assert outcome.reasoning_rule == "discovery_vs_measurement"
        assert outcome.reasoning_resolutions

    def test_passthrough_outcome_still_records_rule(self):
        outcome = convert(
            {"intent_name": "profile_plot", "variable_mentions": ["oxygen"], "region_mentions": ["arabian sea"]}
        )
        assert outcome.reasoning_rule == "hint_passthrough"

    def test_instrumentation_line_includes_rule(self, enable_semantic, caplog):
        service = SemanticUnderstandingService(
            service=CannedLLM.for_all(
                {
                    "intent_name": "profile_plot",
                    "confidence": 0.9,
                    "variable_mentions": ["oxygen"],
                    "region_mentions": ["arabian sea"],
                }
            )
        )
        with caplog.at_level(logging.INFO, logger="floatchat.understanding.service"):
            service.resolve("oxygen in arabian sea")
        assert "rule=hint_passthrough" in caplog.text

    def test_reasoning_trace_is_logged(self, enable_semantic, caplog):
        service = SemanticUnderstandingService(
            service=CannedLLM.for_all(
                {
                    "intent_name": "radius_search",
                    "confidence": 0.9,
                    "variable_mentions": ["oxygen"],
                    "place_mentions": ["goa"],
                }
            )
        )
        with caplog.at_level(logging.INFO, logger="floatchat.understanding.converter"):
            service.resolve("show oxygen near goa")
        assert "SEMANTIC_REASONING rule=discovery_vs_measurement" in caplog.text
        assert "measurement objective" in caplog.text
