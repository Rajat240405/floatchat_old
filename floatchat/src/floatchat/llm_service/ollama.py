"""Ollama LLM service implementation.

Communicates with a local Ollama instance via its HTTP API.
"""

import logging
import time

import httpx

from floatchat.config import settings
from floatchat.exceptions import FloatChatError
from floatchat.llm_service.base import AbstractLLMService

logger = logging.getLogger(__name__)

_DEFAULT_SYSTEM = (
    "You are FloatChat, an AI assistant specialized in oceanography and the "
    "Argo biogeochemical float program. Provide concise, accurate answers."
)


class OllamaLLMService(AbstractLLMService):
    """LLM service backed by a local Ollama server."""

    def __init__(
        self,
        base_url: str = settings.ollama_base_url,
        model: str = settings.ollama_model,
        timeout: float = settings.ollama_timeout,
        *,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        thinking: bool | None = None,
        json_mode: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.temperature = temperature
        self.top_p = top_p
        self.max_tokens = max_tokens
        self.thinking = thinking
        self.json_mode = json_mode
        self._client = httpx.Client(timeout=timeout)

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        """Send *prompt* to Ollama and return the generated text."""
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system or _DEFAULT_SYSTEM,
            "stream": False,
        }
        options = {}
        if self.temperature is not None:
            options["temperature"] = self.temperature
        if self.top_p is not None:
            options["top_p"] = self.top_p
        if self.max_tokens is not None:
            options["num_predict"] = self.max_tokens
        if options:
            payload["options"] = options
        if self.thinking is not None:
            payload["think"] = self.thinking
        if self.json_mode:
            payload["format"] = "json"

        logger.debug(
            "Ollama generate: model=%s prompt_len=%d", self.model, len(prompt)
        )

        generation_t0 = time.perf_counter()
        try:
            response = self._client.post(url, json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Ollama returned %s: %s", exc.response.status_code, exc.response.text
            )
            raise FloatChatError(
                f"Ollama returned HTTP {exc.response.status_code}",
                details={"model": self.model},
            ) from exc
        except httpx.RequestError as exc:
            logger.error("Ollama connection failed: %s", exc)
            raise FloatChatError(
                "Cannot connect to Ollama. Is it running?",
                details={"url": url, "model": self.model},
            ) from exc
        finally:
            logger.info(
                "Ollama generation duration_seconds=%.3f model=%s",
                time.perf_counter() - generation_t0,
                self.model,
            )

        try:
            data = response.json()
            text = data.get("response", "").strip()
        except Exception as exc:
            raise FloatChatError(
                "Ollama returned unparseable JSON",
                details={"raw": response.text[:500]},
            ) from exc

        logger.info(
            "Ollama response: model=%s response_len=%d", self.model, len(text)
        )
        return text
