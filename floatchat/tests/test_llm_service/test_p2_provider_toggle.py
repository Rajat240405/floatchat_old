"""P2 provider toggle tests — GeminiLLMService + factory selection.

These verify the wiring that makes the A/B comparison possible, WITHOUT any
network (the Gemini HTTP call is mocked). They prove:
  - The factory selects the right provider based on settings.
  - GeminiLLMService builds the correct generateContent payload (system,
    contents, JSON responseMimeType) and parses the response.
  - Missing key degrades gracefully (raises a clean domain error / falls back).
"""
import json
from unittest.mock import MagicMock, patch

import pytest

from floatchat.exceptions import FloatChatError
from floatchat.llm_service.base import AbstractLLMService
from floatchat.llm_service.factory import build_llm_service


# --------------------------------------------------------------------------- #
# Factory selection
# --------------------------------------------------------------------------- #
def test_factory_defaults_to_ollama():
    from floatchat.llm_service.ollama import OllamaLLMService
    with patch("floatchat.llm_service.factory.settings") as mock_s:
        mock_s.llm_provider = "ollama"
        mock_s.ollama_model = "qwen2.5:3b"
        mock_s.ollama_timeout = 10.0
        svc = build_llm_service(json_mode=True, model="qwen2.5:3b")
    assert isinstance(svc, OllamaLLMService)
    assert svc.json_mode is True
    assert svc.model == "qwen2.5:3b"


def test_factory_selects_gemini_when_key_present():
    """provider=gemini + GEMINI_API_KEY in env → GeminiLLMService (both modules
    read the shared settings singleton, so toggle via the real object + env)."""
    import os

    from floatchat.config import settings
    from floatchat.llm_service.gemini import GeminiLLMService
    with patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"}), \
         patch.object(settings, "llm_provider", "gemini"), \
         patch.object(settings, "gemini_model", "gemini-2.5-flash"):
        svc = build_llm_service(json_mode=True)
    assert isinstance(svc, GeminiLLMService)
    assert svc.model == "gemini-2.5-flash"
    assert svc.json_mode is True


def test_factory_falls_back_to_ollama_when_gemini_key_missing():
    """provider=gemini but no key → graceful fallback to Ollama, no crash."""
    from floatchat.llm_service.ollama import OllamaLLMService
    with patch("floatchat.llm_service.factory.settings") as mock_s:
        mock_s.llm_provider = "gemini"
        mock_s.gemini_model = "gemini-2.5-flash"
        mock_s.gemini_api_key = ""  # no key
        mock_s.ollama_model = "qwen2.5:3b"
        mock_s.ollama_timeout = 10.0
        svc = build_llm_service(json_mode=True, model="qwen2.5:3b")
    assert isinstance(svc, OllamaLLMService), "must fall back to Ollama when key missing"


def test_factory_invalid_provider_defaults_to_ollama():
    from floatchat.llm_service.ollama import OllamaLLMService
    with patch("floatchat.llm_service.factory.settings") as mock_s:
        mock_s.llm_provider = "bogus"
        mock_s.ollama_model = "qwen2.5:7b"
        mock_s.ollama_timeout = 60.0
        svc = build_llm_service(json_mode=False)
    assert isinstance(svc, OllamaLLMService)


# --------------------------------------------------------------------------- #
# GeminiLLMService — payload shape + response parsing (no network)
# --------------------------------------------------------------------------- #
def test_gemini_construction_requires_key():
    import os

    from floatchat.config import settings
    from floatchat.llm_service.gemini import GeminiLLMService
    # No explicit key, settings empty, and no GEMINI_API_KEY in env.
    env_without_key = {k: v for k, v in os.environ.items() if k != "GEMINI_API_KEY"}
    with patch.dict(os.environ, env_without_key, clear=True), \
         patch.object(settings, "gemini_api_key", ""), \
         patch.object(settings, "gemini_model", "gemini-2.5-flash"), pytest.raises(FloatChatError):
        GeminiLLMService()


