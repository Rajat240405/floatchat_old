"""Models for metadata records and search criteria."""

from datetime import datetime

from pydantic import BaseModel, Field


class MetadataRecord(BaseModel):
    """A single row from the Argo BGC bio-profile index.

    The ``file`` field contains the relative path inside the GDAC ``dac/``
    directory, e.g. ``coriolis/6903091/profiles/BR6903091_001.nc``.
    """

    file: str = Field(..., description="Relative path from GDAC dac/ root.")
    date: datetime = Field(..., description="Profile date (UTC).")
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    ocean: str = Field(..., description="Ocean code (e.g., A, I, P).")
    profiler_type: str = Field(..., description="Argo profiler type code.")
    institution: str = Field(..., description="Data assembly centre code.")
    parameters: str = Field(
        ...,
        description="Space-separated list of parameters in the profile.",
    )
    parameter_data_mode: str = Field(
        ...,
        description="Space-separated data mode flags (R, A, D).",
    )
    date_update: datetime = Field(..., description="Last file update (UTC).")


class SearchCriteria(BaseModel):
    """Criteria used by the MetadataService to filter the index.

    This is intentionally separate from :class:`ParsedIntent` so that the
    metadata service never depends on intent-parser concepts.
    """

    region: str | None = Field(default=None, description="Named ocean region.")
    lat_min: float | None = Field(default=None, ge=-90.0, le=90.0)
    lat_max: float | None = Field(default=None, ge=-90.0, le=90.0)
    lon_min: float | None = Field(default=None, ge=-180.0, le=180.0)
    lon_max: float | None = Field(default=None, ge=-180.0, le=180.0)
    year: int | None = Field(default=None, ge=1900, le=2100)
    month: int | None = Field(default=None, ge=1, le=12)
    day: int | None = Field(default=None, ge=1, le=31)
    parameters: list[str] = Field(
        default_factory=list,
        description="Required parameters (AND logic).",
    )
    float_id: str | None = Field(default=None, description="WMO float ID.")
    profile_number: int | None = Field(
        default=None,
        ge=1,
        description="Specific profile cycle number (e.g. 52 → _052.nc).",
    )
    limit: int = Field(default=5, ge=1, le=10000)
