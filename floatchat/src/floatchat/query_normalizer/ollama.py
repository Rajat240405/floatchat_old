"""Ollama-backed Query Normalizer for Phase 20.2."""

import logging

from floatchat.llm_service.ollama import OllamaLLMService
from .base import AbstractQueryNormalizer

logger = logging.getLogger(__name__)


_NORMALIZATION_SYSTEM = (
    "You are a query normalizer for an oceanographic Argo data assistant. "
    "Your ONLY job is to correct spelling, normalize scientific terminology, "
    "Argo variable names, region names, and expand common abbreviations. "
    "Return ONLY the corrected query text. Do NOT answer the question, "
    "do NOT add explanations, do NOT change meaning. "
    "Examples:\n"
    "temparature → temperature\n"
    "chlorphyll → chlorophyll\n"
    "oxigen → oxygen\n"
    "arabain sea → Arabian Sea\n"
    "chl → chlorophyll\n"
    "temp → temperature\n"
    "dox → dissolved oxygen\n"
)


class OllamaQueryNormalizer(AbstractQueryNormalizer):
    """Query normalizer powered by Ollama LLM."""

    def __init__(self, model: str | None = None):
        self.llm = OllamaLLMService()
        if model:
            self.llm.model = model

    def normalize(self, query: str) -> str:
        """Normalize the query using the LLM."""
        if not query or not query.strip():
            return query

        prompt = f"Normalize this query: {query}"

        try:
            normalized = self.llm.generate(prompt, system=_NORMALIZATION_SYSTEM)
            normalized = normalized.strip().strip('"').strip("'")
            if normalized and len(normalized) < len(query) * 3:  # sanity check
                logger.info("Query normalized: %r → %r", query, normalized)
                return normalized
        except Exception as exc:
            logger.warning("LLM normalization failed, falling back: %s", exc)

        return query  # return original on failure