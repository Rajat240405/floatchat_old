"""Shared fixtures/helpers for the Semantic Understanding Layer tests (Phase 2).

No test in this package ever performs a real LLM/network call: every service
is fed a stubbed AbstractLLMService double. The feature flag is pinned OFF at
repo-level conftest for the legacy suite; these tests opt in explicitly via
the ``enable_semantic`` fixture (monkeypatch auto-restores).
"""

from __future__ import annotations

import json

import pytest

from floatchat.config import settings


class CannedLLM:
    """Deterministic AbstractLLMService double.

    Built via :meth:`for_all` (one payload for every prompt) or
    :meth:`routed` (prompt-substring → payload). Payloads may be dicts
    (JSON-serialised on the way out), raw strings, or Exception instances
    (raised). Records every call for assertions.
    """

    def __init__(self) -> None:
        self._single = None
        self._routes: dict[str, object] | None = None
        self.calls: list[dict] = []

    @classmethod
    def for_all(cls, payload) -> "CannedLLM":
        service = cls()
        service._single = payload
        return service

    @classmethod
    def routed(cls, routes: dict[str, object]) -> "CannedLLM":
        service = cls()
        service._routes = dict(routes)
        return service

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        self.calls.append({"prompt": prompt, "system": system})
        payload = self._single
        if self._routes is not None:
            for needle, routed in self._routes.items():
                if needle in prompt:
                    payload = routed
                    break
            else:
                raise AssertionError(
                    f"CannedLLM: no route matched prompt: {prompt[:100]}"
                )
        if isinstance(payload, Exception):
            raise payload
        if isinstance(payload, str):
            return payload
        return json.dumps(payload)


class NullConversationManager:
    """Passthrough conversation manager (optional fixed context)."""

    def __init__(self, context=None):
        self._context = context
        self.merge_calls: list[dict] = []
        self.updated = None

    def get_context(self, session_id):
        return self._context

    def merge_context(self, session_id, intent, message=None, in_place=False):
        self.merge_calls.append(
            {"session_id": session_id, "intent": intent, "message": message}
        )
        return intent

    def update_context(self, session_id, intent, response):
        self.updated = {"session_id": session_id, "intent": intent, "response": response}

    def clear_context(self, session_id):
        self._context = None


@pytest.fixture
def enable_semantic(monkeypatch):
    """Enable the semantic layer for the duration of one test."""
    monkeypatch.setattr(settings, "semantic_understanding_enabled", True)
    monkeypatch.setattr(settings, "llm_enabled", True)
    monkeypatch.setattr(settings, "semantic_model", "test-model")
    return settings
