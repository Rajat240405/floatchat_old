"""Phase 2.1 — Semantic Stabilization regression tests.

Covers the four stabilisation issues from live testing:

1. Explicit ``null`` (or absent) optional concepts must NOT fail validation —
   "Plot dissolved oxygen" simply has no temporal/spatial/comparison content.
2. Requests that failed purely on those optional concepts now complete
   through the semantic pipeline (the success-criteria battery).
3. Per-request instrumentation: outcome, reason, semantic latency, converter
   latency, fallback flag, total understanding latency.
4. Exactly ONE LLM call per resolution — everything else is deterministic.

Fallback remains reserved for: LLM unavailable, malformed JSON, ontology
grounding failure surfaces, genuinely ambiguous understanding.
"""

from __future__ import annotations

import json
import logging
import re

import pytest

from floatchat.understanding import (
    SemanticClarificationNeeded,
    SemanticConverter,
    SemanticUnderstanding,
    SemanticUnderstandingService,
    SemanticUnavailableError,
    convert_to_parsed_intent,
)
from floatchat.understanding.prompt import build_system_prompt
from floatchat.intent_parser.regex import RegexIntentParser
from floatchat.intent_resolution.resolver import IntentResolver

from .conftest import CannedLLM

# --------------------------------------------------------------------------- #
# Issue 1 — optional concepts are naturally absent, not validation errors
# --------------------------------------------------------------------------- #


class TestOptionalConceptsNeverFailValidation:
    """Exact repro of the live-log validation failures: explicit nulls for
    temporal / depth / spatial / comparison / follow_up_reference."""

    def test_explicit_nulls_for_all_optional_concepts_are_accepted(self):
        understanding = SemanticUnderstanding.model_validate(
            {
                "intent_name": "profile_plot",
                "confidence": 0.95,
                "variable_mentions": ["oxygen"],
                "float_ids": ["1902190"],
                # The live-log failure family — all explicit nulls:
                "temporal": None,
                "depth": None,
                "spatial": None,
                "comparison": None,
                "follow_up_reference": None,
                "existence_check": None,
                "profile_number": None,
                "operational_filter": None,
                "region_mentions": None,
                "place_mentions": None,
                "concept_mentions": None,
                "requires_clarification": None,
                "clarification_question": None,
                "ambiguities": None,
            }
        )
        assert understanding.temporal is None
        assert understanding.depth is None
        assert understanding.spatial is None
        assert understanding.comparison is None
        assert understanding.follow_up_reference is None
        assert understanding.existence_check is None
        assert understanding.ambiguities == []
        # And it CONVERTS — the whole point: no fallback for absent concepts.
        outcome = convert_to_parsed_intent(understanding)
        assert outcome.kind == "intent"
        assert outcome.parsed_intent.variables == ["DOXY"]
        assert outcome.parsed_intent.float_id == "1902190"

    def test_absent_concepts_stay_absent(self):
        """No empty objects are fabricated — the model mirrors language."""
        understanding = SemanticUnderstanding.model_validate(
            {
                "intent_name": "profile_plot",
                "confidence": 0.9,
                "variable_mentions": ["dissolved oxygen"],
            }
        )
        assert understanding.temporal is None
        assert understanding.depth is None
        assert understanding.spatial is None
        assert understanding.comparison is None
        outcome = convert_to_parsed_intent(understanding)
        assert outcome.kind == "intent"
        assert outcome.parsed_intent.variables == ["DOXY"]
        assert outcome.parsed_intent.year is None  # nothing invented

    def test_verbose_null_full_coverage_query_converts(self):
        """A null-laden payload WITH temporal/depth content still grounds."""
        outcome = convert_to_parsed_intent(
            SemanticUnderstanding.model_validate(
                {
                    "intent_name": "profile_plot",
                    "confidence": 0.9,
                    "variable_mentions": ["oxygen"],
                    "region_mentions": ["arabian sea"],
                    "temporal": {"year": 2024, "month": None, "season": None},
                    "depth": None,
                    "spatial": None,
                    "comparison": None,
                }
            )
        )
        assert outcome.parsed_intent.year == 2024
        assert outcome.parsed_intent.month is None
        assert outcome.parsed_intent.region == "arabian_sea"

    def test_junk_strings_mean_absent_not_failure(self):
        understanding = SemanticUnderstanding.model_validate(
            {
                "temporal": "none",
                "depth": "n/a",
                "spatial": "null",
                "comparison": "not applicable",
                "follow_up_reference": "no",
                "existence_check": "false",
                "ambiguities": "none mentioned",
            }
        )
        assert (
            understanding.temporal is None
            and understanding.spatial is None
            and understanding.comparison is None
            and understanding.follow_up_reference is False
            and understanding.existence_check is False
            and understanding.ambiguities == []
        )

    def test_genuinely_invalid_payload_still_fails(self, enable_semantic):
        """Tolerance has a floor: an ambiguity record missing its required
        description is still a schema failure (→ reasoned fallback)."""
        service = SemanticUnderstandingService(
            service=CannedLLM.for_all({"ambiguities": [{"field": "x"}]})
        )
        with pytest.raises(SemanticUnavailableError) as exc_info:
            service.understand("q")
        assert exc_info.value.reason == "schema_invalid"


