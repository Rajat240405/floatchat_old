"""Tests for FastAPI routes — Phase 6 Traffic Cop."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from floatchat.api.dependencies import (
    get_conversation_manager,
    get_intent_parser,
    get_knowledge_base,
    get_llm_service,
    get_metadata_service,
    get_netcdf_reader,
    get_query_classifier,
    get_query_engine,
    get_repository_service,
    get_visualization_engine,
)
from floatchat.api.main import create_app
from floatchat.conversation.memory import InMemoryConversationManager
from floatchat.intent_parser.regex import RegexIntentParser
from floatchat.llm_service.classifier import QueryClassifier
from floatchat.llm_service.ollama import OllamaLLMService


@pytest.fixture
def client():
    app = create_app()

    # Override dependencies with lightweight mocks/stubs
    app.dependency_overrides[get_intent_parser] = lambda: RegexIntentParser()

    # LLM service + classifier — mock to avoid Ollama dependency in tests
    llm_mock = MagicMock(spec=OllamaLLMService)
    llm_mock.generate = MagicMock(return_value="Mock LLM answer")
    app.dependency_overrides[get_llm_service] = lambda: llm_mock

    classifier_mock = MagicMock(spec=QueryClassifier)
    classifier_mock.classify = MagicMock(return_value="DATA_QUERY")
    app.dependency_overrides[get_query_classifier] = lambda: classifier_mock

    metadata = MagicMock()
    metadata.is_loaded = MagicMock(return_value=True)
    metadata.search = MagicMock(return_value=[])
    app.dependency_overrides[get_metadata_service] = lambda: metadata

    repo = MagicMock()
    app.dependency_overrides[get_repository_service] = lambda: repo

    reader = MagicMock()
    app.dependency_overrides[get_netcdf_reader] = lambda: reader

    viz = MagicMock()
    viz.render = MagicMock(return_value={"data": [], "layout": {}})
    app.dependency_overrides[get_visualization_engine] = lambda: viz

    # Knowledge base mock — use real KB for knowledge query tests, but mockable
    from floatchat.llm_service.knowledge_base import KnowledgeBase
    kb = KnowledgeBase()
    app.dependency_overrides[get_knowledge_base] = lambda: kb

    # QueryEngine needs the real orchestrator but with mocked sub-services
    from floatchat.query_engine.engine import QueryEngine

    engine = QueryEngine(metadata, repo, reader, viz)
    app.dependency_overrides[get_query_engine] = lambda: engine

    # Conversation manager — single instance per test so session context persists
    _conversation_manager = InMemoryConversationManager()
    app.dependency_overrides[get_conversation_manager] = lambda: _conversation_manager

    return TestClient(app)


class TestChatEndpoint:
    def test_chat_known_message(self, client) -> None:
        response = client.post(
            "/api/v1/chat",
            json={"message": "show oxygen profile in arabian sea for 2024"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "profile_plot"
        # Priority 1A: Data queries now go through the local data lake.
        # The response should NOT indicate a remote GDAC fetch was performed
        # (i.e., the message should not say "GDAC HTTP fetch" as a log event).
        # The phrase "no GDAC HTTP" in the lake success message is fine —
        # it's an informational label, not a log of an actual HTTP call.

    def test_chat_unknown_mock_message(self, client) -> None:
        """Unknown queries without context return a helpful suggestion message."""
        response = client.post(
            "/api/v1/chat",
            json={"message": "totally unknown query"},
        )
        # Conversational recovery returns a suggestion instead of hard 400
        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "unknown"
        assert "couldn't fully understand" in data["message"].lower()

    def test_chat_unknown_with_context_returns_suggestions(self, client) -> None:
        """Priority 2: Unknown queries WITHOUT reference phrases return suggestions,
        even when context exists. Context inheritance requires explicit reference phrases."""
        session_id = "test-session-unknown"

        # Seed context
        client.post(
            "/api/v1/chat",
            json={"message": "show oxygen in arabian sea", "session_id": session_id},
        )

        # "blargle flargle" has NO reference phrase → no recovery, returns unknown
        response = client.post(
            "/api/v1/chat",
            json={"message": "blargle flargle", "session_id": session_id},
        )
        assert response.status_code == 200
        data = response.json()
        # Priority 2: No reference phrase → no context inheritance → unknown
        assert data["intent"] == "unknown"

    def test_chat_followup_with_reference_phrase_recovers(self, client) -> None:
        """Priority 2: Unknown queries WITH reference phrases use context."""
        session_id = "test-session-recovery"

        # Seed context
        client.post(
            "/api/v1/chat",
            json={"message": "show oxygen in arabian sea", "session_id": session_id},
        )

        # "same for Bay of Bengal" has reference phrase "same" → recovery works
        response = client.post(
            "/api/v1/chat",
            json={"message": "same for Bay of Bengal", "session_id": session_id},
        )
        assert response.status_code == 200
        data = response.json()
        # Recovery succeeds using context + reference phrase
        assert data["intent"] in ("profile_plot", "region_search")

    def test_chat_unknown_no_context_returns_suggestions(self, client) -> None:
        """Unknown queries without any context return a suggestion message."""
        response = client.post(
            "/api/v1/chat",
            json={"message": "blargle flargle", "session_id": "fresh-session"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "unknown"
        assert "couldn't fully understand" in data["message"].lower()
        assert "oxygen" in data["message"].lower()

    def test_nearest_float_route(self, client) -> None:
        response = client.post(
            "/api/v1/chat",
            json={"message": "nearest float to 15.5, 72.3"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "nearest_float"

    def test_radius_search_route(self, client) -> None:
        response = client.post(
            "/api/v1/chat",
            json={"message": "within 100km of 15.5, 72.3"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "radius_search"

    def test_metadata_lookup_route(self, client) -> None:
        response = client.post(
            "/api/v1/chat",
            json={"message": "sensors on float 6903091"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "metadata_lookup"

    def test_count_aggregate_route(self, client) -> None:
        response = client.post(
            "/api/v1/chat",
            json={"message": "how many profiles in Bay of Bengal for 2023"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "count_aggregate"

    def test_health_endpoint(self, client) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_unhandled_exception_returns_structured_json(self, client, monkeypatch) -> None:
        """Phase 8: unhandled exceptions return graceful ChatResponse, not HTTP 500."""
        from floatchat.intent_parser.regex import RegexIntentParser

        def _boom_parse(self, message):
            raise RuntimeError("something exploded internally")

        monkeypatch.setattr(RegexIntentParser, "parse", _boom_parse)

        response = client.post(
            "/api/v1/chat",
            json={"message": "trigger error"},
        )
        assert response.status_code == 200  # Phase 8: graceful error as ChatResponse
        data = response.json()
        assert data["intent"] == "error"
        assert "unexpected error" in data["message"].lower()
        assert "exploded" not in data["message"].lower()

    def test_knowledge_query_returns_kb_response(self, client, monkeypatch) -> None:
        """KNOWLEDGE_QUERY uses KB."""
        from floatchat.llm_service.classifier import QueryClassifier

        monkeypatch.setattr(QueryClassifier, "classify", lambda self, msg: "KNOWLEDGE_QUERY")

        response = client.post(
            "/api/v1/chat",
            json={"message": "What is a BGC float?"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "knowledge_base"
        assert data["figure"] is None
        assert data["map_data"] == []

    def test_small_talk_returns_hardcoded(self, client, monkeypatch) -> None:
        """SMALL_TALK returns hardcoded greeting without LLM."""
        from floatchat.llm_service.classifier import QueryClassifier

        monkeypatch.setattr(QueryClassifier, "classify", lambda self, msg: "SMALL_TALK")

        response = client.post(
            "/api/v1/chat",
            json={"message": "Hello"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "small_talk"
        assert "FloatChat" in data["message"]

    def test_out_of_domain_returns_bouncer(self, client, monkeypatch) -> None:
        """OUT_OF_DOMAIN returns polite bouncer."""
        from floatchat.llm_service.classifier import QueryClassifier

        monkeypatch.setattr(QueryClassifier, "classify", lambda self, msg: "OUT_OF_DOMAIN")

        response = client.post(
            "/api/v1/chat",
            json={"message": "Who won the world cup?"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "out_of_domain"
        assert "INCOIS" in data["message"]

    def test_follow_up_reuses_context(self, client) -> None:
        """Priority 2: A follow-up with a reference phrase inherits previous context."""
        session_id = "test-session-123"

        # First query: oxygen in Arabian Sea
        response1 = client.post(
            "/api/v1/chat",
            json={"message": "show oxygen in arabian sea", "session_id": session_id},
        )
        assert response1.status_code == 200
        data1 = response1.json()
        assert data1["intent"] == "profile_plot"

        # Second query: mentions chlorophyll with reference phrase "same region"
        # → should inherit Arabian Sea from context
        response2 = client.post(
            "/api/v1/chat",
            json={"message": "show chlorophyll in the same region", "session_id": session_id},
        )
        assert response2.status_code == 200
        data2 = response2.json()
        # The merged intent should have both CHLA and the inherited region,
        # so it routes through the data pipeline (not general_chat).
        assert data2["intent"] == "profile_plot"

    def test_follow_up_with_explicit_override(self, client) -> None:
        """Explicit values in a follow-up override inherited context."""
        session_id = "test-session-456"

        # First query: oxygen in Arabian Sea
        response1 = client.post(
            "/api/v1/chat",
            json={"message": "show oxygen in arabian sea", "session_id": session_id},
        )
        assert response1.status_code == 200

        # Second query: explicitly different region
        response2 = client.post(
            "/api/v1/chat",
            json={
                "message": "show chlorophyll in bay of bengal",
                "session_id": session_id,
            },
        )
        assert response2.status_code == 200
        data2 = response2.json()
        assert data2["intent"] == "profile_plot"

    def test_scientific_followup_overrides_classifier_result(self, monkeypatch) -> None:
        """Deictic follow-ups during an active scientific conversation stay on
        the data path even when the classifier reports KNOWLEDGE_QUERY.

        History: this replaced the obsolete ``test_general_query_uses_context_hint``
        (Cleanup M1), which asserted the legacy direct-LLM GENERAL_QUERY branch.
        In Cleanup M2 the GENERAL_QUERY alias and that branch were removed
        entirely; the scenario remains worth guarding because a KNOWLEDGE_QUERY
        classification for "Explain this graph" is perfectly reachable from the
        live classifier — and the state-based override must still win:

        1. ``_is_active_scientific_followup`` (definition keyword + deictic
           reference over a live profile context) forces ``DATA_QUERY``.
        2. Canonical resolution then declines gracefully (intent="unknown")
           with a context-aware suggestion message — no direct LLM answer.

        Assertions cover both: the override wins, and the LLM is never called.
        """
        session_id = "test-session-789"
        llm_calls: list[str] = []

        # Capture LLM prompts — the current architecture must NOT call the
        # LLM at any point during this conversation.
        from floatchat.api.dependencies import get_llm_service

        def _capture_llm():
            mock = MagicMock(spec=OllamaLLMService)

            def _generate(prompt, *, system=None):
                llm_calls.append(prompt)
                return "Mock explanation"

            mock.generate = _generate
            return mock

        app = create_app()
        app.dependency_overrides[get_llm_service] = _capture_llm
        _conversation_manager = InMemoryConversationManager()
        app.dependency_overrides[get_conversation_manager] = lambda: _conversation_manager
        app.dependency_overrides[get_metadata_service] = lambda: MagicMock(
            is_loaded=MagicMock(return_value=True),
            search=MagicMock(return_value=[]),
        )
        from floatchat.llm_service.knowledge_base import KnowledgeBase

        app.dependency_overrides[get_knowledge_base] = lambda: KnowledgeBase()

        # Turn 1 is a data query; turn 2 forces a KNOWLEDGE_QUERY
        # classification to prove the state-based routing override wins even
        # over the live knowledge bucket.
        _classify_calls: list[str] = []

        def _fake_classify(self, message: str) -> str:
            _classify_calls.append(message)
            return "DATA_QUERY" if len(_classify_calls) == 1 else "KNOWLEDGE_QUERY"

        monkeypatch.setattr(QueryClassifier, "classify", _fake_classify)

        test_client = TestClient(app)
        response1 = test_client.post(
            "/api/v1/chat",
            json={"message": "show oxygen in arabian sea", "session_id": session_id},
        )
        assert response1.status_code == 200
        assert response1.json()["intent"] == "profile_plot"

        response2 = test_client.post(
            "/api/v1/chat",
            json={"message": "Explain this graph", "session_id": session_id},
        )
        assert response2.status_code == 200
        # Behavior: definition word ("explain") + deictic reference ("this")
        # over an active profile context takes precedence over the classifier
        # result (DATA_QUERY override), so the follow-up stays on the data
        # pipeline rather than being answered directly. Canonical intent
        # resolution cannot bind "Explain this graph" to a query, so the route
        # replies with the graceful "unknown" response whose suggestion
        # message is built from the turn-1 scientific context.
        data2 = response2.json()
        assert data2["intent"] == "unknown"
        assert "You were previously looking at" in data2["message"]
        assert "DOXY" in data2["message"]
        assert "Arabian Sea" in data2["message"]

        # No direct-LLM answer path fired (the legacy branch no longer exists).
        assert llm_calls == []