def test_gemini_generate_builds_correct_json_payload():
    from floatchat.llm_service.gemini import GeminiLLMService
    svc = GeminiLLMService(api_key="k", model="gemini-2.5-flash",
                           json_mode=True, temperature=0.1, max_tokens=256)

    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": '{"action":"x"}'}]}}]}

    def fake_post(url, json=None, params=None):
        captured["url"] = url
        captured["body"] = json
        captured["params"] = params
        return FakeResp()

    with patch.object(svc._client, "post", side_effect=fake_post):
        out = svc.generate("EXTRACT THIS", system="SYS")

    assert out == '{"action":"x"}'
    assert "generateContent" in captured["url"]
    assert "gemini-2.5-flash" in captured["url"]
    assert captured["params"]["key"] == "k"
    # system instruction present
    assert captured["body"]["system_instruction"]["parts"][0]["text"] == "SYS"
    # JSON response mode enforced (equivalent to Ollama format:"json")
    assert captured["body"]["generationConfig"]["responseMimeType"] == "application/json"
    assert captured["body"]["generationConfig"]["temperature"] == 0.1
    assert captured["body"]["generationConfig"]["maxOutputTokens"] == 256
    # user content present
    assert captured["body"]["contents"][0]["parts"][0]["text"] == "EXTRACT THIS"


def test_gemini_generate_plain_text_for_classifier():
    """json_mode=False must NOT set responseMimeType (classifier wants a label)."""
    from floatchat.llm_service.gemini import GeminiLLMService
    svc = GeminiLLMService(api_key="k", model="gemini-2.5-flash", json_mode=False)

    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "DATA_QUERY"}]}}]}

    def _fake_post(url, json=None, params=None):
        captured["body"] = json
        return FakeResp()

    with patch.object(svc._client, "post", side_effect=_fake_post):
        out = svc.generate("classify this", system="CLS")

    assert out == "DATA_QUERY"
    gc = captured["body"].get("generationConfig", {})
    assert "responseMimeType" not in gc, "classifier path must not force JSON mode"


def test_gemini_raises_domain_error_on_http_failure():
    import httpx

    from floatchat.llm_service.gemini import GeminiLLMService
    svc = GeminiLLMService(api_key="k", model="gemini-2.5-flash")

    class FakeResp:
        status_code = 429
        text = "rate limited"

        def raise_for_status(self):
            raise httpx.HTTPStatusError("429", request=MagicMock(), response=self)

    with patch.object(svc._client, "post", return_value=FakeResp()):
        with pytest.raises(FloatChatError):
            svc.generate("hi")


# --------------------------------------------------------------------------- #
# End-to-end: extractor builds the right provider service lazily
# --------------------------------------------------------------------------- #
def test_extractor_uses_injected_service():
    """LLMEntityExtractor(service=...) uses it and never builds another."""
    from floatchat.entity_extractor.extractor import LLMEntityExtractor
    mock_svc = MagicMock(spec=AbstractLLMService)
    mock_svc.generate.return_value = json.dumps({
        "action": "region_search", "variables": ["DOXY"],
        "spatial_filter": "arabian_sea", "confidence": 0.9,
    })
    extractor = LLMEntityExtractor(service=mock_svc)
    spec = extractor.extract("oxygen in Arabian Sea")
    assert spec is not None
    assert spec.variables == ["DOXY"]
    mock_svc.generate.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# --------------------------------------------------------------------------- #
# Groq provider (OpenAI-compatible API)
# --------------------------------------------------------------------------- #
def test_factory_selects_groq_when_key_present():
    """provider=groq + GROQ_API_KEY → GroqLLMService."""
    import os

    from floatchat.config import settings
    from floatchat.llm_service.groq import GroqLLMService
    with patch.dict(os.environ, {"GROQ_API_KEY": "fake-key"}), \
         patch.object(settings, "llm_provider", "groq"), \
         patch.object(settings, "groq_model", "openai/gpt-oss-120b"):
        svc = build_llm_service(json_mode=True)
    assert isinstance(svc, GroqLLMService)
    assert svc.model == "openai/gpt-oss-120b"
    assert svc.json_mode is True


