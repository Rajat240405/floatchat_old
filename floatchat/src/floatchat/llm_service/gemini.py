"""Gemini LLM service implementation (P2: provider toggle).

A drop-in alternative to :class:`OllamaLLMService` that talks to the Google
Generative Language API (Gemini) over plain HTTP. Used to A/B-test the entity
extractor and query classifier against the local Ollama model with the SAME
prompts, JSON schema, and gating — to diagnose model hallucination vs code
design.

Design notes:
  - No Google SDK dependency: raw ``generateContent`` REST via httpx, mirroring
    how :class:`OllamaLLMService` calls Ollama. Keeps the comparison apples-to-
    apples and the dependency footprint minimal.
  - ``json_mode=True`` sets ``responseMimeType: application/json`` so the entity
    extractor receives validated JSON (equivalent to Ollama's ``format: json``).
  - The API key is read from ``GEMINI_API_KEY`` (or ``FLOATCHAT_GEMINI_API_KEY``)
    via :mod:`floatchat.config`. If absent, construction raises
    :class:`FloatChatError` so the factory can fall back gracefully.
"""

import logging
import time

import httpx

from floatchat.config import settings
from floatchat.exceptions import FloatChatError
from floatchat.llm_service.base import AbstractLLMService
from floatchat.llm_service.ollama import _DEFAULT_SYSTEM

logger = logging.getLogger(__name__)

_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


def _resolve_api_key(explicit: str | None) -> str:
    """Resolve the Gemini API key from the explicit arg, settings, or env.

    Priority: explicit constructor arg > settings.gemini_api_key (which itself
    honours GEMINI_API_KEY / FLOATCHAT_GEMINI_API_KEY).
    """
    import os

    if explicit:
        return explicit
    if settings.gemini_api_key:
        return settings.gemini_api_key
    return os.environ.get("GEMINI_API_KEY", "")


class GeminiLLMService(AbstractLLMService):
    """LLM service backed by the Google Gemini API."""

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
                "Gemini provider selected but no API key found. "
                "Set GEMINI_API_KEY (or FLOATCHAT_GEMINI_API_KEY).",
                details={"model": model or settings.gemini_model},
            )
        self._api_key = key
        self.model = model or settings.gemini_model
        self.timeout = timeout
        self.temperature = temperature
        self.top_p = top_p
        self.max_tokens = max_tokens
        self.json_mode = json_mode
        self._client = httpx.Client(timeout=timeout)

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        """Send *prompt* to Gemini and return the generated text."""
        url = f"{_GEMINI_BASE_URL}/models/{self.model}:generateContent"
        sys_text = system or _DEFAULT_SYSTEM

        body: dict = {
            "system_instruction": {"parts": [{"text": sys_text}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        }
        gen_config: dict = {}
        if self.temperature is not None:
            gen_config["temperature"] = self.temperature
        if self.top_p is not None:
            gen_config["topP"] = self.top_p
        if self.max_tokens is not None:
            gen_config["maxOutputTokens"] = self.max_tokens
        if self.json_mode:
            # Enforce JSON output — equivalent to Ollama's format:"json".
            gen_config["responseMimeType"] = "application/json"
        if gen_config:
            body["generationConfig"] = gen_config

        logger.debug(
            "Gemini generate: model=%s prompt_len=%d json_mode=%s",
            self.model, len(prompt), self.json_mode,
        )

        t0 = time.perf_counter()
        try:
            response = self._client.post(
                url, json=body, params={"key": self._api_key}
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Gemini returned %s: %s",
                exc.response.status_code, exc.response.text[:500],
            )
            raise FloatChatError(
                f"Gemini returned HTTP {exc.response.status_code}",
                details={"model": self.model, "body": exc.response.text[:500]},
            ) from exc
        except httpx.RequestError as exc:
            logger.error("Gemini connection failed: %s", exc)
            raise FloatChatError(
                "Cannot connect to Gemini API.",
                details={"url": url, "model": self.model},
            ) from exc
        finally:
            logger.info(
                "Gemini generation duration_seconds=%.3f model=%s",
                time.perf_counter() - t0, self.model,
            )

        try:
            data = response.json()
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts).strip()
        except Exception as exc:  # noqa: BLE001 — surface a clean domain error
            raise FloatChatError(
                "Gemini returned unparseable response",
                details={"raw": str(data)[:500]},
            ) from exc

        logger.info(
            "Gemini response: model=%s response_len=%d", self.model, len(text)
        )
        return text
