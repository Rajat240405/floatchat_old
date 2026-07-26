"""Bug Fix Sprint 1 (Bug 2) — deterministic "available plots" interception.

"What plots are available for float <id>?" is a capability question: the API
layer must answer with the deterministic variable listing (only variables
with data), render no figure, and never reach the query engine.
"""

from unittest.mock import MagicMock, patch

from floatchat.api.schemas import ChatRequest
from floatchat.api.services.chat_service import handle_chat
from floatchat.intent_parser.regex import RegexIntentParser
from floatchat.intent_resolution.resolver import IntentResolver
from floatchat.llm_service.classifier import QueryClassifier
from floatchat.models import ChatResponse

# Fixture-lake float whose DOXY column is entirely NULL (TEMP/PSAL/CHLA have data).
FIXTURE_FLOAT = "1901897"


def _make_handle_chat_args(message: str):
    conversation_manager = MagicMock()
    conversation_manager.get_context = MagicMock(return_value=None)
    resolver = IntentResolver(
        parser=RegexIntentParser(),
        compiler=None,
        # No session context in these tests: the resolver's context merge is
        # guarded on a real conversation manager, so pass None for hermeticity.
        conversation_manager=None,
    )
    query_engine = MagicMock()
    query_engine.execute = MagicMock(
        return_value=ChatResponse(
            intent="metadata_lookup",
            message="engine-called",
            data_summary={"matched_records": 0},
        )
    )
    return {
        "request": ChatRequest(message=message, session_id=None),
        "classifier": MagicMock(spec=QueryClassifier),
        "llm_service": MagicMock(),
        "intent_parser": resolver.parser,
        "intent_resolver": resolver,
        "query_engine": query_engine,
        "conversation_manager": conversation_manager,
        "knowledge_base": MagicMock(),
    }


class TestAvailablePlotsInterception:
    def test_capability_query_returns_available_plots(self) -> None:
        args = _make_handle_chat_args(f"What plots are available for float {FIXTURE_FLOAT}?")
        with patch.object(QueryClassifier, "classify", return_value="DATA_QUERY"):
            response = handle_chat(**args)

        assert response.intent == "available_plots"
        assert response.figure is None
        assert response.map_data == []
        # query engine must NOT execute a data pipeline for capability questions
        args["query_engine"].execute.assert_not_called()

        plots = response.data_summary.get("available_plots")
        assert plots, "expected non-empty available_plots listing"
        variables = [p["variable"] for p in plots]
        # fixture float has TEMP/PSAL/CHLA data but an all-NULL DOCY column
        assert "TEMP" in variables and "PSAL" in variables
        assert "DOXY" not in variables
        # every listed plot has at least one profile
        assert all(p["profiles"] > 0 for p in plots)
        assert FIXTURE_FLOAT in response.message
        args["conversation_manager"].update_context.assert_called_once()

    def test_metadata_query_without_capability_phrase_not_intercepted(self) -> None:
        args = _make_handle_chat_args(f"Tell me about float {FIXTURE_FLOAT}")
        with patch.object(QueryClassifier, "classify", return_value="DATA_QUERY"):
            response = handle_chat(**args)

        # plain metadata lookup flows through the normal engine path
        args["query_engine"].execute.assert_called_once()
        assert response.intent == "metadata_lookup"
        assert "available_plots" not in response.data_summary

    def test_profile_plot_query_not_intercepted(self) -> None:
        args = _make_handle_chat_args(f"Show temperature profile for float {FIXTURE_FLOAT}")
        with patch.object(QueryClassifier, "classify", return_value="DATA_QUERY"):
            response = handle_chat(**args)

        args["query_engine"].execute.assert_called_once()
        assert response.intent == "metadata_lookup"  # stubbed engine response
