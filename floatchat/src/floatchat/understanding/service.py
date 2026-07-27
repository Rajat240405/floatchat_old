"""SemanticUnderstandingService — the Phase 2 LLM understanding call.

Pipeline position (Target Architecture, Phase 2):

    User → Conversation Context → Domain Ontology → **LLM Semantic
    Understanding** → SemanticUnderstanding → deterministic conversion →
    ParsedIntent → existing Planner/QueryEngine/Execution (unchanged)

This service owns exactly ONE LLM interaction: it renders the ontology-built
system prompt, asks the model for structured JSON, and validates it into a
:class:`SemanticUnderstanding`. Every failure mode (disabled flag, provider
unavailable, call exception, malformed JSON, schema violation) raises
:class:`SemanticUnavailableError` — a *benign* signal the intent resolver
converts into the legacy regex-first fallback path.

The deterministic conversion (:class:`SemanticConverter`) is deliberately a
separate collaborator: the model never emits ``ParsedIntent``.
"""

from __future__ import annotations

import json
import logging
import re
from time import perf_counter
from typing import Any

from floatchat.config import settings
from floatchat.llm_service.base import AbstractLLMService
from floatchat.understanding.converter import ConversionOutcome, SemanticConverter
from floatchat.understanding.exceptions import (
    REASON_CONVERSION_INVALID,
    REASON_DISABLED,
    REASON_EMPTY_OUTPUT,
    REASON_LLM_ERROR,
    REASON_NO_PROVIDER,
    REASON_NOT_JSON,
    REASON_SCHEMA_INVALID,
    SemanticUnavailableError,
)
from floatchat.understanding.models import SemanticUnderstanding
from floatchat.understanding.prompt import build_system_prompt, build_user_prompt

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"```(?:json)?\s*(?P<body>.*?)```", re.DOTALL)


def _log_outcome(
    *,
    outcome: str,
    reason: str,
    fallback: bool,
    semantic_ms: float,
    convert_ms: float,
    message: str,
    intent: str | None = None,
    confidence: float | None = None,
    rule: str | None = None,
) -> None:
    """One structured instrumentation line per request (Phase 2.1).

    Fields are key=value (awk/grep friendly):
    outcome=converted|clarification|failure, reason=<code>, fallback=true|false,
    semantic_ms (LLM understand latency), convert_ms (deterministic converter
    latency), total_ms (whole understanding stage), rule=<reasoner rule>
    (Phase 3 explainability).
    """
    logger.info(
        "SEMANTIC_UNDERSTANDING outcome=%s intent=%s confidence=%s reason=%s "
        "fallback=%s semantic_ms=%.1f convert_ms=%.1f total_ms=%.1f rule=%s msg=%r",
        outcome,
        intent or "-",
        f"{confidence:.2f}" if isinstance(confidence, float) else "-",
        reason,
        "true" if fallback else "false",
        semantic_ms,
        convert_ms,
        semantic_ms + convert_ms,
        rule or "-",
        message[:80],
    )


