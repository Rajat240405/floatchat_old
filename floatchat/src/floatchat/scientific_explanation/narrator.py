"""Provider-agnostic scientific narrator.

This module is intentionally limited to narration orchestration. It delegates
model communication through :class:`AbstractLLMService` and does not build
prompts, parse output, verify scientific grounding, or select fallbacks; those
responsibilities belong to later pipeline phases.
"""

from __future__ import annotations

import logging

from floatchat.config import settings
from floatchat.exceptions import ScientificNarratorError
from floatchat.llm_service.base import AbstractLLMService

logger = logging.getLogger(__name__)


class ScientificNarrator:
    """Generate raw scientific narration through an abstract LLM provider.

    The caller supplies an already-built prompt. The injected LLM service owns
    all provider-specific behavior such as model selection, HTTP transport,
    timeouts, and generation parameters. This class only validates the request,
    applies provider-independent retry policy, and returns raw text for the
    future parser stage.
    """

    def __init__(
        self,
        llm_service: AbstractLLMService,
        *,
        max_retries: int | None = None,
    ) -> None:
        self._llm = llm_service
        self.max_retries = (
            max_retries if max_retries is not None else settings.sci_narrator_max_retries
        )
        if self.max_retries < 0:
            raise ValueError("Scientific narrator max_retries must not be negative")

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        """Delegate narration to the injected LLM service and return raw text.

        Provider failures and empty responses are retried up to
        ``max_retries`` times. When all attempts fail, the provider exception is
        translated into :class:`ScientificNarratorError` without exposing the
        prompt content.
        """
        if not isinstance(prompt, str) or not prompt.strip():
            raise ScientificNarratorError("Scientific narrator prompt must not be empty.")

        total_attempts = self.max_retries + 1
        provider_name = self._llm.__class__.__name__
        last_error: Exception | None = None

        logger.info(
            "Scientific narrator request: provider=%s prompt_len=%d attempts=%d",
            provider_name,
            len(prompt),
            total_attempts,
        )

        for attempt in range(1, total_attempts + 1):
            try:
                text = self._llm.generate(prompt, system=system)
                if not isinstance(text, str) or not text.strip():
                    raise ValueError("LLM provider returned empty narration text")

                result = text.strip()
                logger.info(
                    "Scientific narrator response: provider=%s response_len=%d attempt=%d",
                    provider_name,
                    len(result),
                    attempt,
                )
                return result
            except Exception as exc:
                last_error = exc
                if attempt == total_attempts:
                    raise ScientificNarratorError(
                        "Scientific narrator request failed.",
                        details={
                            "provider": provider_name,
                            "attempts": attempt,
                            "exception": type(exc).__name__,
                        },
                    ) from exc
                logger.warning(
                    "Scientific narrator provider failure on attempt %d/%d; retrying: %s",
                    attempt,
                    total_attempts,
                    type(exc).__name__,
                )

        # Defensive only: the final failed attempt always raises above.
        raise ScientificNarratorError(
            "Scientific narrator failed unexpectedly.",
            details={
                "provider": provider_name,
                "attempts": total_attempts,
                "exception": type(last_error).__name__ if last_error else None,
            },
        )


__all__ = ["ScientificNarrator"]
