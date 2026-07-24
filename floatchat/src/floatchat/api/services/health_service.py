"""Health application service — runtime readiness reporting.

Cleanup M3 (API layer decomposition): the lake-readiness probe was moved
verbatim from ``api/main.py``; the payload shape returned by GET /health is
unchanged.
"""

import logging

from floatchat.config import settings

logger = logging.getLogger(__name__)


def runtime_lake_readiness() -> dict[str, bool]:
    """Report DuckDB/Parquet readiness without loading GDAC metadata."""
    try:
        from floatchat.api.dependencies import get_data_lake

        lake = get_data_lake()
        levels_ready = lake.is_available()
        phase2_root = getattr(lake, "_phase2_root", None)
        profile_index_ready = bool(
            phase2_root
            and (phase2_root / "parquet" / "profile_index").exists()
        )
        float_registry_ready = bool(
            phase2_root
            and (phase2_root / "parquet" / "float_registry").exists()
        )
        return {
            "duckdb_ready": levels_ready,
            "float_registry_ready": float_registry_ready,
            "profile_index_ready": profile_index_ready,
            "levels_ready": levels_ready,
        }
    except Exception as exc:
        logger.warning("Runtime lake readiness check failed: %s", exc)
        return {
            "duckdb_ready": False,
            "float_registry_ready": False,
            "profile_index_ready": False,
            "levels_ready": False,
        }


def build_health_payload() -> dict:
    """Return the exact GET /health response body (shape unchanged)."""
    readiness = runtime_lake_readiness()
    return {
        "status": "ok" if readiness["duckdb_ready"] else "degraded",
        **readiness,
        "gdac_runtime_enabled": settings.enable_gdac_runtime,
    }
