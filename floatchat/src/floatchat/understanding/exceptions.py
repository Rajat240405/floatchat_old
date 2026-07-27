"""Semantic Understanding Layer exceptions (FloatChat 2.0 — Phase 2)."""

from floatchat.exceptions import FloatChatError, IntentParseError

#: Machine-readable failure reasons carried by SemanticUnavailableError
#: (Phase 2.1 instrumentation; logged per request).
REASON_DISABLED = "disabled"
REASON_NO_PROVIDER = "no_provider"
REASON_LLM_ERROR = "llm_error"
REASON_EMPTY_OUTPUT = "empty_output"
REASON_NOT_JSON = "not_json"
REASON_SCHEMA_INVALID = "schema_invalid"
REASON_CONVERSION_INVALID = "conversion_invalid"


class SemanticUnavailableError(FloatChatError):
    """The semantic layer could not produce a usable representation.

    Raised when the layer is disabled by configuration, no LLM provider can
    be constructed, the LLM call fails, or the model output cannot be
    validated as a :class:`SemanticUnderstanding`. The intent resolver treats
    this as *expected* and falls back to the legacy regex-first pipeline —
    it never surfaces to the user.

    ``reason`` is a machine-readable code (see REASON_* constants) so logs
    and benches can group fallback causes; it is also copied into ``details``
    for consumers that only read the exception payload.
    """

    def __init__(
        self,
        message: str,
        *,
        reason: str = "unknown",
        details: dict | None = None,
    ) -> None:
        merged = dict(details or {})
        merged.setdefault("reason", reason)
        super().__init__(message, details=merged)
        self.reason = reason


class SemanticClarificationNeeded(IntentParseError):
    """The semantic layer requires clarification instead of guessing.

    Raised by the converter/resolver when the semantic output is incomplete
    or ambiguous and the correct behaviour is to ask the scientist a targeted
    question rather than invent values.

    Subclasses :class:`IntentParseError` so legacy call sites keep working;
    the chat service catches this subclass FIRST and answers with the
    clarification question (response pseudo-intent ``"clarification"``)
    instead of the generic parse-failure suggestion.
    """