class SemanticUnderstandingService:
    """Understands one user message into a SemanticUnderstanding via an LLM."""

    def __init__(
        self,
        service: AbstractLLMService | None = None,
        converter: SemanticConverter | None = None,
        conversation_intelligence: Any | None = None,
    ) -> None:
        # Same lazy-construction convention as LLMIntentCompiler: an explicit
        # service (tests/DI) is honoured; otherwise the provider factory is
        # tried once on first use.
        self._service = service
        self._tried = service is not None
        if converter is not None:
            self._converter = converter
        else:
            # Phase 4: the default converter is wired with the deterministic
            # Conversation Intelligence layer (reference resolution before
            # the reasoner). An explicitly injected converter is used as-is.
            self._converter = SemanticConverter(
                conversation_intelligence=conversation_intelligence
            )

    # ------------------------------------------------------------------ #
    # Availability
    # ------------------------------------------------------------------ #

    @property
    def enabled(self) -> bool:
        """Configuration gate: flag on + LLM on + model configured."""
        return bool(
            settings.semantic_understanding_enabled
            and settings.llm_enabled
            and settings.semantic_model
        )

    def _get_service(self) -> AbstractLLMService | None:
        if self._service is None and not self._tried:
            self._tried = True
            try:
                from floatchat.llm_service.factory import build_semantic_llm_service

                self._service = build_semantic_llm_service()
            except Exception as exc:  # noqa: BLE001 — degrade gracefully
                logger.warning("Could not build semantic LLM service: %s", exc)
        return self._service

    # ------------------------------------------------------------------ #
    # Understanding (single LLM call; the ONLY LLM surface in this layer)
    # ------------------------------------------------------------------ #

    def understand(
        self,
        message: str,
        conversation_context: Any | None = None,
    ) -> SemanticUnderstanding:
        """Understand *message* via the LLM and validate the representation.

        Raises SemanticUnavailableError when no usable representation can be
        produced (resolver then falls back to the regex parser).
        """
        if not self.enabled:
            raise SemanticUnavailableError(
                "Semantic understanding layer is disabled.",
                reason=REASON_DISABLED,
                details={
                    "flag": settings.semantic_understanding_enabled,
                    "llm_enabled": settings.llm_enabled,
                    "model_configured": bool(settings.semantic_model),
                },
            )
        service = self._get_service()
        if service is None:
            raise SemanticUnavailableError(
                "No LLM provider available for semantic understanding.",
                reason=REASON_NO_PROVIDER,
            )

        prompt = build_user_prompt(message, conversation_context)
        # The SINGLE LLM call of the whole understanding pipeline (Phase 2.1
        # invariant: one understanding call, everything else deterministic).
        llm_t0 = perf_counter()
        try:
            raw = service.generate(prompt, system=build_system_prompt())
        except Exception as exc:
            logger.info("Semantic understanding LLM call failed: %s", exc)
            raise SemanticUnavailableError(
                f"Semantic understanding call failed: {exc}",
                reason=REASON_LLM_ERROR,
                details={
                    "message": message[:120],
                    "llm_ms": round((perf_counter() - llm_t0) * 1000.0, 1),
                },
            ) from exc
        return self._validate_output(raw, message)

    @staticmethod
    def _validate_output(raw: str, message: str) -> SemanticUnderstanding:
        """Parse/validate the model output into the understanding contract."""
        text = (raw or "").strip()
        if not text:
            raise SemanticUnavailableError(
                "Semantic understanding returned empty output.",
                reason=REASON_EMPTY_OUTPUT,
            )
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            match = _FENCE_RE.search(text)
            if match:
                try:
                    data = json.loads(match.group("body").strip())
                except json.JSONDecodeError:
                    data = None
            else:
                data = None
        if not isinstance(data, dict):
            raise SemanticUnavailableError(
                "Semantic understanding output was not a JSON object.",
                reason=REASON_NOT_JSON,
                details={"raw_prefix": text[:160]},
            )
        try:
            return SemanticUnderstanding.model_validate(data)
        except Exception as exc:
            logger.info("Semantic understanding output failed validation: %s", exc)
            raise SemanticUnavailableError(
                f"Semantic understanding output invalid: {exc}",
                reason=REASON_SCHEMA_INVALID,
                details={"raw_prefix": text[:160]},
            ) from exc

    # ------------------------------------------------------------------ #
    # Full pipeline: understand → deterministic conversion
    # ------------------------------------------------------------------ #

    def resolve(
        self,
        message: str,
        conversation_context: Any | None = None,
        session_id: str | None = None,
    ) -> ConversionOutcome:
        """Understand + deterministically convert, with per-request instrumentation.

        Emits exactly one SEMANTIC_UNDERSTANDING log line per call covering:
        success/failure, reason, understanding (LLM) latency, converter
        latency, whether the fallback will be used, and total understanding
        latency (Phase 2.1 observability requirement). Raises
        SemanticUnavailableError on any failure (after logging it).
        """
        semantic_t0 = perf_counter()
        try:
            understanding = self.understand(message, conversation_context)
        except SemanticUnavailableError as exc:
            _log_outcome(
                outcome="failure",
                reason=exc.reason,
                fallback=True,
                semantic_ms=(perf_counter() - semantic_t0) * 1000.0,
                convert_ms=0.0,
                message=message,
            )
            raise
        semantic_ms = (perf_counter() - semantic_t0) * 1000.0

        convert_t0 = perf_counter()
        try:
            # Phase 4: the deterministic Conversation Intelligence layer keys
            # conversation memory by session id. Prefer the explicit id; fall
            # back to the legacy context snapshot's own id. No session →
            # single-request behaviour identical to Phase 3, and injected
            # converter doubles with the pre-Phase-4 signature keep working.
            sid = session_id or getattr(conversation_context, "session_id", None)
            if sid:
                outcome = self._converter.convert(understanding, session_id=sid)
            else:
                outcome = self._converter.convert(understanding)
        except SemanticUnavailableError as exc:
            convert_ms = (perf_counter() - convert_t0) * 1000.0
            _log_outcome(
                outcome="failure",
                reason=getattr(exc, "reason", REASON_CONVERSION_INVALID),
                fallback=True,
                semantic_ms=semantic_ms,
                convert_ms=convert_ms,
                message=message,
            )
            raise
        convert_ms = (perf_counter() - convert_t0) * 1000.0

        _log_outcome(
            outcome=outcome.kind,  # "intent" → converted | "clarification"
            reason="ok",
            fallback=False,
            semantic_ms=semantic_ms,
            convert_ms=convert_ms,
            message=message,
            intent=outcome.parsed_intent.intent if outcome.parsed_intent else None,
            confidence=understanding.confidence,
            rule=outcome.reasoning_rule,  # Phase 3 reasoner trace
        )
        logger.debug(
            "Semantic understanding converted %r → intent=%s ambiguities=%d",
            message[:80],
            outcome.parsed_intent.intent if outcome.parsed_intent else None,
            len(outcome.ambiguities),
        )
        return outcome