def test_factory_falls_back_to_ollama_when_groq_key_missing():
    """provider=groq but no key → graceful fallback to Ollama, no crash."""
    from floatchat.llm_service.ollama import OllamaLLMService
    with patch("floatchat.llm_service.factory.settings") as mock_s:
        mock_s.llm_provider = "groq"
        mock_s.groq_model = "openai/gpt-oss-120b"
        mock_s.groq_api_key = ""
        mock_s.ollama_model = "qwen2.5:3b"
        mock_s.ollama_timeout = 10.0
        svc = build_llm_service(json_mode=True, model="qwen2.5:3b")
    assert isinstance(svc, OllamaLLMService)


def test_groq_construction_requires_key():
    import os

    from floatchat.config import settings
    from floatchat.llm_service.groq import GroqLLMService
    env_without_key = {k: v for k, v in os.environ.items() if k != "GROQ_API_KEY"}
    with patch.dict(os.environ, env_without_key, clear=True), \
         patch.object(settings, "groq_api_key", ""), \
         patch.object(settings, "groq_model", "openai/gpt-oss-120b"), pytest.raises(FloatChatError):
        GroqLLMService()


def test_groq_generate_builds_openai_payload():
    """Groq payload is OpenAI-shaped: messages[], response_format for JSON."""
    from floatchat.llm_service.groq import GroqLLMService
    svc = GroqLLMService(api_key="k", model="openai/gpt-oss-120b",
                         json_mode=True, temperature=0.1, max_tokens=256)
    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": '{"action":"x"}'}}]}

    def fake_post(url, json=None, headers=None):
        captured["url"] = url
        captured["body"] = json
        captured["headers"] = headers
        return FakeResp()

    with patch.object(svc._client, "post", side_effect=fake_post):
        out = svc.generate("EXTRACT THIS", system="SYS")

    assert out == '{"action":"x"}'
    assert "chat/completions" in captured["url"]
    assert captured["headers"]["Authorization"] == "Bearer k"
    # OpenAI chat messages: system + user
    roles = [m["role"] for m in captured["body"]["messages"]]
    assert roles == ["system", "user"]
    assert captured["body"]["messages"][1]["content"] == "EXTRACT THIS"
    # JSON response mode (OpenAI/Groq shape)
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert captured["body"]["model"] == "openai/gpt-oss-120b"
    assert captured["body"]["temperature"] == 0.1
    assert captured["body"]["max_tokens"] == 256


def test_groq_plain_text_for_classifier():
    """json_mode=False must NOT set response_format (classifier wants a label)."""
    from floatchat.llm_service.groq import GroqLLMService
    svc = GroqLLMService(api_key="k", model="openai/gpt-oss-120b", json_mode=False)
    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "DATA_QUERY"}}]}

    def _fake_post(url, json=None, headers=None):
        captured["body"] = json
        return FakeResp()

    with patch.object(svc._client, "post", side_effect=_fake_post):
        out = svc.generate("classify", system="CLS")
    assert out == "DATA_QUERY"
    assert "response_format" not in captured["body"]


def test_groq_raises_domain_error_on_http_failure():
    import httpx

    from floatchat.llm_service.groq import GroqLLMService
    svc = GroqLLMService(api_key="k", model="openai/gpt-oss-120b")

    class FakeResp:
        status_code = 429
        text = "rate limited"

        def raise_for_status(self):
            raise httpx.HTTPStatusError("429", request=MagicMock(), response=self)

    with patch.object(svc._client, "post", return_value=FakeResp()):
        with pytest.raises(FloatChatError):
            svc.generate("hi")
