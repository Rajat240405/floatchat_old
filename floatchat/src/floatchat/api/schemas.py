"""HTTP request/response schemas for the FloatChat API.

Cleanup M3: these models were moved verbatim from the former monolithic
``api/routes.py`` during the API-layer decomposition. They define the public
API contract and are shared by the thin route modules (``api/routes/``) and
the service modules (``api/services/``). Field names, types, defaults and
docstrings are unchanged — the OpenAPI schema is byte-identical.
"""

from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Incoming POST /chat body."""

    message: str = Field(..., min_length=1, description="Natural language query.")
    session_id: str | None = Field(
        default=None,
        description="Client-generated session ID for conversational continuity.",
    )


class FloatRegistryResponse(BaseModel):
    float_count: int
    map_data: list[dict]
    networks: list[str]
    dacs: list[str]
    variables: list[str]
    statuses: list[str]


class FloatMetadataAPIResponse(BaseModel):
    float_info: dict[str, Any]
    map_data: list[dict] = Field(default_factory=list)


class FloatTrajectoryAPIResponse(BaseModel):
    float_id: str
    cycle_count: int
    map_data: list[dict] = Field(default_factory=list)
    distance_km: float | None = None
    date_range: dict[str, Any] = Field(default_factory=dict)


class FloatProfileAPIResponse(BaseModel):
    float_id: str
    intent: str = "profile_plot"
    message: str = ""
    figure: dict[str, Any] | None = None
    figures: list[dict[str, Any]] | None = None
    data_summary: dict[str, Any] = Field(default_factory=dict)
    map_data: list[dict] = Field(default_factory=list)


class AvailablePlotItem(BaseModel):
    variable: str
    title: str
    profiles: int = 0


class FloatAvailablePlotsResponse(BaseModel):
    float_id: str
    plots: list[AvailablePlotItem] = Field(default_factory=list)
