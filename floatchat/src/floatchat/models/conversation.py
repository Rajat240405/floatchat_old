"""Conversation context models for follow-up query resolution."""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class ConversationContext(BaseModel):
    """Snapshot of a conversation session for contextual follow-up queries.

    Stored per ``session_id`` by a :class:`AbstractConversationManager`.
    """

    session_id: str
    turn_count: int = 0
    last_intent: str | None = None
    last_float_id: str | None = None
    last_variables: list[str] = Field(default_factory=list)
    last_region: str | None = None
    last_year: int | None = None
    last_profile_number: int | None = None
    last_lat: float | None = None
    last_lon: float | None = None
    last_radius_km: float | None = None
    last_message: str | None = None
    last_response_summary: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
