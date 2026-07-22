"""Priority 3: Structured LLM Entity Extractor.

Extracts structured entities from natural language queries using a small
model via Ollama or Gemini (P2: provider toggle). Returns a validated QuerySpec.

Rules:
  1. The deterministic regex parser runs FIRST. Only if slots are missing
     does this extractor get called.
  2. The LLM returns ONLY a validated JSON QuerySpec — never raw SQL,
     never free text.
  3. One call, tight timeout (default 10s). No retries by default.
  4. If confidence < threshold → return None (triggers clarification).
  5. If the provider is down or times out → return None (graceful degradation).

P2 hardening:
  - Structural-confidence override only fires when the extraction has
    GENUINELY meaningful content (variables, place/region, float, or a
    resolvable time filter). A lone ``operational_filter`` or a placeholder
    time_filter ("year", "time", ">=") is NOT meaningful → discarded even at
    high self-reported confidence. This stops the qwen2.5:0.5b behaviour of
    inventing ``operational_filter='active'`` for unrelated queries.
"""

import json
import logging
import time

from floatchat.config import settings
from floatchat.entity_extractor.query_spec import QuerySpec
from floatchat.exceptions import FloatChatError

logger = logging.getLogger(__name__)

_EXTRACTION_SYSTEM_PROMPT = """You are a TEMPORAL and ACTION resolver for an Argo ocean data chatbot. Your ONLY job is to resolve temporal expressions and identify the query action. Return a JSON object.

DO NOT generate SQL, explanations, or free text. Return ONLY the JSON object.

CRITICAL — FIELD RESTRICTIONS:
You may ONLY fill these fields:
  - action: the intent type (from the list below)
  - time_filter: temporal expressions ONLY (e.g., "2024", "last monsoon", "summer", "2023-06-01 to 2023-09-30")

You must NEVER fill these fields — ALWAYS set them to null or empty:
  - variables: ALWAYS [] (the regex parser handles variables)
  - spatial_filter: ALWAYS null (the gazetteer handles locations)
  - float_id: ALWAYS null (the regex parser handles float IDs)
  - depth_filter: ALWAYS null (the regex parser handles depth)
  - operational_filter: ALWAYS null (the regex parser handles "alive")

If you cannot determine the action or time_filter, set them to null.

Available actions: region_search, profile_plot, time_series, hovmoller, ts_diagram, comparison_plot, trajectory, nearest_float, radius_search, metadata_lookup, count_aggregate

Time filters: a year (e.g., "2024"), a season (e.g., "monsoon", "winter"), a relative season (e.g., "last monsoon"), or a date range (e.g., "2023-06-01 to 2023-09-30").

Return this exact JSON structure:
{
  "action": "<intent or null>",
  "variables": [],
  "spatial_filter": null,
  "time_filter": "<temporal expression or null>",
  "float_id": null,
  "depth_filter": null,
  "operational_filter": null,
  "confidence": 0.0-1.0
}

Rules:
- If the user asks about sensors/battery/manufacturer/status of a float, set action=metadata_lookup.
- NEVER use a generic placeholder like "year" or "time" for time_filter. Only return a concrete year, season, or date range. If unsure, use null.
- The deployment is India-only (Arabian Sea, Bay of Bengal, Indian Ocean)."""

_EXTRACTION_PROMPT_TEMPLATE = """Extract entities from this query:
"{query}"

Previous conversation context (for reference only):
- Last variables: {last_vars}
- Last region: {last_region}
- Last year: {last_year}
- Last float: {last_float}

Return ONLY the JSON object. No other text."""

# P2: time_filter values that carry no real temporal information. The small
# models emit these as placeholders; they must NOT count as "meaningful
# content" and must be ignored at the merge step.
_PLACEHOLDER_TIME_FILTERS = frozenset({
    "year", "time", "date", "period", "now", "recent", "current",
    "recently", "anytime", "sometime", "all", "overall",
    ">", "<", ">=", "<=", "=", ">=", "==",
})


def _is_placeholder_time_filter(time_filter: str | None) -> bool:
    """Return True if *time_filter* is a generic placeholder, not a real date.

    Also returns True for values the deterministic resolver cannot resolve
    (so we don't even log a noisy warning downstream).
    """
    if not time_filter:
        return True
    norm = time_filter.strip().lower()
    if norm in _PLACEHOLDER_TIME_FILTERS:
        return True
    # Bare comparison operators or single punctuation tokens
    if norm in {">", "<", ">=", "<=", "=", "==", "!=", "->", "=>"}:
        return True
    return False


