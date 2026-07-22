"""Abstract interface for conversation context managers."""

from abc import ABC, abstractmethod

from floatchat.models import ChatResponse, ConversationContext, ParsedIntent


class AbstractConversationManager(ABC):
    """Store and retrieve per-session conversation context.

    Implementations must be thread-safe and support multiple independent
    sessions keyed by ``session_id``.
    """

    @abstractmethod
    def get_context(self, session_id: str) -> ConversationContext | None:
        """Return the active context for *session_id*, or ``None``."""
        ...

    @abstractmethod
    def merge_context(
        self,
        session_id: str | None,
        intent: ParsedIntent,
        message: str | None = None,
    ) -> ParsedIntent:
        """Return a new :class:`ParsedIntent` with missing fields filled from context.

        Args:
            session_id: Client-provided session identifier. If ``None``,
                *intent* is returned unchanged.
            intent: Freshly parsed intent (may have empty/missing fields).
            message: The user's raw message for the current turn. This is used
                to detect reference phrases that gate context inheritance
                (Priority 2, constraint #6). Passing it explicitly here is the
                robust contract: the chat pipeline reconstructs ``ParsedIntent``
                objects during LLM extraction/recovery, which would otherwise
                drop a dynamically-attached ``_original_message`` attribute and
                silently disable inheritance. Implementations fall back to an
                ``_original_message`` attribute on *intent* for backward
                compatibility with direct callers/tests.

        Returns:
            A copy of *intent* with gaps filled from stored context.
            Explicit values in *intent* are never overwritten.
        """
        ...

    @abstractmethod
    def update_context(
        self,
        session_id: str | None,
        intent: ParsedIntent,
        response: ChatResponse,
    ) -> None:
        """Persist *intent* and *response* so future follow-ups can reference them.

        Args:
            session_id: Client-provided session identifier. If ``None``,
                the call is a no-op.
            intent: The **merged** intent that was actually executed.
            response: The response that was sent to the user.
        """
        ...

    @abstractmethod
    def clear_context(self, session_id: str) -> None:
        """Remove all stored state for *session_id*."""
        ...
