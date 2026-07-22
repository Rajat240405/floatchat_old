"""Groq LLM service implementation (P2: provider toggle).

A drop-in alternative to :class:`OllamaLLMService` that talks to Groq's
OpenAI-compatible API (api.groq.com) over HTTP. Used to A/B-test the entity
extractor and query classifier against other providers with the SAME prompts,
JSON schema, and gating.

Design notes:
  - No OpenAI SDK dependency: raw ``chat/completions`` REST via httpx. Groq's
    API is byte-for-byte OpenAI-shaped, so the payload uses ``messages`` with
    ``role`` = system|user and ``response_format`` for JSON mode.
  - ``json_mode=True`` sends ``response_format={"type":"json_object"}`` — the
    OpenAI/Groq equivalent of Ollama's ``format: "json"``. The extractor prompt
    already instructs JSON output, so both code paths converge on the same wire
    format regardless of provider.
  - API key read from ``GROQ_API_KEY`` (or ``FLOATCHAT_GROQ_API_KEY``). If
    absent, construction raises :class:`FloatChatError` so the factory can fall
    back gracefully.
"""

import logging
import time

import httpx

from floatchat.config import settings
from floatchat.exceptions import FloatChatError
from floatchat.llm_service.base import AbstractLLMService
from floatchat.llm_service.ollama import _DEFAULT_SYSTEM

logger = logging.getLogger(__name__)

_GROQ_BASE_URL = "https://api.groq.com/openai/v1"


def _resolve_api_key(explicit: str | None) -> str:
    """Resolve the Groq API key (explicit arg → settings → env)."""
    import os

    if explicit:
        return explicit
    if settings.groq_api_key:
        return settings.groq_api_key
    return os.environ.get("GROQ_API_KEY", "")


class GroqLLMService(AbstractLLMService):
    """LLM service backed by the Groq (OpenAI-compatible) API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        *,
        timeout: float = 60.0,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> None:
        key = _resolve_api_key(api_key)
        if not key:
            raise FloatChatError(
                "Groq provider selected but no API key found. "
                "Set GROQ_API_KEY (or FLOATCHAT_GROQ_API_KEY).",
                details={"model": model or settings.groq_model},
            )
        self._api_key = key
        self.model = model or settings.groq_model
        self.timeout = timeout
        self.temperature = temperature
        self.top_p = top_p
        self.max_tokens = max_tokens
        self.json_mode = json_mode
        self._client = httpx.Client(timeout=timeout)

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        """Send *prompt* to Groq (OpenAI chat/completions) and return the text."""
        url = f"{_GROQ_BASE_URL}/chat/completions"
        sys_text = system or _DEFAULT_SYSTEM

        body: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": sys_text},
                {"role": "user", "content": prompt},
            ],
        }
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if self.top_p is not None:
            body["top_p"] = self.top_p
        if self.max_tokens is not None:
            body["max_tokens"] = self.max_tokens
        if self.json_mode:
            # OpenAI/Groq JSON mode — equivalent to Ollama format:"json".
            body["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        logger.debug(
            "Groq generate: model=%s prompt_len=%d json_mode=%s",
            self.model, len(prompt), self.json_mode,
        )

        t0 = time.perf_counter()
        try:
            response = self._client.post(url, json=body, headers=headers)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Groq returned %s: %s",
                exc.response.status_code, exc.response.text[:500],
            )
            raise FloatChatError(
                f"Groq returned HTTP {exc.response.status_code}",
                details={"model": self.model, "body": exc.response.text[:500]},
            ) from exc
        except httpx.RequestError as exc:
            logger.error("Groq connection failed: %s", exc)
            raise FloatChatError(
                "Cannot connect to Groq API.",
                details={"url": url, "model": self.model},
            ) from exc
        finally:
            logger.info(
                "Groq generation duration_seconds=%.3f model=%s",
                time.perf_counter() - t0, self.model,
            )

        try:
            data = response.json()
            text = data["choices"][0]["message"]["content"].strip()
        except Exception as exc:  # noqa: BLE001 — surface a clean domain error
            raise FloatChatError(
                "Groq returned unparseable response",
                details={"raw": str(data)[:500]},
            ) from exc

        logger.info(
            "Groq response: model=%s response_len=%d", self.model, len(text)
        )
        return text
