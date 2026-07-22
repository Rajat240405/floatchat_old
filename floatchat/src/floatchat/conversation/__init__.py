"""Conversation context management for multi-turn follow-up queries."""

from floatchat.conversation.base import AbstractConversationManager
from floatchat.conversation.memory import InMemoryConversationManager

__all__ = ["AbstractConversationManager", "InMemoryConversationManager"]
