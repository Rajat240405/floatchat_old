"""Resolver integration — the Phase 2 wiring contract.

    semantic layer ── success ──▶ ParsedIntent
                   └─ failure ──▶ legacy regex parser (identical to pre-Phase-2)

These tests prove: the semantic path is primary when healthy; every failure
mode degrades to the legacy path with byte-identical results; the legacy
path is untouched when the flag is off; and canonical validation still
applies to semantically-produced intents.

Phase 4 change (documented contract update): the keyword-gated resolver
tail (reference-phrase metadata-followup override, context enrichment,
``merge_context``) runs ONLY on the legacy path. On the semantic path,
deterministic Conversation Intelligence resolves references before the
Semantic Reasoner using the structured ``follow_up_reference`` signal —
keyword heuristics no longer post-process semantic output.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from floatchat.exceptions import IntentParseError
from floatchat.intent_parser.regex import RegexIntentParser
from floatchat.intent_resolution.resolver import IntentResolutionError, IntentResolver
from floatchat.models import ConversationContext
from floatchat.understanding import (
    SemanticClarificationNeeded,
    SemanticUnderstandingService,
)

from .conftest import CannedLLM, NullConversationManager

PROFILE_PAYLOAD = {
    "intent_name": "profile_plot",
    "confidence": 0.93,
    "variable_mentions": ["oxygen levels"],
    "region_mentions": ["arabian sea"],
    "temporal": {"year": 2024},
}

#: Realistic queries exercised for fallback parity (all offline-safe: no live
#: geocoding, local gazetteer hits only).
FALLBACK_PARITY_QUERIES = [
    "show oxygen in arabian sea for 2024",
    "temperature profile of float 2902403",
    "tell me about float 1902190",
    "trajectory of float 1901897",
    "how many floats are in bay of bengal",
    "nearest float to goa",
    "compare temperature of 2902403 and 2903467",
    "salinity in arabian sea during monsoon",
]


def legacy_resolver(**kwargs) -> IntentResolver:
    kwargs.setdefault("compiler", None)
    kwargs.setdefault("conversation_manager", None)
    return IntentResolver(parser=RegexIntentParser(), **kwargs)


class TestSemanticPrimaryPath:
    def test_semantic_result_used_and_parser_not_called(self, enable_semantic):
        parser = MagicMock(wraps=RegexIntentParser())
        service = SemanticUnderstandingService(service=CannedLLM.for_all(PROFILE_PAYLOAD))
        resolver = IntentResolver(parser=parser, understanding=service)

        intent = resolver.resolve("how's the o2 situation in arabian waters in 2024")

        parser.parse.assert_not_called()
        assert intent.intent == "profile_plot"
        assert intent.variables == ["DOXY"]
        assert intent.region == "arabian_sea"
        assert intent.year == 2024

    def test_semantic_path_never_calls_legacy_compiler(self, enable_semantic):
        compiler = MagicMock()
        service = SemanticUnderstandingService(service=CannedLLM.for_all(PROFILE_PAYLOAD))
        resolver = IntentResolver(
            parser=RegexIntentParser(), compiler=compiler, understanding=service
        )
        resolver.resolve("oxygen in arabian sea")
        compiler.compile.assert_not_called()

    def test_context_is_supplied_to_the_semantic_layer(self, enable_semantic):
        stub = CannedLLM.for_all(PROFILE_PAYLOAD)
        service = SemanticUnderstandingService(service=stub)
        ctx = ConversationContext(
            session_id="s1", last_intent="profile_plot", last_float_id="2902403"
        )
        resolver = IntentResolver(
            parser=RegexIntentParser(),
            understanding=service,
            conversation_manager=NullConversationManager(context=ctx),
        )
        resolver.resolve("same but in 2023", session_id="s1")
        prompt = stub.calls[0]["prompt"]
        assert "2902403" in prompt  # context rendered into the understanding prompt

    def test_deterministic_tail_runs_on_semantic_output(self, enable_semantic):
        """Metadata-vs-data on the semantic path is decided by the Semantic
        Reasoner from grounded facts (Phase 3/4 contract) — not by the
        legacy keyword reference-phrase override, and the legacy keyword
        merge no longer post-processes semantic output (Phase 4: CI owns
        semantic-path context)."""
        payload = {
            "intent_name": "unknown",
            "confidence": 0.8,
            "float_ids": ["2902403"],
            "concept_mentions": ["sensors"],
        }
        manager = NullConversationManager()
        service = SemanticUnderstandingService(service=CannedLLM.for_all(payload))
        resolver = IntentResolver(
            parser=RegexIntentParser(),
            understanding=service,
            conversation_manager=manager,
        )
        intent = resolver.resolve("what sensors does float 2902403 carry?", session_id="s1")
        assert intent.intent == "metadata_lookup"  # reasoner: float + concept, no variables
        assert intent.float_id == "2902403"
        assert not manager.merge_calls  # legacy merge is skipped on the semantic path

    def test_semantic_output_still_goes_through_validation(self, enable_semantic):
        """profile_number without float_id must fail validation on the semantic
        path exactly like the legacy path."""
        payload = {
            "intent_name": "profile_plot",
            "confidence": 0.9,
            "variable_mentions": ["oxygen"],
            "region_mentions": ["arabian sea"],
            "profile_number": 3,
        }
        service = SemanticUnderstandingService(service=CannedLLM.for_all(payload))
        resolver = IntentResolver(parser=RegexIntentParser(), understanding=service)
        with pytest.raises(IntentResolutionError):
            resolver.resolve("show profile 3")


class TestStructuredAmbiguityEscalation:
    def test_clarification_outcome_raises_semantic_clarification_needed(self, enable_semantic):
        payload = {
            "intent_name": "profile_plot",
            "confidence": 0.95,
            "requires_clarification": True,
            "clarification_question": "Which variable would you like to see?",
        }
        service = SemanticUnderstandingService(service=CannedLLM.for_all(payload))
        resolver = IntentResolver(parser=RegexIntentParser(), understanding=service)
        with pytest.raises(SemanticClarificationNeeded) as exc_info:
            resolver.resolve("plot it")
        assert exc_info.value.message == "Which variable would you like to see?"
        assert "field" in exc_info.value.details

    def test_ungroundable_region_escalates_structurally(self, enable_semantic):
        payload = {
            "intent_name": "region_search",
            "confidence": 0.9,
            "variable_mentions": ["oxygen"],
            "region_mentions": ["baltic sea"],
        }
        service = SemanticUnderstandingService(service=CannedLLM.for_all(payload))
        resolver = IntentResolver(parser=RegexIntentParser(), understanding=service)
        with pytest.raises(SemanticClarificationNeeded) as exc_info:
            resolver.resolve("oxygen levels in the baltic sea")
        assert "baltic sea" in exc_info.value.message
        assert exc_info.value.details["field"] == "region"
        assert "Arabian Sea" in exc_info.value.details["candidates"]


class TestFallbackToRegex:
    @pytest.mark.parametrize("query", FALLBACK_PARITY_QUERIES)
    def test_llm_failure_falls_back_identically(self, enable_semantic, query):
        dead = SemanticUnderstandingService(
            service=CannedLLM.for_all(RuntimeError("provider down"))
        )
        semantic_backed = IntentResolver(
            parser=RegexIntentParser(), understanding=dead
        )
        legacy = legacy_resolver()
        assert semantic_backed.resolve(query).model_dump() == legacy.resolve(query).model_dump()

    def test_llm_failure_still_raises_identically_for_gibberish(self, enable_semantic):
        dead = SemanticUnderstandingService(
            service=CannedLLM.for_all(RuntimeError("provider down"))
        )
        semantic_backed = IntentResolver(parser=RegexIntentParser(), understanding=dead)
        with pytest.raises(IntentParseError) as semantic_exc:
            semantic_backed.resolve("zqxv wubblenaught")
        with pytest.raises(IntentParseError) as legacy_exc:
            legacy_resolver().resolve("zqxv wubblenaught")
        # identical failure surface on both paths (exact same exception type)
        assert type(semantic_exc.value) is type(legacy_exc.value)

    def test_invalid_output_falls_back_identically(self, enable_semantic):
        garbage = SemanticUnderstandingService(service=CannedLLM.for_all("not json"))
        semantic_backed = IntentResolver(parser=RegexIntentParser(), understanding=garbage)
        legacy = legacy_resolver()
        query = "show oxygen in arabian sea for 2024"
        assert semantic_backed.resolve(query).model_dump() == legacy.resolve(query).model_dump()

    def test_regex_parser_is_called_exactly_once_on_fallback(self, enable_semantic):
        parser = MagicMock(wraps=RegexIntentParser())
        dead = SemanticUnderstandingService(
            service=CannedLLM.for_all(RuntimeError("provider down"))
        )
        resolver = IntentResolver(parser=parser, understanding=dead)
        resolver.resolve("show oxygen in arabian sea for 2024")
        assert parser.parse.call_count == 1


class TestFeatureFlagAndCompatibility:
    def test_flag_off_never_calls_llm_and_matches_legacy(self, monkeypatch):
        """Feature-flag rollback: disabled layer = byte-identical pre-Phase-2 pipeline
        and the LLM stub is never even invoked."""
        from floatchat.config import settings

        monkeypatch.setattr(settings, "semantic_understanding_enabled", False)
        stub = CannedLLM.for_all(PROFILE_PAYLOAD)
        service = SemanticUnderstandingService(service=stub)
        resolver = IntentResolver(parser=RegexIntentParser(), understanding=service)
        legacy = legacy_resolver()

        query = "show oxygen in arabian sea for 2024"
        assert resolver.resolve(query).model_dump() == legacy.resolve(query).model_dump()
        assert stub.call_count == 0

    def test_no_understanding_service_is_exactly_the_legacy_pipeline(self):
        """Default constructor (no understanding injected) preserves the old
        resolver contract for all existing call sites."""
        resolver = IntentResolver(parser=RegexIntentParser())
        intent = resolver.resolve("show oxygen in arabian sea for 2024")
        assert intent.intent == "profile_plot"
        assert intent.variables == ["DOXY"]
        assert intent.region == "arabian_sea"
