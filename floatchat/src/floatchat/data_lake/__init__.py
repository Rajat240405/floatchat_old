"""Local Data Lake — DuckDB/Parquet-backed Argo profile storage.

Phase 1: Walking skeleton for India-region Argo data queries.
"""
from floatchat.data_lake.base import (
    AbstractDataLake,
    LakeQueryResult,
)
from floatchat.data_lake.duckdb_lake import DuckDBDataLake

__all__ = [
    "AbstractDataLake",
    "LakeQueryResult",
    "DuckDBDataLake",
]