# --------------------------------------------------------------------------- #
# Issue 2 — success-criteria battery completes through the semantic pipeline
# --------------------------------------------------------------------------- #

#: (query, null-laden canned LLM payload, expected (intent, variables,
#: float_id, profile_number)). Payloads deliberately include the explicit
#: nulls that live models produced and that used to force regex fallback.
SUCCESS_CRITERIA = [
    (
        "Plot oxygen profile for float 1902190",
        {
            "intent_name": "profile_plot",
            "confidence": 0.95,
            "variable_mentions": ["oxygen"],
            "float_ids": ["1902190"],
            "temporal": None, "depth": None, "spatial": None,
            "comparison": None, "follow_up_reference": None,
        },
        ("profile_plot", ["DOXY"], "1902190", None),
    ),
    (
        "Show oxygen for float 5906969 profile 142",
        {
            "intent_name": "profile_plot",
            "confidence": 0.96,
            "variable_mentions": ["oxygen"],
            "float_ids": ["5906969"],
            "profile_number": 142,
            "temporal": None, "depth": None, "spatial": None, "comparison": None,
        },
        ("profile_plot", ["DOXY"], "5906969", 142),
    ),
    (
        "Plot O2 profile 5906969",
        {
            "intent_name": "profile_plot",
            "confidence": 0.9,
            "variable_mentions": ["o2"],
            "float_ids": ["5906969"],
            "temporal": None, "comparison": None,
        },
        ("profile_plot", ["DOXY"], "5906969", None),
    ),
    (
        "Plot dissolved oxygen",
        {
            "intent_name": "profile_plot",
            "confidence": 0.85,
            "variable_mentions": ["dissolved oxygen"],
            "temporal": None, "depth": None, "spatial": None,
            "comparison": None, "follow_up_reference": None,
        },
        ("profile_plot", ["DOXY"], None, None),
    ),
    (
        "Show salinity profile",
        {
            "intent_name": "profile_plot",
            "confidence": 0.87,
            "variable_mentions": ["salinity"],
            "temporal": None, "depth": None, "spatial": None, "comparison": None,
        },
        ("profile_plot", ["PSAL"], None, None),
    ),
]


class TestSuccessCriteriaBattery:
    @pytest.mark.parametrize(
        "query,payload,expected",
        SUCCESS_CRITERIA,
        ids=[c[0] for c in SUCCESS_CRITERIA],
    )
    def test_resolves_semantically_without_regex(self, enable_semantic, query, payload, expected):
        stub = CannedLLM.for_all(payload)
        parser = type("CountingParser", (RegexIntentParser,), {"calls": 0})()
        original_parse = parser.parse

        def counting_parse(message):
            parser.calls += 1
            return original_parse(message)

        parser.parse = counting_parse
        resolver = IntentResolver(
            parser=parser,
            understanding=SemanticUnderstandingService(service=stub),
        )
        intent = resolver.resolve(query)

        exp_intent, exp_vars, exp_float, exp_profile = expected
        assert intent.intent == exp_intent
        assert intent.variables == exp_vars
        assert intent.float_id == exp_float
        assert intent.profile_number == exp_profile
        # Issue 2: completed through the semantic pipeline…
        assert parser.calls == 0  # …regex fallback NOT used
        # Issue 4: exactly ONE LLM call
        assert stub.call_count == 1


# --------------------------------------------------------------------------- #
# Issue 3 — instrumentation
# --------------------------------------------------------------------------- #

_LOG_RE = re.compile(r"SEMANTIC_UNDERSTANDING (.*?) msg=", re.DOTALL)


def _fields(record_text: str) -> dict[str, str]:
    """Parse the key=value fields (msg= is last and may itself contain =)."""
    match = _LOG_RE.search(record_text)
    assert match, record_text
    return dict(pair.split("=", 1) for pair in match.group(1).split())