class LLMEntityExtractor:
    """Extract structured entities from natural language using a local/cloud LLM.

    Gracefully degrades: if the provider is down or times out, returns None
    (no crash, no hang).
    """

    def __init__(self, service=None) -> None:
        # Allow injecting an AbstractLLMService (tests / DI). When None, the
        # provider service is built lazily on first use via the factory so that
        # constructing the extractor never performs network I/O.
        self._model = settings.extractor_model
        self._timeout = settings.extractor_timeout
        self._base_url = settings.ollama_base_url
        self._min_confidence = settings.extractor_min_confidence
        self._temperature = settings.extractor_temperature
        self._service = service
        self._service_unavailable = service is None and False  # set on failed build
        self._tried_build = service is not None

    def _ensure_service(self):
        """Lazily build the LLM provider service (Ollama or Gemini).

        Returns the service, or None if it could not be built (e.g. Gemini
        selected without an API key). Never raises.
        """
        if self._service is not None:
            return self._service
        if self._tried_build:
            return None
        self._tried_build = True
        try:
            from floatchat.llm_service.factory import build_extractor_llm_service

            self._service = build_extractor_llm_service()
            logger.debug("Extractor provider service built: %s", type(self._service).__name__)
        except Exception as exc:  # noqa: BLE001 — degrade to "no LLM"
            self._service_unavailable = True
            logger.warning(
                "Could not build extractor LLM service (%s); extraction disabled",
                exc,
            )
            return None
        return self._service

    def extract(
        self,
        message: str,
        context_vars: list[str] | None = None,
        context_region: str | None = None,
        context_year: int | None = None,
        context_float: str | None = None,
    ) -> QuerySpec | None:
        """Extract structured entities from *message*.

        Returns:
            A validated QuerySpec, or None if extraction failed or had no
            genuinely meaningful content.
        """
        if not self._model:
            logger.debug("Extractor model not configured — skipping LLM extraction")
            return None

        prompt = _EXTRACTION_PROMPT_TEMPLATE.format(
            query=message,
            last_vars=", ".join(context_vars) if context_vars else "none",
            last_region=context_region or "none",
            last_year=context_year or "none",
            last_float=context_float or "none",
        )

        t0 = time.perf_counter()
        try:
            raw_json = self._call_ollama(prompt)
        except Exception as exc:
            logger.warning(
                "LLM entity extraction failed: %s (%.2fs)",
                exc, time.perf_counter() - t0,
            )
            return None

        duration = time.perf_counter() - t0
        logger.info("LLM entity extraction: %.2fs, raw_len=%d", duration, len(raw_json))

        # Parse and validate
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            logger.warning("LLM returned invalid JSON: %s | raw: %s", exc, raw_json[:200])
            return None

        try:
            spec = QuerySpec(**data)
        except Exception as exc:
            logger.warning("LLM output failed QuerySpec validation: %s | data: %s", exc, data)
            return None

        # P2: Decide whether the extraction has GENUINELY meaningful content.
        # A lone operational_filter or a placeholder/unresolvable time_filter
        # is NOT meaningful and must not trigger a confidence override (and is
        # discarded even at high self-reported confidence).
        meaningful_time = bool(spec.time_filter) and not _is_placeholder_time_filter(
            spec.time_filter
        )
        has_meaningful_content = bool(
            spec.variables
            or spec.spatial_filter
            or spec.float_id
            or meaningful_time
        )

        if not has_meaningful_content:
            logger.info(
                "LLM extraction discarded — no meaningful slots "
                "(only operational_filter=%r / placeholder time=%r); "
                "treating as low-value and skipping merge",
                spec.operational_filter, spec.time_filter,
            )
            return None

        # Confidence gate — with structural confidence override.
        # Small models are unreliable at self-assessing confidence and often
        # return confidence=0.0 even when extraction is correct. Since we have
        # already verified meaningful content above, we override low
        # self-reported confidence up to the threshold.
        if spec.confidence < self._min_confidence:
            logger.info(
                "LLM extraction confidence %.2f < threshold %.2f BUT extraction has "
                "meaningful content (vars=%s time=%s spatial=%s float=%s) — "
                "applying structural confidence override",
                spec.confidence, self._min_confidence,
                spec.variables, spec.time_filter,
                spec.spatial_filter, spec.float_id,
            )
            spec = spec.model_copy(update={"confidence": self._min_confidence})

        logger.info(
            "LLM extraction succeeded: action=%s vars=%s spatial=%s time=%s float=%s conf=%.2f",
            spec.action, spec.variables, spec.spatial_filter,
            spec.time_filter, spec.float_id, spec.confidence,
        )
        return spec

    def _call_ollama(self, prompt: str) -> str:
        """Call the configured LLM provider with JSON mode and return its text.

        Name kept for backward compatibility with existing tests (which patch
        this method). Delegates to the injected/lazily-built provider service
        (Ollama or Gemini), so the same prompt/schema flow through either
        provider for a fair A/B comparison.
        """
        service = self._ensure_service()
        if service is None:
            raise FloatChatError("No LLM provider service available for extraction")
        return service.generate(prompt, system=_EXTRACTION_SYSTEM_PROMPT)


def build_clarification_message(spec: QuerySpec | None, original_message: str) -> str:
    """Build a clarification message when LLM confidence is low.

    Returns a helpful message with suggestion chips.
    """
    parts = ["I'm not sure exactly what you're looking for. Could you be more specific?"]

    if spec:
        if spec.variables:
            parts.append(f"\nDid you mean: **{', '.join(spec.variables)}**?")
        if spec.spatial_filter:
            parts.append(f"\nRegion: **{spec.spatial_filter.replace('_', ' ').title()}**?")
        parts.append(f"\n(Intent detected: {spec.action}, confidence: {spec.confidence:.0%})")

    parts.append("\n\nTry something like:")
    parts.append("• temperature in Arabian Sea 2024")
    parts.append("• oxygen in Bay of Bengal during monsoon")
    parts.append("• trajectory of float 2902403")
    parts.append("• active floats near Goa last monsoon")

    return "\n".join(parts)
