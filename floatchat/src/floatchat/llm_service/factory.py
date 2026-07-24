"""LLM provider factory (P2: provider toggle).

Single entry point for building an :class:`AbstractLLMService` based on
``settings.llm_provider`` (``ollama`` | ``gemini``). Both the entity extractor
and the query classifier route through here so flipping
``FLOATCHAT_LLM_PROVIDER`` swaps BOTH call sites at once — the A/B switch for
diagnosing model hallucination vs code design.

Defaults remain offline (Ollama). Gemini is only selected when explicitly
requested AND an API key is present; otherwise we fall back to Ollama with a
warning so the app never hard-fails on a missing key.
"""

import logging

from floatchat.config import settings
from floatchat.llm_service.base import AbstractLLMService

logger = logging.getLogger(__name__)


def build_llm_service(
    *,
    json_mode: bool = False,
    model: str | None = None,
    timeout: float | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    top_p: float | None = None,
    provider: str | None = None,
) -> AbstractLLMService:
    """Construct an LLM service for the configured provider.

    Args:
        json_mode: If True, request strict JSON output (extractor path).
        model: Ollama model override (ignored when provider=gemini, which uses
            ``settings.gemini_model``).
        timeout, temperature, max_tokens, top_p: Generation options passed
            through to the chosen provider.
        provider: Override ``settings.llm_provider`` (``ollama`` | ``gemini``).

    Returns:
        An :class:`AbstractLLMService` for the requested provider. Falls back
        to Ollama if Gemini is requested without an API key.
    """
    chosen = (provider or settings.llm_provider or "ollama").strip().lower()

    if chosen == "gemini":
        from floatchat.llm_service.gemini import GeminiLLMService

        # Gemini uses its own model setting; ignore the Ollama-specific model arg.
        try:
            return GeminiLLMService(
                model=settings.gemini_model,
                timeout=timeout if timeout is not None else 60.0,
                temperature=temperature,
                top_p=top_p,
                max_tokens=max_tokens,
                json_mode=json_mode,
            )
        except Exception as exc:  # noqa: BLE001 — degrade to Ollama on missing key
            logger.warning(
                "Gemini provider unavailable (%s); falling back to Ollama. "
                "Set GEMINI_API_KEY to use Gemini.",
                exc,
            )

    elif chosen == "groq":
        from floatchat.llm_service.groq import GroqLLMService

        # Groq uses its own model setting (e.g. openai/gpt-oss-120b); ignore the
        # Ollama-specific model arg.
        try:
            return GroqLLMService(
                model=settings.groq_model,
                timeout=timeout if timeout is not None else 30.0,
                temperature=temperature,
                top_p=top_p,
                max_tokens=max_tokens,
                json_mode=json_mode,
            )
        except Exception as exc:  # noqa: BLE001 — degrade to Ollama on missing key
            logger.warning(
                "Groq provider unavailable (%s); falling back to Ollama. "
                "Set GROQ_API_KEY to use Groq.",
                exc,
            )

    # Default / fallback: Ollama.
    from floatchat.llm_service.ollama import OllamaLLMService

    return OllamaLLMService(
        base_url=settings.ollama_base_url,
        model=model or settings.ollama_model,
        timeout=timeout if timeout is not None else settings.ollama_timeout,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        json_mode=json_mode,
    )


def build_compiler_llm_service() -> AbstractLLMService:
    """Build the LLM service used by the intent compiler (resolver fallback).

    IntentResolver's LLMIntentCompiler is the only caller (Cleanup M2: the
    legacy entity extractor was removed). Uses extraction-specific tuning
    (JSON mode, low temperature, short output) for whichever provider is
    configured.
    """
    return build_llm_service(
        json_mode=True,
        model=settings.extractor_model,
        timeout=settings.extractor_timeout,
        temperature=settings.extractor_temperature,
        max_tokens=256,
    )
