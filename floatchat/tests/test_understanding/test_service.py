"""SemanticUnderstandingService — the single LLM interaction of Phase 2.

Covers: semantic representation creation from LLM output, output validation
and every failure mode (→ SemanticUnavailableError → regex fallback), the
feature-flag gates, conversation-context prompt inclusion, and the
understand → deterministic conversion pipeline.
"""

from __future__ import annotations

import pytest

from floatchat.config import settings
from floatchat.models import ConversationContext
from floatchat.understanding import (
    ConversionOutcome,
    SemanticConverter,
    SemanticUnderstanding,
    SemanticUnderstandingService,
    SemanticUnavailableError,
)

from .conftest import CannedLLM

PROFILE_PAYLOAD = {
    "intent_name": "profile_plot",
    "confidence": 0.93,
    "variable_mentions": ["oxygen levels"],
    "region_mentions": ["arabian sea"],
    "temporal": {"year": 2024},
}


class TestUnderstandingCreation:
    def test_valid_json_becomes_semantic_understanding(self, enable_semantic):
        service = SemanticUnderstandingService(service=CannedLLM.for_all(PROFILE_PAYLOAD))
        understanding = service.understand("show oxygen in arabian sea for 2024")
        assert isinstance(understanding, SemanticUnderstanding)
        assert understanding.intent_name == "profile_plot"
        assert understanding.variable_mentions == ["oxygen levels"]
        assert understanding.confidence == 0.93

    def test_markdown_fenced_json_is_tolerated(self, enable_semantic):
        raw = "Sure! Here is the JSON:\n```json\n" + _json_of(PROFILE_PAYLOAD) + "\n```"
        service = SemanticUnderstandingService(service=CannedLLM.for_all(raw))
        understanding = service.understand("anything")
        assert understanding.intent_name == "profile_plot"

    def test_single_llm_call_per_message(self, enable_semantic):
        stub = CannedLLM.for_all(PROFILE_PAYLOAD)
        service = SemanticUnderstandingService(service=stub)
        service.understand("q1")
        service.understand("q2")
        assert stub.call_count == 2

    def test_system_prompt_is_ontology_grounded(self, enable_semantic):
        stub = CannedLLM.for_all(PROFILE_PAYLOAD)
        service = SemanticUnderstandingService(service=stub)
        service.understand("q")
        system = stub.calls[0]["system"]
        assert "arabian sea" in system.lower()
        assert "comparison_plot" in system

    def test_conversation_context_reaches_the_prompt(self, enable_semantic):
        stub = CannedLLM.for_all(PROFILE_PAYLOAD)
        service = SemanticUnderstandingService(service=stub)
        ctx = ConversationContext(
            session_id="s1",
            last_intent="profile_plot",
            last_float_id="2902403",
            last_variables=["DOXY"],
            last_region="arabian_sea",
        )
        service.understand("same but in 2023", conversation_context=ctx)
        prompt = stub.calls[0]["prompt"]
        assert "PRIOR CONVERSATION CONTEXT" in prompt
        assert "2902403" in prompt
        assert "arabian sea" in prompt


