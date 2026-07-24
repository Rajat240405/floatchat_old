"""Intent model: the single typed object that crosses the NL → backend boundary."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from floatchat.variable_registry.registry import VariableRegistry


class ParsedIntent(BaseModel):
    """Structured representation of a user's natural-language request.

    The intent parser (Mock, Regex, or LLM) is responsible for producing this
    object. All downstream modules consume *only* this model.
    """

    intent: Literal[
        "profile_plot",
        "region_search",
        "time_series",
        "comparison_plot",
        "comparison",
        "trajectory",
        "hovmoller",
        "ts_diagram",
        "general_chat",
        "unknown",
        "nearest_float",
        "radius_search",
        "metadata_lookup",
        "count_aggregate",
        # Phase 6 — Traffic Cop 4-way routing
        "small_talk",
        "out_of_domain",
        "knowledge_base",
    ] = Field(
        default="unknown",
        description="Deterministic routing key for the query & visualization engine.",
    )
    region: str | None = Field(default=None, description="Named ocean region.")
    variables: list[str] = Field(
        default_factory=list,
        description="Requested BGC variables (e.g., DOXY, CHLA).",
    )
    comparison_float_ids: list[str] = Field(
        default_factory=list,
        description="Target float IDs for comparison query.",
    )
    comparison_regions: list[str] = Field(
        default_factory=list,
        description="Target regions for comparison query.",
    )
    year: int | None = Field(default=None, ge=1900, le=2100)
    month: int | None = Field(default=None, ge=1, le=12)
    # P3 #3: season month-window (e.g. monsoon -> [6,7,8,9]). When set, the data
    # lake filters month IN (...) instead of month = ?. Kept separate from
    # `month` (the representative start month) for backward compatibility.
    month_window: list[int] | None = Field(default=None, description="Season month window (e.g. JJAS=[6,7,8,9]).")
    day: int | None = Field(default=None, ge=1, le=31)
    lat_min: float | None = Field(default=None, ge=-90.0, le=90.0)
    lat_max: float | None = Field(default=None, ge=-90.0, le=90.0)
    lon_min: float | None = Field(default=None, ge=-180.0, le=180.0)
    lon_max: float | None = Field(default=None, ge=-180.0, le=180.0)
    lat: float | None = Field(default=None, ge=-90.0, le=90.0, description="Target point latitude for spatial queries.")
    lon: float | None = Field(default=None, ge=-180.0, le=180.0, description="Target point longitude for spatial queries.")
    radius_km: float | None = Field(default=None, ge=0.0, description="Search radius in kilometers for spatial queries.")
    existence_check: bool = Field(default=False, description="Whether query asks if data exists vs count.")
    depth_min: float | None = Field(default=None, ge=0)
    depth_max: float | None = Field(default=None, ge=0)
    float_id: str | None = Field(
        default=None,
        description="Argo float WMO identifier.",
    )
    profile_number: int | None = Field(
        default=None,
        ge=1,
        description="Specific profile/cycle number to retrieve.",
    )
    cycle_number: int | None = Field(default=None, ge=1)
    # P3 #2 / P2: Operational + resolved-temporal attributes promoted to proper
    # fields so they survive model_dump() + ParsedIntent reconstruction (the old
    # underscore-prefixed dynamic attrs were silently dropped by the `not
    # k.startswith("_")` filter in routes.py, making alive-filtering dead code).
    operational_filter: str | None = Field(
        default=None,
        description="Operational filter: 'alive' = float has >=1 recent profile.",
    )
    temporal_date_start: str | None = Field(
        default=None,
        description="ISO date start for a resolved temporal range (from LLM season).",
    )
    temporal_date_end: str | None = Field(
        default=None,
        description="ISO date end for a resolved temporal range (from LLM season).",
    )
    limit: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum number of profiles to retrieve.",
    )

    @field_validator("variables", mode="before")
    @classmethod
    def _uppercase_variables(cls, v: list[str]) -> list[str]:
        """Normalise variable names to uppercase Argo conventions."""
        if isinstance(v, list):
            return [VariableRegistry.normalize(str(item)) for item in v]
        return v

    @field_validator("region")
    @classmethod
    def _lowercase_region(cls, v: str | None) -> str | None:
        if v:
            return v.strip().lower().replace(" ", "_")
        return v
