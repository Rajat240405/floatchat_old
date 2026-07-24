"""Shared internal helpers for the QueryEngine execution layer.

Extracted verbatim from the pre-M4 ``query_engine/engine.py`` monolith
(Milestone 4 decomposition). These functions are engine-internal utilities
(alive-window construction, profiler/manufacturer resolution, GDAC path
extraction, figure metrics, and the float-by-variable filter) shared by the
executor modules. Not part of the public API.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta
from typing import Any

import pandas as pd

from floatchat.config import settings
from floatchat.models import ParsedIntent

logger = logging.getLogger(__name__)


def _figure_metrics(figures: list[dict[str, Any]] | None) -> tuple[int, int, int]:
    """Return trace count, plotted point count, and compact JSON bytes."""
    traces = 0
    points = 0
    payload = 0
    for figure in figures or []:
        data = figure.get("data", []) or []
        traces += len(data)
        for trace in data:
            if not isinstance(trace, dict):
                continue
            points += max(len(trace.get("x", []) or []), len(trace.get("y", []) or []))
        payload += len(json.dumps(figure, separators=(",", ":")).encode("utf-8"))
    return traces, points, payload


_PROFILER_MFR_MAP: dict[str, str] = {
    "831": "Teledyne Webb",
    "832": "Teledyne Webb",
    "833": "Teledyne Webb",
    "834": "Teledyne Webb",
    "835": "Teledyne Webb",
    "836": "Teledyne CARAIBE",
    "837": "Teledyne CARAIBE",
    "838": "Teledyne CARAIBE",
    "839": "Teledyne CARAIBE",
    "840": "Teledyne CARAIBE",
    "841": "Teledyne CARAIBE",
    "842": "Teledyne CARAIBE",
    "843": "Teledyne CARAIBE",
    "844": "Teledyne CARAIBE",
    "845": "Teledyne Webb",
    "846": "Tsurumi Seiki",
    "847": "Tsurumi Seiki",
    "848": "Nortek",
    "849": "Nortek",
    "850": "Scripps/Floats Inc.",
    "851": "Scripps/Floats Inc.",
    "852": "Scripps/Floats Inc.",
    "853": "Scripps/Floats Inc.",
    "854": "Scripps/Floats Inc.",
    "860": "Teledyne CARAIBE",
    "861": "Teledyne CARAIBE",
    "862": "Teledyne CARAIBE",
    "863": "Teledyne CARAIBE",
    "864": "Teledyne CARAIBE",
}


def _resolve_manufacturer(profiler_type: str | None) -> str | None:
    """Phase 5 Part A: Resolve manufacturer name from profiler type code."""
    if not profiler_type:
        return None
    code = str(profiler_type).strip()
    return _PROFILER_MFR_MAP.get(code)


_FLOAT_ID_RE = re.compile(r"/([\d]{7,})/")


def _build_alive_window(intent: ParsedIntent) -> tuple[str | None, str | None]:
    """P3 #2: Build the [start, end] date window for 'alive' filtering.

    Semantics (confirmed):
      - If a period is derivable from intent.year/month/month_window: floats
        must have >=1 profile WITHIN that period.
      - If no period (year is None): "currently alive" = >=1 profile in the last
        `settings.alive_recent_months` months.
    Returns (start_iso, end_iso); each None if the window cannot be built.
    """
    from dateutil.relativedelta import relativedelta  # type: ignore[import-not-found]

    # Priority 1: explicit date range from LLM temporal resolution (most precise).
    # e.g. "summer" -> temporal_date_start="2026-03-01", temporal_date_end="2026-05-31".
    # This MUST be checked before year/month derivation, otherwise the LLM's
    # precise season resolution gets overwritten by a coarse year-only window.
    if intent.temporal_date_start and intent.temporal_date_end:
        return intent.temporal_date_start, intent.temporal_date_end

    # Priority 2: derive from year + month/month_window (deterministic parser).
    if intent.year is not None:
        mw = getattr(intent, "month_window", None)
        if mw:
            months_sorted = sorted(set(int(m) for m in mw if 1 <= int(m) <= 12))
            start_m, end_m = months_sorted[0], months_sorted[-1]
            start = date(intent.year, start_m, 1)
            # End of end_m
            if end_m == 12:
                end = date(intent.year, 12, 31)
            else:
                end = date(intent.year, end_m + 1, 1) - timedelta(days=1)
        elif intent.month is not None:
            start = date(intent.year, intent.month, 1)
            if intent.month == 12:
                end = date(intent.year, 12, 31)
            else:
                end = date(intent.year, intent.month + 1, 1) - timedelta(days=1)
        else:
            # Whole year
            start = date(intent.year, 1, 1)
            end = date(intent.year, 12, 31)
        return start.isoformat(), end.isoformat()

    # No period -> currently alive = last N months
    n_months = settings.alive_recent_months
    today = date.today()
    start = today - relativedelta(months=n_months)
    return start.isoformat(), today.isoformat()


def _extract_float_id_from_path(file_path: str) -> str:
    """Extract the 7-digit WMO float ID from a GDAC relative path."""
    match = _FLOAT_ID_RE.search(file_path)
    return match.group(1) if match else "unknown"


def _extract_float_cycle_key(file_path: str) -> tuple[str, str]:
    """Extract (float_id, cycle) key from a GDAC file path for pairing (Phase 24)."""
    _cyc_re = re.compile(r"_(\d{3})\.nc")
    fid = _FLOAT_ID_RE.search(file_path)
    cyc = _cyc_re.search(file_path)
    return (fid.group(1) if fid else "", cyc.group(1) if cyc else "")


def _extract_cycle_from_filename(file_name: str) -> int | None:
    """Extract the cycle number from a GDAC filename (``_NNN[D].nc`` suffix).

    Shared by the trajectory executor and the record-based map builder
    (Milestone 4 deduplication of an identical inline regex idiom).
    """
    match = re.search(r"_(\d{1,4})[D]?\.nc$", file_name)
    return int(match.group(1)) if match else None


def _filter_floats_by_variable(
    df: pd.DataFrame,
    lake: Any,
    variables: list[str],
) -> pd.DataFrame:
    """Filter a DataFrame of floats to only those with the requested variables.

    Checks two sources:
    1. float_registry.sensors column (sensor list like "CTD, OPTODE, NITRATE_SENSOR")
    2. levels table (actual measurement presence for TEMP/PSAL/DOXY/CHLA)

    A float passes if ANY of the requested variables is found in either source.
    """
    if df.empty or not variables:
        return df

    # Build a set of variable keywords to search for in the sensors column
    _VAR_SENSOR_MAP = {
        "TEMP": ["CTD", "TEMP", "SST"],
        "PSAL": ["CTD", "PSAL", "SALINITY"],
        "DOXY": ["OPTODE", "DOXY", "OXYGEN", "AANDERAA"],
        "CHLA": ["FLUOROMETER", "CHLA", "CHLOROPHYLL", "ECO"],
        "NITRATE": ["NITRATE", "SUNA", "ISUS", "ISUS_NITRATE"],
        "BBP700": ["BACKSCATTER", "BBP", "ECO", "FLBBCD"],
        "PH_IN_SITU_TOTAL": ["PH", "SBE_PH"],
        "DOWNWELLING_PAR": ["PAR", "RADIOMETER", "OCR"],
    }

    float_ids = df["float_id"].astype(str).tolist()

    # Check 1: float_registry sensors column
    fr_df = None
    if hasattr(lake, "get_float_registry"):
        try:
            fr_df = lake.get_float_registry()
        except Exception:
            pass

    # Build set of float_ids that have the requested variable
    qualified_ids: set[str] = set()

    if fr_df is not None and not fr_df.empty and "sensors" in fr_df.columns:
        for _, row in fr_df.iterrows():
            fid = str(row["float_id"])
            if fid not in [str(f) for f in float_ids]:
                continue
            sensors_raw = str(row.get("sensors", "")).upper()
            for var in variables:
                var_upper = var.upper()
                keywords = _VAR_SENSOR_MAP.get(var_upper, [var_upper])
                if any(kw in sensors_raw for kw in keywords):
                    qualified_ids.add(fid)
                    break

    # Check 2: levels table — for variables we have columns for (TEMP/PSAL/DOXY/CHLA)
    _LAKE_VAR_COLS = {"TEMP", "PSAL", "DOXY", "CHLA"}
    vars_to_check_in_levels = [v.upper() for v in variables if v.upper() in _LAKE_VAR_COLS]
    if vars_to_check_in_levels and hasattr(lake, "_lake_root") and lake._lake_root.exists():
        try:
            from floatchat.data_lake.base import LakeQueryCriteria
            conn = lake._get_connection()
            parquet_pattern = (lake._lake_root / "**" / "*.parquet").as_posix()
            placeholders = ", ".join("?" for _ in float_ids[:100])  # cap at 100 for SQL safety
            for var in vars_to_check_in_levels:
                adj_col = f"{var.lower()}_adjusted"
                raw_col = var.lower()
                sql = (
                    f"SELECT DISTINCT CAST(float_id AS VARCHAR) AS float_id "
                    f"FROM read_parquet('{parquet_pattern}', hive_partitioning=true) "
                    f"WHERE CAST(float_id AS VARCHAR) IN ({placeholders}) "
                    f"AND (({adj_col} IS NOT NULL AND NOT isnan({adj_col})) "
                    f"OR ({raw_col} IS NOT NULL AND NOT isnan({raw_col})))"
                )
                result = conn.execute(sql, [str(f) for f in float_ids[:100]]).fetchall()
                for row in result:
                    qualified_ids.add(str(row[0]))
        except Exception as exc:
            logger.warning("Levels variable check failed: %s", exc)

    # Apply filter
    if qualified_ids:
        mask = df["float_id"].astype(str).isin(qualified_ids)
        return df[mask].reset_index(drop=True)
    else:
        # No floats qualified — return empty
        return df.iloc[0:0]
