"""API response models."""

from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field, field_validator


def _sanitize_for_json(obj: Any) -> Any:
    """Recursively convert numpy arrays, pandas series, and timestamps to native Python types for JSON serialization."""
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    if isinstance(obj, tuple):
        return [_sanitize_for_json(v) for v in obj]
    if hasattr(obj, "tolist") and callable(obj.tolist):
        return _sanitize_for_json(obj.tolist())
    if hasattr(obj, "isoformat") and callable(obj.isoformat):
        return obj.isoformat()
    if isinstance(obj, (np.integer, np.floating)):
        return obj.item()
    if isinstance(obj, np.bool_):
        return bool(obj)
    if pd.isna(obj):
        return None
    return obj


class MapData(BaseModel):
    """Geographic marker data for a single Argo float profile."""

    float_id: str = Field(..., description="Argo float WMO identifier.")
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    profile_date: str | None = Field(default=None, description="ISO-8601 profile date.")
    profile_number: int | None = Field(default=None, description="Cycle / profile number.")
    dac: str = Field(default="", description="Data assembly centre code.")
    variables: list[str] = Field(default_factory=list, description="Available BGC variables.")
    selected: bool = Field(default=False, description="Whether this marker is selected.")
    status: str | None = Field(default="unknown", description="Float status: active, inactive, drifted, unknown.")
    # Phase 5 Part A: Manufacturer info for map popup
    manufacturer: str | None = Field(default=None, description="Float manufacturer name.")
    profiler_type: str | None = Field(default=None, description="Profiler type code or name.")
    # Redesign: first-class scientific attributes on every marker so the
    # sidebar filters (Network, DAC) and map popups stay consistent with the
    # metadata inspector. Derived when not authoritative.
    network: str | None = Field(default=None, description="Argo network: Core Argo or BGC Argo.")
    wmo_id: str | None = Field(default=None, description="WMO identifier (mirrors float_id when not distinct).")
    region_tag: str | None = Field(default=None, description="India-region tag: arabian_sea | bay_of_bengal | indian_ocean.")
    profile_count: int | None = Field(
        default=None,
        description="Number of profiles/cycles for this float (marker sizing).",
    )


class ChatResponse(BaseModel):
    """Successful response from POST /chat.

    The ``figure`` field contains a Plotly JSON figure dict when a
    visualization was generated; otherwise it is ``None``.
    """

    intent: str = Field(..., description="Resolved intent type.")
    message: str = Field(..., description="Human-readable summary.")
    figure: dict[str, Any] | None = Field(
        default=None,
        description="Plotly JSON figure object (combined multi-subplot view).",
    )
    figures: list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "Per-variable Plotly figure objects for the redesigned stacked plot "
            "drawer. Each entry is a standalone single-variable figure with a "
            "'variable' field. Populated for profile/comparison intents; "
            "None when not applicable."
        ),
    )
    data_summary: dict[str, Any] = Field(
        default_factory=dict,
        description="Summary statistics or metadata about the result.",
    )
    map_data: list[MapData] = Field(
        default_factory=list,
        description="Geographic markers for returned float profiles.",
    )

    @field_validator("figure", "figures", "data_summary", mode="before")
    @classmethod
    def _clean_payload_data(cls, v: Any) -> Any:
        return _sanitize_for_json(v) if v is not None else v


class ErrorResponse(BaseModel):
    """Standard error response body."""

    error: str = Field(..., description="Error type code.")
    message: str = Field(..., description="Human-readable error message.")
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional diagnostic information.",
    )