class TestInstrumentation:
    REQUIRED_KEYS = {
        "outcome", "reason", "fallback", "semantic_ms", "convert_ms", "total_ms",
    }

    def test_success_line_has_all_fields(self, enable_semantic, caplog):
        service = SemanticUnderstandingService(
            service=CannedLLM.for_all(
                {
                    "intent_name": "profile_plot",
                    "confidence": 0.9,
                    "variable_mentions": ["oxygen"],
                    "float_ids": ["1902190"],
                }
            )
        )
        with caplog.at_level(logging.INFO, logger="floatchat.understanding.service"):
            service.resolve("plot oxygen for float 1902190")
        fields = _fields(caplog.text)
        assert self.REQUIRED_KEYS <= set(fields)
        assert fields["outcome"] == "intent"
        assert fields["reason"] == "ok"
        assert fields["fallback"] == "false"
        assert fields["intent"] == "profile_plot"
        assert float(fields["semantic_ms"]) >= 0.0
        assert float(fields["convert_ms"]) >= 0.0
        total = float(fields["total_ms"])
        assert total >= float(fields["semantic_ms"]) >= 0.0

    def test_clarification_line_is_not_a_fallback(self, enable_semantic, caplog):
        service = SemanticUnderstandingService(
            service=CannedLLM.for_all(
                {
                    "intent_name": "profile_plot",
                    "confidence": 0.9,
                    "requires_clarification": True,
                    "clarification_question": "Which variable?",
                }
            )
        )
        with caplog.at_level(logging.INFO, logger="floatchat.understanding.service"):
            outcome = service.resolve("plot it")
        assert outcome.kind == "clarification"
        fields = _fields(caplog.text)
        assert fields["outcome"] == "clarification"
        assert fields["fallback"] == "false"

    @pytest.mark.parametrize(
        "payload,reason",
        [
            (RuntimeError("ollama refused"), "llm_error"),
            ("definitely not json", "not_json"),
            ("[1, 2]", "not_json"),
            ("", "empty_output"),
            ({"ambiguities": [{"field": "x"}]}, "schema_invalid"),
        ],
        ids=["llm_error", "malformed_json", "non_object_json", "empty_output", "schema_invalid"],
    )
    def test_failure_lines_carry_reason_and_fallback(
        self, enable_semantic, caplog, payload, reason
    ):
        service = SemanticUnderstandingService(service=CannedLLM.for_all(payload))
        with caplog.at_level(logging.INFO, logger="floatchat.understanding.service"):
            with pytest.raises(SemanticUnavailableError):
                service.resolve("q")
        fields = _fields(caplog.text)
        assert fields["outcome"] == "failure"
        assert fields["reason"] == reason
        assert fields["fallback"] == "true"
        assert float(fields["semantic_ms"]) >= 0.0

    def test_disabled_flag_has_reason_without_llm_call(self, monkeypatch, caplog):
        from floatchat.config import settings

        monkeypatch.setattr(settings, "semantic_understanding_enabled", False)
        stub = CannedLLM.for_all({})
        service = SemanticUnderstandingService(service=stub)
        with caplog.at_level(logging.INFO, logger="floatchat.understanding.service"):
            with pytest.raises(SemanticUnavailableError):
                service.resolve("q")
        fields = _fields(caplog.text)
        assert fields["reason"] == "disabled"
        assert stub.call_count == 0

    def test_resolver_marks_fallback_with_reason(self, enable_semantic, caplog):
        service = SemanticUnderstandingService(
            service=CannedLLM.for_all(RuntimeError("down"))
        )
        resolver = IntentResolver(parser=RegexIntentParser(), understanding=service)
        with caplog.at_level(logging.INFO, logger="floatchat.intent_resolution.resolver"):
            intent = resolver.resolve("show oxygen in arabian sea for 2024")
        assert intent.intent == "profile_plot"  # legacy result served fine
        assert "fallback used=true reason=llm_error" in caplog.text


# --------------------------------------------------------------------------- #
# Issue 4 — one understanding LLM call, everything else deterministic
# --------------------------------------------------------------------------- #


class TestSingleLLMCall:
    def test_resolve_makes_exactly_one_llm_call(self, enable_semantic):
        stub = CannedLLM.for_all(
            {
                "intent_name": "profile_plot",
                "confidence": 0.9,
                "variable_mentions": ["oxygen"],
                "region_mentions": ["arabian sea"],
                "temporal": {"year": 2024},
            }
        )
        service = SemanticUnderstandingService(service=stub)
        outcome = service.resolve("oxygen in arabian sea 2024")
        assert outcome.kind == "intent"
        assert stub.call_count == 1

    def test_resolver_semantic_path_makes_one_llm_call_and_no_compiler(
        self, enable_semantic
    ):
        stub = CannedLLM.for_all(
            {
                "intent_name": "trajectory",
                "confidence": 0.9,
                "float_ids": ["2902403"],
            }
        )
        from unittest.mock import MagicMock

        compiler = MagicMock()
        resolver = IntentResolver(
            parser=MagicMock(wraps=RegexIntentParser()),
            compiler=compiler,
            understanding=SemanticUnderstandingService(service=stub),
        )
        resolver.resolve("ride along float 2902403")
        assert stub.call_count == 1  # the ONLY understanding LLM call
        compiler.compile.assert_not_called()
        resolver.parser.parse.assert_not_called()


# --------------------------------------------------------------------------- #
# Prompt — "omit, don't null" guidance (Phase 2.1 recommendation)
# --------------------------------------------------------------------------- #


class TestOmitNotNullPrompt:
    def test_prompt_requests_field_omission(self):
        prompt = build_system_prompt()
        assert "Omit fields that are not applicable" in prompt
        assert "Do NOT emit null values" in prompt

    def test_prompt_examples_contain_no_null_literals(self):
        prompt = build_system_prompt()
        examples = prompt.split("EXAMPLES", 1)[1]
        assert ": null" not in examples
        assert "null," not in examples

    def test_required_contract_markers_survive(self):
        prompt = build_system_prompt()
        assert "OUTPUT CONTRACT" in prompt
        assert "requires_clarification" in prompt
        assert "ONLY the JSON object" in prompt
