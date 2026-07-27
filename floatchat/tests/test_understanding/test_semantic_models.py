"""Semantic representation creation — the understanding contract itself.

These tests pin the shape/tolerance of :class:`SemanticUnderstanding`, the
object the LLM emits (instead of ParsedIntent, which remains the execution
contract).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from floatchat.understanding.models import (
    Ambiguity,
    ComparisonMention,
    SemanticUnderstanding,
)


class TestSemanticUnderstandingCreation:
    def test_full_payload_round_trip(self):
        data = {
            "intent_name": "profile_plot",
            "confidence": 0.92,
            "variable_mentions": ["oxygen", "chlorophyll"],
            "region_mentions": ["arabian sea"],
            "place_mentions": ["goa"],
            "float_ids": ["2902403"],
            "profile_number": 4,
            "temporal": {"year": 2024, "month": 7, "season": "monsoon"},
            "depth": {"min": 0.0, "max": 500.0},
            "spatial": {"lat": 15.0, "lon": 72.0, "radius_km": 100.0},
            "comparison": {"is_comparison": True, "float_ids": ["2902403", "2903467"]},
            "concept_mentions": ["BGC float"],
            "operational_filter": "alive",
            "existence_check": True,
            "follow_up_reference": True,
            "requires_clarification": False,
            "clarification_question": None,
            "ambiguities": [{"field": "region", "description": "two seas", "candidates": ["A"]}],
        }
        understanding = SemanticUnderstanding.model_validate(data)
        assert understanding.intent_name == "profile_plot"
        assert understanding.confidence == 0.92
        assert understanding.variable_mentions == ["oxygen", "chlorophyll"]
        assert understanding.temporal.year == 2024
        assert understanding.temporal.season == "monsoon"
        assert understanding.depth.max == 500.0
        assert understanding.spatial.lat == 15.0
        assert understanding.comparison.is_comparison is True
        assert understanding.ambiguities[0].candidates == ["A"]

    def test_minimal_payload_defaults(self):
        understanding = SemanticUnderstanding.model_validate({})
        assert understanding.intent_name == "unknown"
        assert understanding.confidence == 0.0
        assert understanding.variable_mentions == []
        # Phase 2.1: optional structured concepts are naturally absent (None),
        # not fabricated empty objects.
        assert understanding.temporal is None
        assert understanding.depth is None
        assert understanding.spatial is None
        assert understanding.comparison is None
        assert understanding.requires_clarification is False
        assert understanding.ambiguities == []

    def test_unknown_provider_keys_are_ignored(self):
        data = {
            "intent_name": "trajectory",
            "confidence": 0.8,
            "float_ids": ["2902403"],
            "explanation_of_my_chain_of_thought": "the user asked for a path",
            "parsed_intent": {"intent": "trajectory"},  # must NOT leak through
            "sql": "SELECT * FROM floats",
        }
        understanding = SemanticUnderstanding.model_validate(data)
        assert understanding.float_ids == ["2902403"]
        assert not hasattr(understanding, "parsed_intent")
        assert not hasattr(understanding, "sql")

    def test_scalar_is_wrapped_into_list(self):
        understanding = SemanticUnderstanding.model_validate(
            {"variable_mentions": "temperature", "float_ids": "2902403"}
        )
        assert understanding.variable_mentions == ["temperature"]
        assert understanding.float_ids == ["2902403"]

    def test_non_list_becomes_empty_list(self):
        understanding = SemanticUnderstanding.model_validate({"variable_mentions": 123})
        assert understanding.variable_mentions == []

    def test_blank_items_are_dropped(self):
        understanding = SemanticUnderstanding.model_validate(
            {"variable_mentions": ["oxygen", "  ", None, "chlorophyll"]}
        )
        assert understanding.variable_mentions == ["oxygen", "chlorophyll"]


class TestConfidenceTolerance:
    def test_confidence_above_one_is_clamped(self):
        assert SemanticUnderstanding.model_validate({"confidence": 1.7}).confidence == 1.0

    def test_confidence_below_zero_is_clamped(self):
        assert SemanticUnderstanding.model_validate({"confidence": -0.4}).confidence == 0.0

    def test_confidence_string_is_coerced(self):
        assert SemanticUnderstanding.model_validate({"confidence": "0.75"}).confidence == 0.75

    def test_confidence_garbage_becomes_zero(self):
        assert SemanticUnderstanding.model_validate({"confidence": "high"}).confidence == 0.0

    def test_reasoning_looking_types_in_nested_models_are_ignored(self):
        understanding = SemanticUnderstanding.model_validate(
            {"temporal": {"year": 2024, "why": "monsoon guesses"}, "confidence": 0.5}
        )
        assert understanding.temporal.year == 2024


class TestAmbiguityModel:
    def test_ambiguity_creation(self):
        ambiguity = Ambiguity(
            field="variables",
            description="'potassium' is not an Argo variable",
            candidates=["DOXY", "CHLA"],
        )
        assert ambiguity.field == "variables"
        assert ambiguity.candidates == ["DOXY", "CHLA"]

    def test_ambiguity_candidates_default_empty(self):
        assert Ambiguity(field="region", description="x").candidates == []

    def test_ambiguity_requires_field_and_description(self):
        with pytest.raises(ValidationError):
            Ambiguity.model_validate({"field": "region"})

    def test_comparison_mention_wrapping(self):
        mention = ComparisonMention.model_validate({"float_ids": "2902403"})
        assert mention.float_ids == ["2902403"]
