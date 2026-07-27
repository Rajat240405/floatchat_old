"""End-to-end /chat orchestration with the semantic layer (Phase 2).

Covers the user-visible wiring through ``handle_chat``: semantic success →
the converted ParsedIntent reaches the QueryEngine; structured ambiguity →
the existing "clarification" response pseudo-intent (schema unchanged); LLM
failure → the regex fallback answers exactly as pre-Phase-2.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from floatchat.api.schemas import ChatRequest
from floatchat.api.services.chat_service import handle_chat
from floatchat.intent_parser.regex import RegexIntentParser
from floatchat.intent_resolution.resolver import IntentResolver
from floatchat.llm_service.classifier import QueryClassifier
from floatchat.models import ChatResponse
from floatchat.understanding import SemanticUnderstandingService

from .conftest import CannedLLM, NullConversationManager

PROFILE_PAYLOAD = {
    "intent_name": "profile_plot",
    "confidence": 0.94,
    "variable_mentions": ["oxygen levels"],
    "region_mentions": ["arabian sea"],
    "temporal": {"year": 2024},
}

CLARIFICATION_PAYLOAD = {
    "intent_name": "profile_plot",
    "confidence": 0.95,
    "requires_clarification": True,
    "clarification_question": "Which variable would you like to see plotted?",
}


def _engine():
    engine = MagicMock()
    engine.execute = MagicMock(
        return_value=ChatResponse(
            intent="profile_plot",
            message="engine answered",
            figure=None,
            data_summary={"matched_records": 1},
            map_data=[],
        )
    )
    return engine


def _run_chat(message: str, resolver: IntentResolver, engine=None):
    engine = engine or _engine()
    manager = NullConversationManager()
    args = {
        "request": ChatRequest(message=message, session_id=None),
        "classifier": MagicMock(spec=QueryClassifier),
        "llm_service": MagicMock(),
        "intent_parser": getattr(resolver, "parser", RegexIntentParser()),
        "intent_resolver": resolver,
        "query_engine": engine,
        "conversation_manager": manager,
        "knowledge_base": MagicMock(),
    }
    with patch.object(QueryClassifier, "classify", return_value="DATA_QUERY"):
        response = handle_chat(**args)
    return response, engine


class TestChatSemanticSuccess:
    def test_converted_intent_reaches_query_engine(self, enable_semantic):
        service = SemanticUnderstandingService(service=CannedLLM.for_all(PROFILE_PAYLOAD))
        resolver = IntentResolver(parser=RegexIntentParser(), understanding=service)
        response, engine = _run_chat("how's the o2 in arabian waters in 2024?", resolver)

        engine.execute.assert_called_once()
        executed = engine.execute.call_args[0][0]
        assert executed.intent == "profile_plot"
        assert executed.variables == ["DOXY"]
        assert executed.region == "arabian_sea"
        assert executed.year == 2024
        assert response.message == "engine answered"
        assert response.intent == "profile_plot"


class TestChatClarification:
    def test_ambiguity_produces_clarification_response_without_engine(self, enable_semantic):
        service = SemanticUnderstandingService(
            service=CannedLLM.for_all(CLARIFICATION_PAYLOAD)
        )
        resolver = IntentResolver(parser=RegexIntentParser(), understanding=service)
        response, engine = _run_chat("plot it", resolver)

        assert response.intent == "clarification"  # existing pseudo-intent, schema unchanged
        assert response.message == "Which variable would you like to see plotted?"
        assert response.figure is None
        assert response.map_data == []
        engine.execute.assert_not_called()


class TestChatFallback:
    def test_dead_llm_falls_back_to_regex_answer(self, enable_semantic):
        dead = SemanticUnderstandingService(
            service=CannedLLM.for_all(RuntimeError("provider unreachable"))
        )
        resolver = IntentResolver(parser=RegexIntentParser(), understanding=dead)
        response, engine = _run_chat("show oxygen in arabian sea for 2024", resolver)

        engine.execute.assert_called_once()
        executed = engine.execute.call_args[0][0]
        # Regex-parser result for the same query (fallback path = pre-Phase-2 behaviour)
        legacy = IntentResolver(parser=RegexIntentParser())
        assert executed.model_dump() == legacy.resolve(
            "show oxygen in arabian sea for 2024"
        ).model_dump()
        assert response.intent == "profile_plot"


class TestParaphraseToleranceThroughChat:
    def test_paraphrases_execute_identical_intents(self, enable_semantic):
        """Two surface-different questions understood the same way must execute
        the same ParsedIntent — the core 'LLM understands' promise."""
        payload = {
            "intent_name": "profile_plot",
            "confidence": 0.9,
            "variable_mentions": ["the salt content"],
            "region_mentions": ["the bay of bengal"],
            "temporal": {"year": 2023},
        }
        service = SemanticUnderstandingService(service=CannedLLM.for_all(payload))
        resolver = IntentResolver(parser=RegexIntentParser(), understanding=service)

        response_a, engine_a = _run_chat(
            "how salty is the bay of bengal been back in 2023?", resolver
        )
        response_b, engine_b = _run_chat(
            "salinity profiles in the bay of bengal, year 2023 please", resolver
        )
        assert engine_a.execute.call_args[0][0].model_dump() == (
            engine_b.execute.call_args[0][0].model_dump()
        )
        executed = engine_a.execute.call_args[0][0]
        assert executed.variables == ["PSAL"]
        assert executed.region == "bay_of_bengal"
        assert executed.year == 2023
        assert response_a.intent == response_b.intent == "profile_plot"
