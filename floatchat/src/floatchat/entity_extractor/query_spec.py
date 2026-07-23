"""Priority 3: QuerySpec — structured output from LLM entity extraction.

The LLM returns a validated JSON object matching this schema.
This is the ONLY shape the LLM is allowed to produce — never raw SQL,
never free text, never unvalidated fields.
"""

from pydantic import BaseModel, Field, field_validator


class QuerySpec(BaseModel):
    """Structured entity extraction from a user's natural language query.

    Produced by the LLM entity extractor and validated before use.
    """

    action: str = Field(
        description=(
            "The user's intent. Must be one of: "
            "region_search, profile_plot, time_series, hovmoller, ts_diagram, "
            "comparison_plot, trajectory, nearest_float, radius_search, "
            "metadata_lookup, count_aggregate"
        ),
    )
    variables: list[str] = Field(
        default_factory=list,
        description=(
            "Argo variable names requested. Must be from: "
            "TEMP, PSAL, DOXY, CHLA, BBP700, NITRATE, PH_IN_SITU_TOTAL, "
            "DOWNWELLING_PAR. Empty if not specified."
        ),
    )
    spatial_filter: str | None = Field(
        default=None,
        description=(
            "Named region or place. Must be one of: "
            "arabian_sea, bay_of_bengal, equatorial_indian_ocean, southern_indian_ocean, indian_ocean (alias for all IO). "
            "Or a place name for geocoding. Null if not specified."
        ),
    )
    time_filter: str | None = Field(
        default=None,
        description=(
            "Semantic temporal expression. Examples: '2024', 'monsoon', "
            "'last monsoon', '2023-06-01 to 2023-09-30', 'January'. "
            "Null if not specified. Will be resolved by deterministic temporal resolver."
        ),
    )
    float_id: str | None = Field(
        default=None,
        description="7-digit WMO float ID. Null if not specified.",
    )
    depth_filter: str | None = Field(
        default=None,
        description=(
            "Depth-related expression. Examples: 'deep', 'surface', "
            "'below 1000m', '0-200m'. Null if not specified."
        ),
    )
    operational_filter: str | None = Field(
        default=None,
        description=(
            "Operational aspect. Examples: 'alive', 'active', 'inactive', "
            "'drift', 'parking depth'. Null if not specified."
        ),
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description=(
            "Extraction confidence from 0.0 to 1.0. "
            "Below 0.5 → system should ask for clarification."
        ),
    )

    @field_validator("action", mode="before")
    @classmethod
    def _normalize_action(cls, v: str) -> str:
        """Normalize action to known intents."""
        v = str(v).strip().lower().replace("-", "_").replace(" ", "_")
        # Map common aliases
        _ALIASES = {
            "compare": "comparison_plot",
            "comparison": "comparison_plot",
            "profile": "profile_plot",
            "plot": "profile_plot",
            "timeseries": "time_series",
            "hovmoller_plot": "hovmoller",
            "ts_plot": "ts_diagram",
            "metadata": "metadata_lookup",
            "sensor_info": "metadata_lookup",
            "count": "count_aggregate",
            "search": "region_search",
            "find": "region_search",
        }
        return _ALIASES.get(v, v)

    @field_validator("variables", mode="before")
    @classmethod
    def _normalize_variables(cls, v: list) -> list[str]:
        """Normalize variable names to uppercase Argo conventions."""
        if not isinstance(v, list):
            return []
        _VAR_MAP = {
            "TEMP": "TEMP",
            "TEMPERATURE": "TEMP",
            "TEMP_ADJUSTED": "TEMP",
            "PSAL": "PSAL",
            "SALINITY": "PSAL",
            "PSAL_ADJUSTED": "PSAL",
            "DOXY": "DOXY",
            "OXYGEN": "DOXY",
            "DISSOLVED_OXYGEN": "DOXY",
            "O2": "DOXY",
            "DOXY_ADJUSTED": "DOXY",
            "CHLA": "CHLA",
            "CHLOROPHYLL": "CHLA",
            "CHLOROPHYLL_A": "CHLA",
            "CHLA_ADJUSTED": "CHLA",
            "BBP700": "BBP700",
            "BACKSCATTERING": "BBP700",
            "NITRATE": "NITRATE",
            "NO3": "NITRATE",
            "PH_IN_SITU_TOTAL": "PH_IN_SITU_TOTAL",
            "PH": "PH_IN_SITU_TOTAL",
            "DOWNWELLING_PAR": "DOWNWELLING_PAR",
            "PAR": "DOWNWELLING_PAR",
        }
        result = []
        for item in v:
            key = str(item).strip().upper().replace(" ", "_")
            canonical = _VAR_MAP.get(key)
            if canonical and canonical not in result:
                result.append(canonical)
        return result

    @field_validator("spatial_filter", mode="before")
    @classmethod
    def _normalize_spatial(cls, v: str | None) -> str | None:
        """Normalize region names to underscore format."""
        if not v:
            return None
        v = str(v).strip().lower().replace(" ", "_")
        _REGION_MAP = {
            "arabian_sea": "arabian_sea",
            "arabian": "arabian_sea",
            "bay_of_bengal": "bay_of_bengal",
            "bengal": "bay_of_bengal",
            "bob": "bay_of_bengal",
            "equatorial_indian_ocean": "equatorial_indian_ocean",
            "equatorial_io": "equatorial_indian_ocean",
            "tropical_indian_ocean": "equatorial_indian_ocean",
            "southern_indian_ocean": "southern_indian_ocean",
            "south_indian_ocean": "southern_indian_ocean",
            "southern_io": "southern_indian_ocean",
            # Query alias — expand_region_filter unions all four leaves.
            "indian_ocean": "indian_ocean",
            "io": "indian_ocean",
            "north_indian_ocean": "indian_ocean",
            "nio": "indian_ocean",
        }
        return _REGION_MAP.get(v, v)
