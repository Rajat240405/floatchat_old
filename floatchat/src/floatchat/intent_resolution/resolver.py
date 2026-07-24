"""Canonical deterministic-first intent resolution pipeline.

This module is the single boundary between natural language and the rest of
FloatChat. Regex remains authoritative; the LLM compiler only fills fields
that are absent from the deterministic result.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from floatchat.conversation.base import AbstractConversationManager
from floatchat.conversation.reference_phrases import detect_reference_phrases
from floatchat.intent_resolution.llm_compiler import LLMIntentCompiler
from floatchat.exceptions import IntentParseError
from floatchat.intent_parser.base import AbstractIntentParser
from floatchat.models import ParsedIntent
from floatchat.variable_registry.registry import VariableRegistry

logger = logging.getLogger(__name__)


class IntentResolutionError(IntentParseError):
    """Raised when neither deterministic parsing nor the compiler can resolve a request."""


class IntentResolver:
    """Resolve one user message into one final, validated ParsedIntent."""

    def __init__(
        self,
        parser: AbstractIntentParser,
        compiler: LLMIntentCompiler | None = None,
        conversation_manager: AbstractConversationManager | None = None,
    ) -> None:
        self.parser = parser
        self.compiler = compiler
        self.conversation_manager = conversation_manager

    def resolve(self, message: str, session_id: str | None = None) -> ParsedIntent:
        """Run deterministic parse, fallback compilation, validation, and context enrichment."""
        parsed: ParsedIntent | None = None
        parse_error: Exception | None = None

        try:
            parsed = self.parser.parse(message)
        except Exception as exc:  # parser contract exposes IntentParseError; preserve fallback behavior
            parse_error = exc
            logger.info("Deterministic intent parse failed; trying compiler: %s", exc)

        if parsed is None and self.compiler is not None:
            # Compiler fallback is only for a normal deterministic parse
            # failure. Unexpected parser/runtime exceptions must propagate to
            # preserve the existing structured error response.
            if parse_error is None or isinstance(parse_error, IntentParseError):
                parsed = self.compiler.compile(message)

        if parsed is None:
            if isinstance(parse_error, IntentParseError):
                raise parse_error
            # Preserve the existing outer-route handling for unexpected parser
            # failures; it returns the established structured error response.
            if parse_error is not None:
                raise parse_error
            raise IntentResolutionError(
                "Could not resolve the request into a ParsedIntent.",
                details={"message": message},
            )

        # The compiler is allowed only to fill unresolved fields. It cannot
        # replace deterministic values. This second call is used only when the
        # deterministic result is structurally incomplete.
        if self.compiler is not None and self._needs_compilation(parsed):
            compiled = self.compiler.compile(message, seed=parsed)
            if compiled is not None:
                parsed = self._merge_unresolved(parsed, compiled)

        parsed = self._validate(parsed)
        # Deterministic metadata-followup routing remains part of the canonical
        # resolver, not the HTTP route.
        if detect_reference_phrases(message).is_metadata_followup and parsed.intent != "metadata_lookup":
            data = parsed.model_dump()
            data["intent"] = "metadata_lookup"
            parsed = ParsedIntent.model_validate(data)

        # Context enrichment happens after validation and does not change the
        # parser/compiler ownership of fields.
        ref = detect_reference_phrases(message)
        previous_context = (
            self.conversation_manager.get_context(session_id)
            if self.conversation_manager is not None and session_id
            else None
        )
        if (
            previous_context is not None
            and self._context_dependent(message)
            and previous_context.last_intent in {
                "profile_plot", "time_series", "hovmoller", "ts_diagram",
                "comparison_plot", "comparison", "trajectory",
            }
        ):
            data = parsed.model_dump()
            if parsed.intent == "unknown":
                data["intent"] = previous_context.last_intent
            if data.get("float_id") is None:
                data["float_id"] = previous_context.last_float_id
            if data.get("profile_number") is None:
                data["profile_number"] = previous_context.last_profile_number
            if not data.get("variables"):
                data["variables"] = list(previous_context.last_variables)
            if data.get("region") is None:
                data["region"] = previous_context.last_region
            parsed = ParsedIntent.model_validate(data)

        if self.conversation_manager is not None:
            parsed = self.conversation_manager.merge_context(
                session_id, parsed, message=message, in_place=True
            )

        # A scientific follow-up can be linguistically underspecified (for
        # example, "Explain this profile"). Reuse the previous data intent
        # only when an explicit scientific reference was detected.
        if (
            parsed.intent == "unknown"
            and ref.has_reference
            and previous_context is not None
            and previous_context.last_intent in {
                "profile_plot", "time_series", "hovmoller", "ts_diagram",
                "comparison_plot", "comparison",
            }
        ):
            parsed.intent = previous_context.last_intent

        if (
            parsed.intent == "unknown"
            and not parsed.variables
            and not parsed.float_id
            and not parsed.region
            and parsed.lat is None
            and parsed.lon is None
        ):
            raise IntentResolutionError(
                "The request did not contain enough information to resolve an intent.",
                details={"message": message},
            )

        return self._validate(parsed)

    @staticmethod
    def _context_dependent(message: str) -> bool:
        """Detect absence of an independent scope without enumerating phrases."""
        text = message.lower()
        has_float = bool(re.search(r"\b(?:float|wmo)\s*\d{5,}\b|\b\d{7}\b", text))
        has_region_or_place = bool(re.search(r"\b(?:in|near|around|within|from)\b", text))
        has_coordinates = bool(re.search(r"[-+]?\d+(?:\.\d+)?\s*,\s*[-+]?\d+(?:\.\d+)?", text))
        has_year = bool(re.search(r"\b(?:19|20)\d{2}\b", text))
        return not (has_float or has_region_or_place or has_coordinates or has_year)

    @staticmethod
    def _needs_compilation(intent: ParsedIntent) -> bool:
        if intent.intent in {"metadata_lookup", "trajectory"}:
            return intent.float_id is None
        if intent.intent == "count_aggregate":
            return intent.region is None and intent.float_id is None
        has_scope = bool(
            intent.float_id
            or intent.region
            or (intent.lat is not None and intent.lon is not None)
        )
        return not intent.variables or not has_scope or intent.year is None

    @staticmethod
    def _merge_unresolved(base: ParsedIntent, compiled: ParsedIntent) -> ParsedIntent:
        """Merge only missing values from the compiler into the deterministic result."""
        data = base.model_dump()
        for field_name in type(base).model_fields:
            current = data.get(field_name)
            candidate = getattr(compiled, field_name)
            missing = current is None or current == []
            if missing and candidate not in (None, []):
                data[field_name] = candidate
        # The model validator is the single construction gateway for this merge.
        return ParsedIntent.model_validate(data)

    @staticmethod
    def _validate(intent: ParsedIntent) -> ParsedIntent:
        """Canonical Pydantic + conservative semantic validation gateway."""
        validated = ParsedIntent.model_validate(intent.model_dump())
        if validated.profile_number is not None and not validated.float_id:
            raise IntentResolutionError(
                "A profile number requires a float ID.",
                details={"profile_number": validated.profile_number},
            )
        if (validated.lat is None) != (validated.lon is None):
            raise IntentResolutionError(
                "Latitude and longitude must be supplied together.",
                details={},
            )
        return validated
