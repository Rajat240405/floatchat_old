"""Conversation context management for multi-turn follow-up queries.

Phase 4 adds the deterministic Conversation Intelligence layer: scientific
focus tracking + reference resolution before the Semantic Reasoner, plus
conversation-control commands (session management).
"""

from floatchat.conversation.base import AbstractConversationManager
from floatchat.conversation.intelligence import (
    ContextClarification,
    ContextResolution,
    ControlResult,
    ConversationFocus,
    ConversationIntelligence,
)
from floatchat.conversation.memory import InMemoryConversationManager

__all__ = [
    "AbstractConversationManager",
    "InMemoryConversationManager",
    "ConversationIntelligence",
    "ConversationFocus",
    "ContextResolution",
    "ContextClarification",
    "ControlResult",
]