class TestFailureModesFallBack:
    def test_invalid_json_raises_unavailable(self, enable_semantic):
        service = SemanticUnderstandingService(
            service=CannedLLM.for_all("this is not json at all")
        )
        with pytest.raises(SemanticUnavailableError):
            service.understand("q")

    def test_non_object_json_raises_unavailable(self, enable_semantic):
        service = SemanticUnderstandingService(service=CannedLLM.for_all("[1, 2, 3]"))
        with pytest.raises(SemanticUnavailableError):
            service.understand("q")

    def test_schema_invalid_payload_raises_unavailable(self, enable_semantic):
        # A genuinely un-coercible payload: an ambiguity record missing its
        # required description. (Tolerated forms — nulls, "none", scalars in
        # list fields — were moved OUT of this failure class by Phase 2.1.)
        bad = {"intent_name": "profile_plot", "ambiguities": [{"field": "region"}]}
        service = SemanticUnderstandingService(service=CannedLLM.for_all(bad))
        with pytest.raises(SemanticUnavailableError):
            service.understand("q")

    def test_empty_output_raises_unavailable(self, enable_semantic):
        service = SemanticUnderstandingService(service=CannedLLM.for_all(""))
        with pytest.raises(SemanticUnavailableError):
            service.understand("q")

    def test_llm_exception_raises_unavailable(self, enable_semantic):
        service = SemanticUnderstandingService(
            service=CannedLLM.for_all(RuntimeError("ollama connection refused"))
        )
        with pytest.raises(SemanticUnavailableError) as exc_info:
            service.understand("q")
        assert "ollama" in str(exc_info.value)

    def test_no_provider_raises_unavailable(self, enable_semantic, monkeypatch):
        monkeypatch.setattr(
            "floatchat.llm_service.factory.build_semantic_llm_service",
            lambda: (_ for _ in ()).throw(RuntimeError("no provider")),
        )
        service = SemanticUnderstandingService()  # nothing injected → lazy factory
        with pytest.raises(SemanticUnavailableError):
            service.understand("q")


class TestFeatureFlagGates:
    def _service(self) -> SemanticUnderstandingService:
        return SemanticUnderstandingService(service=CannedLLM.for_all(PROFILE_PAYLOAD))

    def test_flag_off_raises_unavailable_without_calling_llm(self, monkeypatch):
        monkeypatch.setattr(settings, "semantic_understanding_enabled", False)
        monkeypatch.setattr(settings, "llm_enabled", True)
        monkeypatch.setattr(settings, "semantic_model", "test-model")
        service = self._service()
        with pytest.raises(SemanticUnavailableError):
            service.understand("q")
        assert service._service.call_count == 0

    def test_llm_disabled_raises_unavailable(self, monkeypatch):
        monkeypatch.setattr(settings, "semantic_understanding_enabled", True)
        monkeypatch.setattr(settings, "llm_enabled", False)
        with pytest.raises(SemanticUnavailableError):
            self._service().understand("q")

    def test_empty_model_disables_layer(self, monkeypatch):
        monkeypatch.setattr(settings, "semantic_understanding_enabled", True)
        monkeypatch.setattr(settings, "llm_enabled", True)
        monkeypatch.setattr(settings, "semantic_model", "")
        assert self._service().enabled is False


class TestResolvePipeline:
    def test_resolve_returns_converted_outcome(self, enable_semantic):
        service = SemanticUnderstandingService(service=CannedLLM.for_all(PROFILE_PAYLOAD))
        outcome = service.resolve("show oxygen in arabian sea for 2024")
        assert isinstance(outcome, ConversionOutcome)
        assert outcome.kind == "intent"
        intent = outcome.parsed_intent
        assert intent.intent == "profile_plot"
        assert intent.variables == ["DOXY"]  # grounded through ontology
        assert intent.region == "arabian_sea"
        assert intent.year == 2024

    def test_resolve_propagates_clarification_outcome(self, enable_semantic):
        payload = {
            "intent_name": "profile_plot",
            "confidence": 0.95,
            "variable_mentions": ["it"],
            "requires_clarification": True,
            "clarification_question": "Which variable do you mean?",
        }
        service = SemanticUnderstandingService(service=CannedLLM.for_all(payload))
        outcome = service.resolve("plot it")
        assert outcome.kind == "clarification"
        assert outcome.clarification.question == "Which variable do you mean?"

    def test_injected_converter_is_used(self, enable_semantic):
        class SpyConverter(SemanticConverter):
            def __init__(self):
                super().__init__()
                self.seen = None

            def convert(self, understanding):
                self.seen = understanding
                return super().convert(understanding)

        spy = SpyConverter()
        service = SemanticUnderstandingService(
            service=CannedLLM.for_all(PROFILE_PAYLOAD), converter=spy
        )
        service.resolve("q")
        assert spy.seen is not None
        assert spy.seen.intent_name == "profile_plot"


def _json_of(payload) -> str:
    import json

    return json.dumps(payload)
