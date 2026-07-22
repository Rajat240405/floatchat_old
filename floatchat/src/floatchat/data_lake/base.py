"""Abstract interface for the local data lake.

Phase 1: Provides a structured contract for querying pre-ingested
Argo profile data from DuckDB/Parquet storage, serving as an alternative
to live GDAC fetching for region-level aggregation queries.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

import pandas as pd


@dataclass
class LakeQueryResult:
    """Result returned by a data lake query.

    Contains both the raw DataFrame (for downstream processing) and
    pre-computed aggregates suitable for ScientificFacts construction.
    """

    #: The tidy level-by-level DataFrame matching the query criteria.
    df: pd.DataFrame

    #: Pre-aggregated summary statistics keyed by variable name.
    #: Each value is a dict with keys: min, max, mean, median, count,
    #: surface_mean_0_10m, deep_mean_below_200m, deepest_pres, deepest_val
    stats: dict[str, dict[str, float | int | None]] = field(default_factory=dict)

    #: Number of unique float IDs matching the query.
    unique_floats: int = 0

    #: Number of unique profile dates.
    unique_profiles: int = 0

    #: Earliest profile date in result set.
    date_min: datetime | None = None

    #: Latest profile date in result set.
    date_max: datetime | None = None

    #: Total measurement rows (len of df).
    total_measurements: int = 0

    #: Whether the lake had data for this query (may be empty but valid).
    has_data: bool = False

    #: Source description (for provenance in ScientificFacts).
    source: str = "Argo Data Lake (DuckDB/Parquet)"


@dataclass
class LakeQueryCriteria:
    """Structured query criteria for the data lake.

    Mirrors the existing SearchCriteria intent but adapted for
    lake-only queries (no live GDAC fetching).
    """

    region: Literal["arabian_sea", "bay_of_bengal"] | None = None
    lat_min: float | None = None
    lat_max: float | None = None
    lon_min: float | None = None
    lon_max: float | None = None
    year: int | None = None
    month: int | None = None
    # P3 #3: season month-window. When set, the lake filters month IN (...) and
    # ignores the single `month`. e.g. monsoon → [6,7,8,9].
    months: list[int] | None = None
    variables: list[str] = field(default_factory=list)
    float_id: str | None = None
    profile_number: int | None = None
    limit: int = 100  # max number of profile cycles to return
    depth_min: float | None = None  # dbar
    depth_max: float | None = None  # dbar


class AbstractDataLake(ABC):
    """Query pre-ingested Argo profiles from local DuckDB/Parquet storage.

    Implementations are responsible for:
    - Managing the DuckDB connection and Parquet file discovery
    - Translating LakeQueryCriteria into SQL
    - Returning tidy DataFrames + pre-computed stats

    This interface intentionally mirrors AbstractMetadataService but
    operates on pre-ingested level-by-level data rather than index records.
    """

    @abstractmethod
    def query(self, criteria: LakeQueryCriteria) -> LakeQueryResult:
        """Query the data lake and return matching measurements.

        Args:
            criteria: Structured query criteria.

        Returns:
            LakeQueryResult containing the tidy DataFrame and aggregates.
            Returns an empty (but valid) result when no matches found.
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the data lake is ready to serve queries.

        Returns False when the lake has not been built or is inaccessible.
        """
        ...

    @abstractmethod
    def get_region_tag(self, lat: float, lon: float) -> str | None:
        """Return the canonical region tag for a coordinate pair.

        Args:
            lat: Latitude in degrees.
            lon: Longitude in degrees.

        Returns:
            ``"arabian_sea"``, ``"bay_of_bengal"``, or ``None`` if outside
            the Indian Ocean region coverage.
        """
        ...

    @abstractmethod
    def list_available_years(self) -> list[int]:
        """Return sorted list of years with data in the lake."""
        ...

    @abstractmethod
    def get_map_markers(self, criteria: LakeQueryCriteria) -> list[dict[str, Any]]:
        """Return all unique float locations matching criteria for map markers."""
        ...

    @abstractmethod
    def get_stats(self, criteria: LakeQueryCriteria) -> dict[str, Any]:
        """Compute and return statistics for the given criteria.

        This is a convenience wrapper that calls query() and extracts stats.
        """
        ...
