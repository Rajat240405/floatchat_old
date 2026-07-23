"""Query Engine orchestrator.

Maps :class:`ParsedIntent` through the full pipeline and returns a
:class:`ChatResponse`.

Priority 1A: ALL data intents now route EXCLUSIVELY through DuckDBDataLake.
The legacy GDAC pipeline (RetrievalPlanner → metadata_service → repository_service
→ live NetCDF downloads) is ONLY accessible when
FLOATCHAT_ALLOW_REMOTE_GDAC_FALLBACK=True (default: False).
"""

import logging
import math
import dataclasses
from datetime import date, timedelta
from pathlib import Path
import re
import time
from typing import TYPE_CHECKING, Any

import pandas as pd

from floatchat.config import settings
from floatchat.exceptions import FloatChatError
from floatchat.metadata_service.base import AbstractMetadataService
from floatchat.models import ChatResponse, MapData, ParsedIntent, SearchCriteria
from floatchat.netcdf_reader.base import AbstractNetCDFReader
from floatchat.repository_service.base import AbstractRepositoryService
from floatchat.retrieval_planner.planner import RetrievalPlanner
from floatchat.scientific_explanation.engine import ScientificExplanationEngine
from floatchat.scientific_explanation.verification import (
    build_pipeline_trace,
    build_verification_section,
)
from floatchat.variable_registry.registry import VariableRegistry
from floatchat.visualization_engine.base import AbstractVisualizationEngine

if TYPE_CHECKING:
    from floatchat.data_lake.base import AbstractDataLake

logger = logging.getLogger(__name__)

# All data intents that MUST go through the local data lake
_DATA_INTENTS = frozenset({
    "region_search",
    "profile_plot",
    "time_series",
    "trajectory",
    "hovmoller",
    "ts_diagram",
    "comparison",
    "comparison_plot",
    "nearest_float",
    "radius_search",
    "count_aggregate",
    "metadata_lookup",
})

# Phase 5 Part A: Profiler code → Manufacturer mapping (Argo Reference Table 8)
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


# Extract WMO float ID from GDAC file path: dac/<dac>/<float_id>/profiles/...
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


class QueryEngine:
    """Orchestrates the data retrieval and visualization pipeline.

    Priority 1A: All data intents route through DuckDBDataLake by default.
    The legacy GDAC pipeline is only used when FLOATCHAT_ALLOW_REMOTE_GDAC_FALLBACK=True.
    """

    def __init__(
        self,
        metadata_service: AbstractMetadataService,
        repository_service: AbstractRepositoryService,
        netcdf_reader: AbstractNetCDFReader,
        visualization_engine: AbstractVisualizationEngine,
        explanation_engine: ScientificExplanationEngine | None = None,
    ) -> None:
        self.metadata = metadata_service
        self.repository = repository_service
        self.reader = netcdf_reader
        self.viz = visualization_engine
        self.explanation_engine = (
            explanation_engine if explanation_engine is not None else ScientificExplanationEngine()
        )
        self.planner = RetrievalPlanner()
        # Phase 1: Optional data lake (lazy import to avoid hard dependency)
        self._data_lake: AbstractDataLake | None = None

    def execute(self, intent: ParsedIntent) -> ChatResponse:
        """Run the full pipeline for a single parsed intent.

        Priority 1A: ALL data intents go through the local data lake.
        No GDAC HTTP calls are made unless FLOATCHAT_ALLOW_REMOTE_GDAC_FALLBACK=True.
        """
        pipeline_t0 = time.perf_counter()

        # --- Phase 26: India-only Deployment Gate --- #
        if settings.deployment_mode == "INDIA_ONLY":
            supported_india_regions = {"arabian_sea", "bay_of_bengal"}
            if intent.region and intent.region not in supported_india_regions:
                return ChatResponse(
                    intent=intent.intent,
                    message=(
                        f"Region '{intent.region}' is not supported in the current "
                        "deployment mode. Please request data for the Arabian Sea or Bay of Bengal."
                    ),
                    data_summary={"matched_records": 0},
                )

        # --- Priority 1A: Route ALL data intents through local data lake --- #
        if intent.intent in _DATA_INTENTS:
            return self._execute_via_data_lake_or_explain(intent, pipeline_t0)

        # Non-data intents fall through (small_talk, knowledge_base, etc.)
        logger.warning("Non-data intent reached execute(): %s", intent.intent)
        return ChatResponse(
            intent=intent.intent,
            message="This query type is not handled by the data pipeline.",
            data_summary={"matched_records": 0},
        )

    # --------------------------------------------------------------------- #
    # Priority 1A: Unified local-only data path
    # --------------------------------------------------------------------- #

    def _execute_via_data_lake_or_explain(
        self, intent: ParsedIntent, pipeline_t0: float
    ) -> ChatResponse:
        """Route a data intent through the local DuckDB data lake.

        If the data lake is unavailable and FLOATCHAT_ALLOW_REMOTE_GDAC_FALLBACK
        is True, falls back to the legacy GDAC pipeline. Otherwise returns a
        clear explanation that the data lake is required.
        """
        lake = self._get_data_lake()

        # Route intent to the appropriate handler
        if intent.intent == "nearest_float":
            return self._execute_nearest_float(intent, pipeline_t0)
        if intent.intent == "radius_search":
            return self._execute_radius_search(intent, pipeline_t0)
        if intent.intent == "metadata_lookup":
            return self._execute_metadata_lookup(intent, pipeline_t0)
        if intent.intent == "count_aggregate":
            return self._execute_count_aggregate(intent, pipeline_t0)
        if intent.intent == "trajectory":
            return self._execute_trajectory(intent, pipeline_t0)

        # All other data intents (region_search, profile_plot, time_series,
        # hovmoller, ts_diagram, comparison, comparison_plot) go via lake query
        return self._execute_data_query_via_lake(intent, pipeline_t0)

    # --------------------------------------------------------------------- #
    # Spatial & Metadata Intents (via local data lake only)
    # --------------------------------------------------------------------- #

    def _execute_nearest_float(self, intent: ParsedIntent, pipeline_t0: float) -> ChatResponse:
        lake = self._get_data_lake()
        if intent.lat is None or intent.lon is None:
            return ChatResponse(
                intent="nearest_float",
                message="Please provide latitude and longitude coordinates to find the nearest float.",
                data_summary={"matched_records": 0},
            )

        if lake and (lake.is_available() or lake.is_phase2_available()):
            df = lake.query_nearest_float(lat=intent.lat, lon=intent.lon, limit=intent.limit or 5)
            if not df.empty:
                map_data = []
                float_summaries = []
                for _, row in df.iterrows():
                    fid = str(row["float_id"])
                    dist = float(row.get("distance_km", 0.0))
                    status = str(row.get("status", "unknown"))
                    sensors = str(row.get("sensors", ""))
                    last_date = str(row.get("last_report_date", ""))[:10]
                    lat_val = float(row["lat"]) if pd.notna(row["lat"]) else 0.0
                    lon_val = float(row["lon"]) if pd.notna(row["lon"]) else 0.0

                    profiler_code = str(row.get("profiler_type", "")).strip()
                    mfr = _resolve_manufacturer(profiler_code)

                    map_data.append(
                        MapData(
                            float_id=fid,
                            latitude=lat_val,
                            longitude=lon_val,
                            profile_date=last_date if last_date else None,
                            dac=str(row.get("institution", "")),
                            variables=[s.strip() for s in sensors.split(",") if s.strip()] if sensors else [],
                            selected=False,
                            status=status,
                            manufacturer=mfr,
                            profiler_type=profiler_code if profiler_code else None,
                        )
                    )
                    float_summaries.append(f"• Float {fid}: {dist:.1f} km away (Status: {status}, Last report: {last_date or 'N/A'})")

                top_float = df.iloc[0]
                msg = (
                    f"Nearest float to ({intent.lat:.2f}, {intent.lon:.2f}) is Float {top_float['float_id']} "
                    f"at a distance of {top_float.get('distance_km', 0.0):.1f} km.\n\n"
                    f"Closest match(es):\n" + "\n".join(float_summaries[:5])
                )
                summary = {
                    "matched_records": len(df),
                    "nearest_float_id": str(top_float["float_id"]),
                    "distance_km": float(top_float.get("distance_km", 0.0)),
                    "target_coords": {"lat": intent.lat, "lon": intent.lon},
                }
                return ChatResponse(
                    intent="nearest_float",
                    message=msg,
                    figure=None,
                    data_summary=summary,
                    map_data=map_data,
                )

        # Priority 1A: No GDAC fallback — clear message
        return ChatResponse(
            intent="nearest_float",
            message=f"The local data lake is not available. Cannot search for floats near ({intent.lat:.2f}, {intent.lon:.2f}) without live downloads (disabled).",
            data_summary={"matched_records": 0},
        )

    def _execute_radius_search(self, intent: ParsedIntent, pipeline_t0: float) -> ChatResponse:
        lake = self._get_data_lake()
        # If user says "near arabian sea" but has region, no coordinates
        if (intent.lat is None or intent.lon is None) and intent.region:
            if lake and (lake.is_available() or lake.is_phase2_available()):
                try:
                    df = lake.get_profile_index(region=intent.region, limit=500)
                    if not df.empty:
                        latest = df.sort_values("date").groupby("float_id", as_index=False).last()
                        map_data = []
                        for _, row in latest.iterrows():
                            fid = str(row.get("float_id", ""))
                            lat_val = float(row.get("latitude", row.get("lat", 0)) or 0)
                            lon_val = float(row.get("longitude", row.get("lon", 0)) or 0)
                            if not lat_val or not lon_val:
                                continue
                            status = str(row.get("status", "unknown")) if "status" in row else "unknown"
                            map_data.append(
                                MapData(
                                    float_id=fid,
                                    latitude=lat_val,
                                    longitude=lon_val,
                                    profile_date=str(row.get("date", ""))[:10] if pd.notna(row.get("date")) else None,
                                    dac=str(row.get("dac", row.get("institution", "")) or ""),
                                    variables=[],
                                    selected=False,
                                    status=status,
                                )
                            )
                        msg = f"Found {len(map_data)} float(s) in {intent.region.replace('_',' ').title()} region."
                        return ChatResponse(
                            intent="radius_search",
                            message=msg,
                            figure=None,
                            data_summary={"matched_records": len(map_data), "region": intent.region},
                            map_data=map_data,
                        )
                except Exception as exc:
                    logger.warning("Region fallback for radius_search failed: %s", exc)
            return ChatResponse(
                intent="radius_search",
                message=f"Showing floats in {intent.region.replace('_',' ').title()} region. Data lake may not have coordinates, but {intent.region} filter applied.",
                data_summary={"matched_records": 0, "region": intent.region},
            )

        if intent.lat is None or intent.lon is None:
            return ChatResponse(
                intent="radius_search",
                message="Please provide latitude and longitude coordinates for radius search.",
                data_summary={"matched_records": 0},
            )

        radius_km = intent.radius_km if intent.radius_km is not None else 500.0
        radius_was_assumed = intent.radius_km is None

        # P3 #2: operational_filter='alive' — a float qualifies if it has
        # >=1 profile in profile_index within the requested period (or the last
        # `alive_recent_months` if no period given). Uses report dates, NOT
        # float_registry.status.
        alive_date_start, alive_date_end = None, None
        alive_filter = intent.operational_filter == "alive"
        if alive_filter:
            alive_date_start, alive_date_end = _build_alive_window(intent)

        # P3 #2/Q4: Log the effective execution parameters for debugging.
        logger.info(
            "Executing radius_search: center=(%.2f, %.2f) radius=%.0fkm "
            "alive=%s date_range=%s→%s depth_min=%s depth_max=%s",
            intent.lat, intent.lon, radius_km,
            alive_filter,
            alive_date_start or intent.temporal_date_start,
            alive_date_end or intent.temporal_date_end,
            intent.depth_min, intent.depth_max,
        )

        if lake and (lake.is_available() or lake.is_phase2_available()):
            df = lake.query_radius_search(
                lat=intent.lat, lon=intent.lon, radius_km=radius_km, limit=500,
                alive_date_start=alive_date_start, alive_date_end=alive_date_end,
            )

            # Variable filter: when the user asks for a specific variable
            # (e.g. "nitrate floats"), filter the radius results to only
            # include floats that actually HAVE that variable in the data lake.
            # Uses the float_registry sensors column + levels table check.
            if intent.variables and not df.empty:
                df = _filter_floats_by_variable(df, lake, intent.variables)
                logger.info(
                    "Variable-filtered radius search: %d floats after filtering by %s",
                    len(df), intent.variables,
                )

            map_data = []
            for _, row in df.iterrows():
                fid = str(row["float_id"])
                status = str(row.get("status", "unknown"))
                sensors = str(row.get("sensors", ""))
                last_date = str(row.get("last_report_date", ""))[:10]
                lat_val = float(row["lat"]) if pd.notna(row["lat"]) else 0.0
                lon_val = float(row["lon"]) if pd.notna(row["lon"]) else 0.0

                profiler_code = str(row.get("profiler_type", "")).strip()
                mfr = _resolve_manufacturer(profiler_code)

                map_data.append(
                    MapData(
                        float_id=fid,
                        latitude=lat_val,
                        longitude=lon_val,
                        profile_date=last_date if last_date else None,
                        dac=str(row.get("institution", "")),
                        variables=[s.strip() for s in sensors.split(",") if s.strip()] if sensors else [],
                        selected=False,
                        status=status,
                        manufacturer=mfr,
                        profiler_type=profiler_code if profiler_code else None,
                    )
                )

            count = len(df)
            # P3 #2: reflect alive filtering in the message.
            alive_note = ""
            if alive_filter:
                if intent.year is not None:
                    period_desc = f"{alive_date_start} to {alive_date_end}"
                    alive_note = f" (alive during {period_desc})"
                else:
                    alive_note = f" (currently alive: >=1 profile in the last {settings.alive_recent_months} months)"
            if radius_was_assumed:
                msg = (
                    f"Found {count} alive float(s){alive_note} within a {radius_km:.0f} km radius "
                    f"of ({intent.lat:.2f}, {intent.lon:.2f}).\n"
                    f"ℹ️ No distance specified — assumed {radius_km:.0f} km search radius."
                ) if alive_filter else (
                    f"Found {count} float(s) within a {radius_km:.0f} km radius of ({intent.lat:.2f}, {intent.lon:.2f}).\n"
                    f"ℹ️ No distance specified — assumed {radius_km:.0f} km search radius."
                )
            else:
                if alive_filter:
                    msg = f"Found {count} alive float(s){alive_note} within a {radius_km:.0f} km radius of ({intent.lat:.2f}, {intent.lon:.2f})."
                else:
                    msg = f"Found {count} float(s) within a {radius_km:.0f} km radius of ({intent.lat:.2f}, {intent.lon:.2f})."
            summary = {
                "matched_records": count,
                "radius_km": radius_km,
                "center": {"lat": intent.lat, "lon": intent.lon},
                "alive_filter": alive_filter,
                "alive_date_start": alive_date_start,
                "alive_date_end": alive_date_end,
            }
            return ChatResponse(
                intent="radius_search",
                message=msg,
                figure=None,
                data_summary=summary,
                map_data=map_data,
            )

        return ChatResponse(
            intent="radius_search",
            message=f"Radius search within {radius_km} km of ({intent.lat}, {intent.lon}). Local data lake is not available (remote GDAC is disabled).",
            data_summary={"matched_records": 0},
        )

    def _execute_metadata_lookup(self, intent: ParsedIntent, pipeline_t0: float) -> ChatResponse:
        """Priority 1A: metadata_lookup uses ONLY the local data lake.

        No GDAC metadata service fallback when FLOATCHAT_ALLOW_REMOTE_GDAC_FALLBACK=False.
        """
        lake = self._get_data_lake()
        float_id = intent.float_id

        if not float_id:
            return ChatResponse(
                intent="metadata_lookup",
                message="Please specify a float ID to look up metadata.",
                data_summary={"matched_records": 0},
            )

        info = lake.query_metadata_lookup(float_id) if lake else {"found": False, "float_id": float_id}

        # Priority 1A: GDAC supplement/fallback — ONLY when explicitly allowed
        _needs_gdac = (
            not info.get("found")
            or not info.get("profiler_type")
            or str(info.get("profiler_type", "")).strip() in ("", "unknown", "None")
            or not info.get("institution")
            or str(info.get("institution", "")).strip() in ("", "unknown", "None")
        )
        if _needs_gdac and self.metadata and settings.allow_remote_gdac_fallback:
            logger.warning(
                "GDAC metadata fallback triggered for float %s — "
                "this is a remote HTTP call. Set FLOATCHAT_ALLOW_REMOTE_GDAC_FALLBACK=False to prevent.",
                float_id,
            )
            try:
                records = self.metadata.search(SearchCriteria(float_id=float_id, limit=2000))
                if records:
                    _supplement = info.get("found", False)

                    if not _supplement:
                        info["found"] = True
                        info["float_id"] = str(float_id)
                        info["profile_count"] = len(records)

                    records_sorted = sorted(records, key=lambda r: r.date)

                    if not info.get("first_profile_date"):
                        info["first_profile_date"] = records_sorted[0].date.strftime("%Y-%m-%d")
                    if not info.get("last_report_date"):
                        info["last_report_date"] = records_sorted[-1].date.strftime("%Y-%m-%d")

                    latest = records_sorted[-1]
                    if info.get("last_lat") is None:
                        info["last_lat"] = latest.latitude
                    if info.get("last_lon") is None:
                        info["last_lon"] = latest.longitude
                    
                    if not info.get("institution") or str(info.get("institution", "")).strip() in ("", "unknown", "None"):
                        dac_code = str(latest.institution).strip().upper()
                        DAC_MAP = {
                            "IF": "IFREMER (Coriolis)",
                            "IN": "INCOIS (India)",
                            "AO": "AOML (NOAA)",
                            "JM": "JMA (Japan)",
                            "CS": "CSIRO (Australia)",
                            "KM": "KORDI / KMA (Korea)",
                            "BO": "BODC (UK)",
                            "HZ": "CSIO (China)",
                        }
                        info["institution"] = DAC_MAP.get(dac_code, latest.institution or "unknown")

                    if not info.get("profiler_type") or str(info.get("profiler_type", "")).strip() in ("", "unknown", "None"):
                        info["profiler_type"] = latest.profiler_type

                    code_str = str(info.get("profiler_type", "")).strip()
                    PROFILER_MAP = {
                        "836": "PROVOR CTS4",
                        "837": "PROVOR CTS5",
                        "841": "PROVOR",
                        "842": "PROVOR",
                        "831": "APEX",
                        "832": "APEX",
                        "845": "NAVIS",
                        "851": "SOLO",
                        "861": "ARVOR",
                        "862": "ARVOR",
                    }
                    if code_str in PROFILER_MAP and info.get("platform_type") in (None, "unknown", ""):
                        info["platform_type"] = PROFILER_MAP[code_str]

                    if not info.get("manufacturer") or str(info.get("manufacturer", "")).strip() in ("", "unknown", "None"):
                        mfr = _resolve_manufacturer(code_str)
                        info["manufacturer"] = mfr if mfr else "unknown"

                    if not info.get("sensors") or info.get("sensors") == []:
                        all_params = set()
                        for r in records:
                            if r.parameters:
                                for p in r.parameters.split():
                                    all_params.add(p.upper())

                        sensors = []
                        if "TEMP" in all_params or "PRES" in all_params or "PSAL" in all_params:
                            sensors.append("CTD")
                        if "DOXY" in all_params or "DOXY_ADJUSTED" in all_params:
                            sensors.append("OPTODE")
                        if "CHLA" in all_params or "CHLA_ADJUSTED" in all_params:
                            sensors.append("FLUOROMETER")
                        if any("NITRATE" in p for p in all_params):
                            sensors.append("NITRATE_SENSOR")
                        if any("BBP" in p for p in all_params):
                            sensors.append("BACKSCATTER")
                        info["sensors"] = sensors if sensors else ["CTD"]

                    if info.get("status") in (None, "unknown", ""):
                        from datetime import datetime, timezone
                        ref_now = datetime.now(timezone.utc)
                        last_dt = records_sorted[-1].date
                        if hasattr(last_dt, "tzinfo") and last_dt.tzinfo is None:
                            last_dt = last_dt.replace(tzinfo=timezone.utc)
                        days_diff = (ref_now - last_dt).days
                        info["status"] = "active" if days_diff <= 365 else "inactive"

                    from floatchat.data_lake.duckdb_lake import DuckDBDataLake
                    battery_info = DuckDBDataLake._estimate_battery_status(
                        profile_count=info["profile_count"],
                        first_profile_date=info.get("first_profile_date"),
                        last_report_date=info.get("last_report_date"),
                        status=info["status"],
                        profiler_type=info.get("profiler_type"),
                    )
                    info["battery_voltage"] = battery_info["battery_voltage"]
                    info["battery_percentage"] = battery_info["battery_percentage"]
                    info["battery_status"] = battery_info["battery_status"]
                    info["battery_note"] = battery_info["battery_note"]
            except Exception as exc:
                logger.warning("GDAC metadata fallback failed for float %s: %s", float_id, exc)

        # If float not found anywhere, return clear message
        if not info.get("found"):
            return ChatResponse(
                intent="metadata_lookup",
                message=f"Float {float_id} was not found in the local data lake. "
                        "Remote GDAC lookup is disabled (FLOATCHAT_ALLOW_REMOTE_GDAC_FALLBACK=False).",
                data_summary={"matched_records": 0, "float_id": float_id},
            )

        map_data = []
        if info.get("last_lat") is not None and info.get("last_lon") is not None:
            map_data.append(
                MapData(
                    float_id=str(float_id),
                    latitude=float(info["last_lat"]),
                    longitude=float(info["last_lon"]),
                    profile_date=info.get("last_report_date"),
                    dac=info.get("institution", "unknown"),
                    variables=info.get("sensors", []),
                    selected=True,
                    status=info.get("status", "unknown"),
                )
            )

        sensors_str = ", ".join(info.get("sensors", [])) or "Standard CTD (Temperature, Salinity, Pressure)"
        
        manufacturer = info.get("manufacturer", "unknown")
        mfr_str = manufacturer if manufacturer and manufacturer != "unknown" else "N/A"
        
        battery_pct = info.get("battery_percentage")
        battery_v = info.get("battery_voltage")
        battery_status = info.get("battery_status", "Unknown")
        if battery_pct is not None and battery_v is not None:
            battery_str = f"{battery_v}V (~{battery_pct}%) — {battery_status}"
        elif battery_v is not None:
            battery_str = f"{battery_v}V — {battery_status}"
        else:
            battery_str = battery_status
        
        msg = (
            f"Registry metadata for Argo Float {float_id}:\n"
            f"• Status: {info.get('status', 'unknown').capitalize()}\n"
            f"• Manufacturer: {mfr_str}\n"
            f"• Sensors: {sensors_str}\n"
            f"• First Profile: {info.get('first_profile_date') or 'N/A'}\n"
            f"• Last Report: {info.get('last_report_date') or 'N/A'}\n"
            f"• Profile Count: {info.get('profile_count', 0)}\n"
            f"• DAC / Institution: {info.get('institution', 'N/A').upper()}\n"
            f"• Platform / Profiler Type: {info.get('platform_type', 'N/A')} / {info.get('profiler_type', 'N/A')}\n"
            f"• Battery: {battery_str}"
        )

        return ChatResponse(
            intent="metadata_lookup",
            message=msg,
            figure=None,
            data_summary={
                "matched_records": info.get("profile_count", 0),
                "float_info": info,
            },
            map_data=map_data,
        )

    def _execute_count_aggregate(self, intent: ParsedIntent, pipeline_t0: float) -> ChatResponse:
        lake = self._get_data_lake()

        # Handle spatial count queries like "oxygen data near Mumbai"
        if intent.lat is not None and intent.lon is not None:
            radius_km = intent.radius_km or 500.0
            if lake and (lake.is_available() or lake.is_phase2_available()):
                try:
                    df = lake.query_radius_search(lat=intent.lat, lon=intent.lon, radius_km=radius_km, limit=500)
                    tot_f = len(df)
                    if intent.variables and hasattr(lake, 'query_count_aggregate'):
                        float_ids = df["float_id"].astype(str).tolist() if not df.empty else []
                        tot_p = 0
                        if float_ids:
                            try:
                                tot_p = 0
                                for fid in float_ids[:20]:
                                    s = lake.query_count_aggregate(
                                        float_id=fid,
                                        variables=intent.variables,
                                    )
                                    tot_p += s.get("total_profiles", 0)
                                if tot_p == 0 and tot_f > 0:
                                    tot_p = tot_f
                            except Exception:
                                tot_p = tot_f
                        else:
                            tot_p = 0
                    else:
                        tot_p = tot_f

                    location_desc = f"within {radius_km:.0f} km of ({intent.lat:.2f}, {intent.lon:.2f})"
                    if intent.region:
                        location_desc = f"{intent.region.replace('_',' ').title()} ({location_desc})"

                    var_desc = f" for {', '.join(intent.variables)}" if intent.variables else ""
                    time_desc = f" in {intent.year}" if intent.year else ""

                    if intent.existence_check:
                        if tot_f > 0:
                            msg = f"Yes, Argo profile data exists {location_desc}{var_desc}{time_desc}. Found {tot_f} float(s) within radius, with approx {tot_p} profile(s)."
                        else:
                            msg = f"No profile data found in the lake {location_desc}{var_desc}{time_desc}."
                    else:
                        msg = f"Data count {location_desc}{var_desc}{time_desc}: {tot_f} float(s) / ~{tot_p} profile(s) within radius."

                    map_data = []
                    for _, row in df.iterrows():
                        try:
                            fid = str(row["float_id"])
                            lat_val = float(row["lat"]) if pd.notna(row["lat"]) else None
                            lon_val = float(row["lon"]) if pd.notna(row["lon"]) else None
                            if lat_val is None or lon_val is None:
                                continue
                            map_data.append(
                                MapData(
                                    float_id=fid,
                                    latitude=lat_val,
                                    longitude=lon_val,
                                    profile_date=str(row.get("last_report_date", ""))[:10] if pd.notna(row.get("last_report_date")) else None,
                                    dac=str(row.get("institution", "")),
                                    variables=intent.variables or [],
                                    selected=False,
                                    status=str(row.get("status", "unknown")),
                                )
                            )
                        except Exception:
                            continue

                    summary = {
                        "matched_records": tot_p,
                        "unique_floats": tot_f,
                        "existence": tot_f > 0,
                        "center": {"lat": intent.lat, "lon": intent.lon},
                        "radius_km": radius_km,
                    }
                    return ChatResponse(
                        intent="count_aggregate",
                        message=msg,
                        figure=None,
                        data_summary=summary,
                        map_data=map_data,
                    )
                except Exception as exc:
                    logger.warning("Spatial count aggregate failed: %s", exc)

        # Fallback to original region/year/float counting
        stats = lake.query_count_aggregate(
            region=intent.region,
            year=intent.year,
            month=intent.month,
            months=getattr(intent, "month_window", None),  # P3 #3: season window
            float_id=intent.float_id,
            variables=intent.variables,
        ) if lake else {"total_profiles": 0, "total_floats": 0, "has_data": False}

        tot_p = stats.get("total_profiles", 0)
        tot_f = stats.get("total_floats", 0)

        location_desc = intent.region.replace("_", " ").title() if intent.region else (f"Float {intent.float_id}" if intent.float_id else "India Region")
        time_desc = f" in {intent.year}" if intent.year else ""
        var_desc = f" for {', '.join(intent.variables)}" if intent.variables else ""

        if intent.existence_check:
            if tot_p > 0:
                msg = f"Yes, Argo profile data exists for {location_desc}{var_desc}{time_desc}. Found {tot_p:,} profile(s) collected by {tot_f:,} float(s)."
            else:
                # Priority 1D: Provide availability explanation
                if lake and intent.variables:
                    from floatchat.data_lake.base import LakeQueryCriteria
                    msg = lake.build_zero_result_message(
                        LakeQueryCriteria(
                            region=intent.region,
                            year=intent.year,
                            variables=intent.variables,
                        )
                    )
                else:
                    msg = f"No profile data found in the lake for {location_desc}{var_desc}{time_desc}."
        else:
            msg = f"Data count for {location_desc}{var_desc}{time_desc}: {tot_p:,} total profile(s) across {tot_f:,} unique float(s)."

        summary = {
            "matched_records": tot_p,
            "unique_floats": tot_f,
            "existence": tot_p > 0,
            "date_range": {
                "min": stats.get("min_date"),
                "max": stats.get("max_date"),
            },
        }

        return ChatResponse(
            intent="count_aggregate",
            message=msg,
            figure=None,
            data_summary=summary,
            map_data=[],
        )

    def _execute_trajectory(self, intent: ParsedIntent, pipeline_t0: float) -> ChatResponse:
        """Execute trajectory query returning coordinate history across float cycles.
        
        Priority 1A: Uses ONLY local data lake. No GDAC fallback unless allowed.
        """
        float_id = intent.float_id
        if not float_id:
            return ChatResponse(
                intent="trajectory",
                message="Please specify a float ID to view its trajectory history.",
                data_summary={"matched_records": 0},
            )

        clean_fid = str(float_id).strip()
        lake = self._get_data_lake()
        df = pd.DataFrame()

        if lake and (lake.is_available() or lake.is_phase2_available()):
            if hasattr(lake, "get_profile_index"):
                df = lake.get_profile_index(float_id=clean_fid, limit=50000)
            if df.empty and hasattr(lake, "_lake_root") and lake._lake_root.exists():
                try:
                    conn = lake._get_connection()
                    pi_path = (
                        (lake._phase2_root / "parquet" / "profile_index" / "**" / "*.parquet").as_posix()
                        if lake._phase2_root and (lake._phase2_root / "parquet" / "profile_index").exists()
                        else (lake._lake_root / "**" / "*.parquet").as_posix()
                    )
                    # Support BOTH schemas: lat/lon (Phase2) and latitude/longitude (legacy)
                    lat_col = "lat" if "lat" in str(pi_path).lower() or True else "latitude"  # prefer lat
                    lon_col = "lon" if "lon" in str(pi_path).lower() or True else "longitude"
                    # Determine actual column names present in parquet
                    try:
                        sample = conn.execute(f"SELECT * FROM read_parquet('{pi_path}', hive_partitioning=true) LIMIT 1").fetchdf()
                        cols = [c.lower() for c in sample.columns]
                        lat_col = "lat" if "lat" in cols else ("latitude" if "latitude" in cols else "lat")
                        lon_col = "lon" if "lon" in cols else ("longitude" if "longitude" in cols else "lon")
                    except Exception:
                        lat_col = "lat"
                        lon_col = "lon"

                    sql = f"SELECT CAST(float_id AS VARCHAR) AS float_id, date, arg_max({lat_col}, date) AS lat, arg_max({lon_col}, date) AS lon, COALESCE(arg_max(dac, date), '') AS dac FROM read_parquet('{pi_path}', hive_partitioning=true) WHERE CAST(float_id AS VARCHAR) = ? GROUP BY float_id, date ORDER BY date ASC"
                    df = conn.execute(sql, [clean_fid]).fetchdf()
                except Exception as exc:
                    logger.warning("Trajectory lake query failed: %s", exc)

        # Priority 1A: GDAC fallback ONLY when explicitly allowed
        if df.empty and self.metadata and settings.allow_remote_gdac_fallback:
            logger.warning(
                "GDAC trajectory fallback triggered for float %s — remote HTTP call.",
                clean_fid,
            )
            try:
                records = self.metadata.search(SearchCriteria(float_id=clean_fid, limit=2000))
                if records:
                    records_sorted = sorted(records, key=lambda r: r.date)
                    df = pd.DataFrame(
                        [
                            {
                                "float_id": clean_fid,
                                "date": r.date,
                                "lat": r.latitude,
                                "lon": r.longitude,
                                "dac": r.institution or "",
                            }
                            for r in records_sorted
                        ]
                    )
            except Exception as exc:
                logger.warning("Trajectory GDAC fallback failed: %s", exc)

        if df.empty:
            return ChatResponse(
                intent="trajectory",
                message=f"No trajectory coordinates found for Float {clean_fid} in the local data lake.",
                data_summary={"matched_records": 0},
            )

        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.sort_values("date", ascending=True)

        total_dist_km = 0.0
        lat_col = "lat" if "lat" in df.columns else "latitude"
        lon_col = "lon" if "lon" in df.columns else "longitude"
        lats = df[lat_col].dropna().values
        lons = df[lon_col].dropna().values
        for i in range(len(lats) - 1):
            lat1, lon1 = float(lats[i]), float(lons[i])
            lat2, lon2 = float(lats[i + 1]), float(lons[i + 1])
            if math.isfinite(lat1) and math.isfinite(lon1) and math.isfinite(lat2) and math.isfinite(lon2):
                dlat = math.radians(lat2 - lat1)
                dlon = math.radians(lon2 - lon1)
                a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
                c = 2 * math.asin(math.sqrt(max(0.0, min(1.0, a))))
                total_dist_km += 6371.0 * c

        map_data = []
        for idx_count, (i, row) in enumerate(df.iterrows()):
            lat_val = float(row[lat_col]) if pd.notna(row.get(lat_col)) else None
            lon_val = float(row[lon_col]) if pd.notna(row.get(lon_col)) else None
            if lat_val is None or lon_val is None or not math.isfinite(lat_val) or not math.isfinite(lon_val):
                continue
            date_val = str(row["date"])[:10] if "date" in df.columns and pd.notna(row.get("date")) and str(row.get("date")) != "NaT" else None
            p_num = None
            if "cycle_number" in df.columns and pd.notna(row.get("cycle_number")):
                try:
                    p_num = int(row["cycle_number"])
                except Exception:
                    pass
            elif "profile_number" in df.columns and pd.notna(row.get("profile_number")):
                try:
                    p_num = int(row["profile_number"])
                except Exception:
                    pass
            if p_num is None and "file" in df.columns and pd.notna(row.get("file")):
                m = re.search(r"_(\d{1,4})[D]?\.nc$", str(row["file"]))
                if m:
                    p_num = int(m.group(1))
            if p_num is None:
                p_num = idx_count + 1

            # Per-cycle variable availability from profile_index.available_variables
            # (space-delimited string, e.g. "CHLA DOXY TEMP"). Powers the
            # redesigned Float Cycle History table and trajectory hover tooltips.
            cycle_vars: list[str] = []
            if "available_variables" in df.columns and pd.notna(row.get("available_variables")):
                cycle_vars = [
                    v for v in str(row.get("available_variables")).split()
                    if v and v.upper() not in {"NAN", "NONE"}
                ]

            map_data.append(
                MapData(
                    float_id=clean_fid,
                    latitude=lat_val,
                    longitude=lon_val,
                    profile_date=date_val,
                    profile_number=p_num,
                    dac=str(row.get("dac", "")),
                    variables=cycle_vars,
                    selected=(idx_count == len(df) - 1),
                    status="unknown",
                    wmo_id=clean_fid,
                )
            )

        # Derive Network for the whole float from the union of cycle variables:
        # any BGC variable => BGC Argo, otherwise Core Argo. Applied to all
        # trajectory markers so the sidebar Network filter is consistent.
        _all_vars = " ".join(v.upper() for m in map_data for v in m.variables)
        _BGC_VAR_MARKERS = ("DOXY", "CHLA", "NITRATE", "BBP", "PH_IN_SITU", "DOWNWELLING", "DOWN_IRR")
        _traj_network = "BGC Argo" if any(mk in _all_vars for mk in _BGC_VAR_MARKERS) else "Core Argo"
        for _m in map_data:
            _m.network = _traj_network

        min_d = str(df["date"].min())[:10] if "date" in df.columns and pd.notna(df["date"].min()) else None
        max_d = str(df["date"].max())[:10] if "date" in df.columns and pd.notna(df["date"].max()) else None
        summary = {
            "matched_records": len(map_data),
            "unique_profiles": len(map_data),
            "float_id": clean_fid,
            "trajectory_points": len(map_data),
            "distance_km": round(total_dist_km, 1),
            "date_range": {"min": min_d, "max": max_d},
            "trajectory_path": [[m.longitude, m.latitude] for m in map_data],
        }

        msg = f"Retrieved {len(map_data)} profile coordinates for Float {clean_fid} spanning a total trajectory distance of {total_dist_km:.1f} km between {min_d or 'N/A'} and {max_d or 'N/A'}."
        if self.explanation_engine:
            try:
                from floatchat.scientific_explanation.schemas import build_minimal_facts
                facts = build_minimal_facts([], query_id="traj")
                facts = facts.model_copy(
                    update={
                        "float_id": clean_fid,
                        "cross_variable_notes": [
                            f"Trajectory of Float {clean_fid} spans {len(map_data)} profile locations covering a total distance of {total_dist_km:.1f} km between {min_d or 'N/A'} and {max_d or 'N/A'}."
                        ],
                    }
                )
                if self.explanation_engine.prompt_builder and self.explanation_engine.narrator and self.explanation_engine.output_parser and self.explanation_engine.verification_guard and self.explanation_engine._narration_is_enabled():
                    prompt = self.explanation_engine.prompt_builder.build(facts)
                    raw_out = self.explanation_engine.narrator.generate(prompt)
                    parsed_out = self.explanation_engine.output_parser.parse(raw_out)
                    verified = self.explanation_engine.verification_guard.verify(parsed_out, facts)
                    explanation = verified.explanation
                else:
                    explanation = facts.cross_variable_notes[0]
                msg = f"{msg}\n\n{explanation}"
            except Exception as exc:
                logger.warning("Trajectory narration explanation failed (tolerated, visualization not blocked): %s", exc)

        return ChatResponse(
            intent="trajectory",
            message=msg,
            figure=None,
            data_summary=summary,
            map_data=map_data,
        )

    # --------------------------------------------------------------------- #
    # Priority 1A: Data queries via local lake (region_search, profile_plot,
    # time_series, hovmoller, ts_diagram, comparison)
    # --------------------------------------------------------------------- #


    def _execute_data_query_via_lake(
        self,
        intent: ParsedIntent,
        pipeline_t0: float,
    ) -> ChatResponse:
        """Execute a data query EXCLUSIVELY from DuckDBDataLake.

        Priority 1A: No GDAC fallback. Zero rows = explain, don't download.
        Priority 1A: No max_profiles=5 cap. Uses data_lake_max_profiles.
        Priority 1D: Zero-result explanations with availability probe.
        """
        from floatchat.data_lake.base import LakeQueryCriteria

        lake = self._get_data_lake()
        if lake is None or not (lake.is_available() or lake.is_phase2_available()):
            # Priority 1A: Check if remote fallback is allowed
            if settings.allow_remote_gdac_fallback:
                logger.warning(
                    "Data lake unavailable; FALLING BACK to GDAC pipeline — "
                    "this makes remote HTTP calls!"
                )
                return self._execute_via_legacy_gdac(intent, pipeline_t0)

            return ChatResponse(
                intent=intent.intent,
                message=(
                    "The local data lake is not available and remote GDAC downloads "
                    "are disabled (FLOATCHAT_ALLOW_REMOTE_GDAC_FALLBACK=False). "
                    "Set up the data lake by running the phase2_builder ETL first."
                ),
                data_summary={"matched_records": 0},
            )

        # Map ParsedIntent → LakeQueryCriteria
        # Priority 1A: Use data_lake_max_profiles instead of legacy 5
        query_limit = settings.data_lake_max_profiles

        # Convert point + radius to bounding box for spatial measurement queries.
        # Triggered when a place name was geocoded (lat/lon set) but no explicit
        # bounding box was provided. radius_km is preserved on ParsedIntent for
        # future true-haversine filtering; the bounding box is an approximation
        # (~111 km per degree) that slightly over-selects at the corners.
        lat_min = intent.lat_min
        lat_max = intent.lat_max
        lon_min = intent.lon_min
        lon_max = intent.lon_max
        if intent.lat is not None and intent.lon is not None and lat_min is None:
            _r = intent.radius_km or 500.0
            _deg = _r / 111.0
            lat_min = max(-90.0, intent.lat - _deg)
            lat_max = min(90.0, intent.lat + _deg)
            lon_min = max(-180.0, intent.lon - _deg)
            lon_max = min(180.0, intent.lon + _deg)
            logger.info(
                "Spatial bbox from point+radius: (%.2f,%.22f)+%.0fkm -> "
                "lat[%.2f,%.2f] lon[%.2f,%.2f]",
                intent.lat, intent.lon, _r, lat_min, lat_max, lon_min, lon_max,
            )

        criteria = LakeQueryCriteria(
            region=(
                intent.region
                if intent.region in ("arabian_sea", "bay_of_bengal")
                else None
            ),
            lat_min=lat_min,
            lat_max=lat_max,
            lon_min=lon_min,
            lon_max=lon_max,
            year=intent.year,
            month=intent.month,
            # P3 #3: pass the season month-window (e.g. monsoon -> [6,7,8,9]).
            months=getattr(intent, "month_window", None),
            variables=intent.variables or [],
            float_id=intent.float_id,
            profile_number=intent.profile_number,
            limit=query_limit,
            depth_min=intent.depth_min,
            depth_max=intent.depth_max,
        )

        t_lake = time.perf_counter()
        lake_result = None
        if intent.intent in ("comparison", "comparison_plot") and len(intent.comparison_float_ids) >= 2:
            all_dfs = []
            total_meas = 0
            unique_floats = 0
            unique_profiles = 0
            for fid in intent.comparison_float_ids:
                f_crit = dataclasses.replace(criteria, float_id=fid)
                res = lake.query(f_crit)
                if res.has_data and not res.df.empty:
                    all_dfs.append(res.df)
                    total_meas += res.total_measurements
                    unique_floats += res.unique_floats
                    unique_profiles += res.unique_profiles
            if all_dfs:
                from floatchat.data_lake.base import LakeQueryResult
                comb_df = pd.concat(all_dfs, ignore_index=True)
                lake_result = LakeQueryResult(
                    df=comb_df,
                    stats={},
                    unique_floats=unique_floats,
                    unique_profiles=unique_profiles,
                    total_measurements=total_meas,
                    has_data=True,
                    source=lake._lake_root.as_posix(),
                )
        if lake_result is None:
            lake_result = lake.query(criteria)
        t_lake_end = time.perf_counter()
        logger.info(
            "Data lake query: %.3fs, %d rows, %d floats, has_data=%s [NO GDAC HTTP]",
            t_lake_end - t_lake,
            lake_result.total_measurements,
            lake_result.unique_floats,
            lake_result.has_data,
        )

        if not lake_result.has_data or lake_result.df.empty:
            # Priority 1D: Zero-result explanation with availability probe
            zero_msg = lake.build_zero_result_message(criteria)
            availability = lake.probe_availability(criteria.variables or None)
            return ChatResponse(
                intent=intent.intent,
                message=zero_msg,
                data_summary={
                    "matched_records": 0,
                    "lake_available": lake.is_available(),
                    "lake_years": lake.list_available_years(),
                    "availability": availability,
                },
            )

        df = lake_result.df.copy()
        df["profile_date"] = pd.to_datetime(df["date"], errors="coerce")

        # Map lowercase lake columns to standard uppercase Argo variable names for viz/explanation
        col_aliases = {
            "pressure": "PRES",
            "temp": "TEMP",
            "temp_qc": "TEMP_QC",
            "temp_adjusted": "TEMP_ADJUSTED",
            "psal": "PSAL",
            "psal_qc": "PSAL_QC",
            "psal_adjusted": "PSAL_ADJUSTED",
            "doxy": "DOXY",
            "doxy_qc": "DOXY_QC",
            "doxy_adjusted": "DOXY_ADJUSTED",
            "chla": "CHLA",
            "chla_qc": "CHLA_QC",
            "chla_adjusted": "CHLA_ADJUSTED",
            "bbp700": "BBP700",
            "bbp700_qc": "BBP700_QC",
            "bbp700_adjusted": "BBP700_ADJUSTED",
            "nitrate": "NITRATE",
            "nitrate_qc": "NITRATE_QC",
            "nitrate_adjusted": "NITRATE_ADJUSTED",
            "ph_in_situ_total": "PH_IN_SITU_TOTAL",
            "ph_in_situ_total_qc": "PH_IN_SITU_TOTAL_QC",
            "ph_in_situ_total_adjusted": "PH_IN_SITU_TOTAL_ADJUSTED",
            "downwelling_par": "DOWNWELLING_PAR",
            "downwelling_par_qc": "DOWNWELLING_PAR_QC",
            "downwelling_par_adjusted": "DOWNWELLING_PAR_ADJUSTED",
        }
        for low, up in col_aliases.items():
            if low in df.columns and up not in df.columns:
                df[up] = df[low]

        # Build map_data from the ACTUAL filtered DataFrame — guarantees map
        # markers match the data that was queried and returned. Previous approach
        # used a separate get_map_markers query which could return different
        # floats due to type mismatches or filter inconsistencies.
        map_data = self._build_map_data_from_lake(df)
        logger.info("Map markers from filtered data: %d markers", len(map_data))

        # --- Visualization --- #
        t_viz_t0 = time.perf_counter()
        try:
            figure = self.viz.render(intent, df)
        except FloatChatError:
            logger.exception("Visualization failed for data lake result")
            return ChatResponse(
                intent=intent.intent,
                message="Data retrieved from lake but visualization failed.",
                data_summary=self._build_lake_summary(lake_result, df),
                map_data=map_data,
            )
        t_viz_end = time.perf_counter()

        # --- Per-variable figures for the redesigned stacked plot drawer --- #
        # Additive: produces one standalone figure per variable (Temp, Salinity,
        # Oxygen, Chlorophyll, ...). Falls back to None silently so the primary
        # response is never affected by a drawer-render failure.
        figures: list[dict] | None = None
        per_var_fn = getattr(self.viz, "render_per_variable", None)
        if callable(per_var_fn):
            try:
                figures = per_var_fn(intent, df) or None
            except Exception as exc:
                logger.warning("Per-variable figure render failed: %s", exc)
                figures = None

        # --- Scientific Explanation --- #
        t_sci_t0 = time.perf_counter()
        data_summary = self._build_lake_summary(lake_result, df)
        verification = build_verification_section(
            intent, [], intent.variables, lake_result.stats
        )
        pipeline_trace = build_pipeline_trace(
            intent,
            {
                "lake_query": t_lake_end - t_lake,
                "viz": t_viz_end - t_viz_t0,
                "total": time.perf_counter() - pipeline_t0,
            },
            False,
        )
        explanation = self.explanation_engine.generate_explanation(
            intent, [], intent.variables, data_summary, df=df
        )
        base_message = (
            f"Retrieved {lake_result.unique_profiles} profile(s) with "
            f"{lake_result.total_measurements} total measurements "
            f"for variables {', '.join(intent.variables)} from the data lake [local only, no GDAC HTTP]."
        )
        final_message = base_message + "\n\n" + explanation

        data_summary.update({
            "verification": verification,
            "pipeline_trace": pipeline_trace,
            "source": lake_result.source,
            "derived_insights": {},
        })
        t_sci_end = time.perf_counter()
        logger.info("Scientific explanation: %.3fs", t_sci_end - t_sci_t0)
        logger.info("Total request time: %.3fs [NO GDAC HTTP]", time.perf_counter() - pipeline_t0)

        return ChatResponse(
            intent=intent.intent,
            message=final_message,
            figure=figure,
            figures=figures,
            data_summary=data_summary,
            map_data=map_data,
        )

    # --------------------------------------------------------------------- #
    # Legacy GDAC pipeline (ONLY used when FLOATCHAT_ALLOW_REMOTE_GDAC_FALLBACK=True)
    # --------------------------------------------------------------------- #

    def _execute_via_legacy_gdac(
        self,
        intent: ParsedIntent,
        pipeline_t0: float,
    ) -> ChatResponse:
        """Legacy GDAC pipeline — makes remote HTTP calls to data-argo.ifremer.fr.

        This path is ONLY accessible when FLOATCHAT_ALLOW_REMOTE_GDAC_FALLBACK=True.
        It is retained for backwards compatibility and for the offline phase2_builder.
        """
        logger.warning("Executing via LEGACY GDAC pipeline — remote HTTP calls will be made!")

        # --- Phase 21: Retrieval Planning --- #
        plan = self.planner.plan(intent.variables or [])
        logger.info("Retrieval Plan: %s", plan.reasoning)

        # --- Step 1: Metadata search --- #
        t0 = time.perf_counter()
        criteria = self._intent_to_criteria(intent)
        search_groups = self._search_metadata_groups(intent, criteria, plan)
        records = [record for group_records, _ in search_groups for record in group_records]
        t1 = time.perf_counter()
        logger.info("Metadata search: %.3fs (%d records)", t1 - t0, len(records))

        if not records:
            logger.warning("No metadata records matched criteria: %s", criteria)
            suggestion = self._get_error_suggestion(intent)
            return ChatResponse(
                intent=intent.intent,
                message=f"No Argo profiles matched your query criteria. {suggestion}",
                data_summary={"matched_records": 0},
            )

        map_data = self._build_map_data(records)

        # --- Step 2: Fetch & read NetCDFs --- #
        dataframes: list[pd.DataFrame] = []
        fetched_files: set[str] = set()
        for group_records, variables in search_groups:
            for rec in group_records:
                float_id = _extract_float_id_from_path(rec.file)
                if rec.file in fetched_files:
                    continue
                fetched_files.add(rec.file)

                t_fetch_t0 = time.perf_counter()
                ncd = self.repository.fetch(rec.file)
                t_fetch_t1 = time.perf_counter()
                logger.info("NetCDF fetch: %.3fs (%s) [GDAC HTTP]", t_fetch_t1 - t_fetch_t0, rec.file)

                t_read_t0 = time.perf_counter()
                try:
                    df = self.reader.read(ncd, variables)
                    df["source_file"] = rec.file
                    df["profile_date"] = rec.date
                    df["latitude"] = rec.latitude
                    df["longitude"] = rec.longitude
                    df["float_id"] = float_id
                    df["dac"] = rec.institution
                    dataframes.append(df)
                except FloatChatError:
                    logger.exception("Failed to read %s; skipping", rec.file)
                finally:
                    ncd.close()
                t_read_t1 = time.perf_counter()
                logger.info("NetCDF read: %.3fs (%s)", t_read_t1 - t_read_t0, rec.file)

        t2 = time.perf_counter()
        logger.info("NetCDF fetch+read: %.3fs (%d profiles) [GDAC HTTP]", t2 - t1, len(records))

        if not dataframes:
            return ChatResponse(
                intent=intent.intent,
                message="Profiles were found but could not be read.",
                data_summary={"matched_records": len(records), "readable": 0},
                map_data=map_data,
            )

        combined = pd.concat(dataframes, ignore_index=True)

        # --- Step 3: Visualization --- #
        try:
            figure = self.viz.render(intent, combined)
        except FloatChatError:
            logger.exception("Visualization failed")
            return ChatResponse(
                intent=intent.intent,
                message="Data retrieved but visualization failed.",
                data_summary=self._build_summary(combined, records),
                map_data=map_data,
            )

        t3 = time.perf_counter()

        # --- Step 4: Scientific Interpretation + Verification --- #
        verification = build_verification_section(
            intent, records, intent.variables, {}
        )
        pipeline_trace = build_pipeline_trace(
            intent,
            {
                "metadata": t1 - t0,
                "netcdf": t2 - t1,
                "viz": t3 - t2,
                "total": t3 - pipeline_t0,
            },
            False,
        )

        base_message = self._build_message(intent, records, combined)
        data_summary = self._build_summary(combined, records)
        explanation = self.explanation_engine.generate_explanation(
            intent, records, intent.variables, data_summary, df=combined
        )
        final_message = f"{base_message}\n\n{explanation}"

        data_summary.update({
            "verification": verification,
            "pipeline_trace": pipeline_trace,
            "suggestions": self._generate_suggestions(intent, records),
            "derived_insights": {},
        })

        return ChatResponse(
            intent=intent.intent,
            message=final_message,
            figure=figure,
            data_summary=data_summary,
            map_data=map_data,
        )

    # --------------------------------------------------------------------- #
    # Helpers
    # --------------------------------------------------------------------- #

    def _get_data_lake(self) -> Any:
        """Lazily instantiate the data lake on first use."""
        if self._data_lake is None:
            try:
                from floatchat.data_lake import DuckDBDataLake

                if settings.data_lake_phase2_enabled:
                    phase2_dir = Path(settings.data_lake_dir)
                    lake = DuckDBDataLake(
                        phase2_root=phase2_dir,
                        use_phase2=True,
                    )
                    if lake.is_phase2_available():
                        self._data_lake = lake
                        logger.info("Phase 2 Data Lake initialised: root=%s", phase2_dir)
                    else:
                        logger.warning(
                            "Phase 2 data lake configured but not available at %s. "
                            "Falling back to Phase 1.",
                            phase2_dir,
                        )
                        lake_root = Path(settings.data_lake_root)
                        self._data_lake = DuckDBDataLake(lake_root=lake_root)
                else:
                    lake_root = Path(settings.data_lake_root)
                    self._data_lake = DuckDBDataLake(lake_root=lake_root)

                logger.info(
                    "Data Lake initialised: root=%s available=%s",
                    self._data_lake._lake_root,
                    self._data_lake.is_available(),
                )
            except Exception as exc:
                logger.error("Failed to initialise data lake: %s", exc)
                return None
        return self._data_lake

    @staticmethod
    def _build_map_data_from_lake(df: pd.DataFrame) -> list[MapData]:
        """Build map markers from lake DataFrame."""
        markers: list[MapData] = []
        seen: set[str] = set()
        # Pre-compute which floats carry any BGC variable, for Network derivation.
        _BGC_VAR_MARKERS = ("DOXY", "CHLA", "NITRATE", "BBP", "PH_IN_SITU", "DOWNWELLING", "DOWN_IRR")
        bgc_floats: set[str] = set()
        if not df.empty and "float_id" in df.columns:
            for _fid, _grp in df.groupby("float_id"):
                cols_upper = [str(c).upper() for c in _grp.columns]
                has_bgc_col = any(
                    mk in cu and cu.endswith(mk) for cu in cols_upper for mk in _BGC_VAR_MARKERS
                )
                if has_bgc_col and any(
                    _grp[c].notna().any()
                    for c in _grp.columns
                    if any(str(c).upper().endswith(mk) for mk in _BGC_VAR_MARKERS)
                ):
                    bgc_floats.add(str(_fid))

        for _, row in df.drop_duplicates(subset=["float_id"], keep="last").iterrows():
            fid = str(row.get("float_id", ""))
            if fid in seen or not fid:
                continue
            seen.add(fid)
            date_val = row.get("date", None)
            date_str = str(date_val)[:10] if date_val is not None and pd.notna(date_val) and str(date_val) != "NaT" else None
            p_num = None
            if "cycle_number" in df.columns and pd.notna(row.get("cycle_number")):
                try:
                    p_num = int(row["cycle_number"])
                except Exception:
                    pass
            markers.append(
                MapData(
                    float_id=fid,
                    latitude=float(row["lat"]) if pd.notna(row.get("lat")) else None,
                    longitude=float(row["lon"]) if pd.notna(row.get("lon")) else None,
                    profile_date=date_str,
                    profile_number=p_num,
                    dac=str(row.get("dac", "")),
                    variables=[],
                    selected=False,
                    network="BGC Argo" if fid in bgc_floats else "Core Argo",
                    wmo_id=fid,
                )
            )
        return markers

    @staticmethod
    def _build_lake_summary(lake_result: Any, df: pd.DataFrame) -> dict[str, Any]:
        """Build data_summary dict from lake result."""
        date_col = df["date"] if "date" in df.columns else pd.Series(dtype="datetime64[ns]")
        date_min = date_col.min()
        date_max = date_col.max()
        return {
            "matched_records": lake_result.unique_profiles,
            "total_measurements": lake_result.total_measurements,
            "unique_floats": lake_result.unique_floats,
            "unique_profiles": lake_result.unique_profiles,
            "date_range": {
                "min": str(date_min)[:10] if pd.notna(date_min) else None,
                "max": str(date_max)[:10] if pd.notna(date_max) else None,
            },
            "source": lake_result.source,
            "stats": lake_result.stats,
        }

    @staticmethod
    def _intent_to_criteria(intent: ParsedIntent) -> SearchCriteria:
        """Map a :class:`ParsedIntent` to :class:`SearchCriteria`."""
        limit = (
            1
            if intent.float_id is not None and intent.profile_number is not None
            else min(intent.limit, settings.max_profiles_per_query)
        )
        return SearchCriteria(
            region=intent.region,
            lat_min=intent.lat_min,
            lat_max=intent.lat_max,
            lon_min=intent.lon_min,
            lon_max=intent.lon_max,
            year=intent.year,
            month=intent.month,
            day=intent.day,
            parameters=intent.variables,
            float_id=intent.float_id,
            profile_number=intent.profile_number,
            limit=limit,
        )

    def _search_metadata_groups(
        self,
        intent: ParsedIntent,
        criteria: SearchCriteria,
        plan,
    ) -> list[tuple[list[Any], list[str]]]:
        """Search metadata — used ONLY by legacy GDAC pipeline."""
        classification = VariableRegistry.classify_variables(intent.variables or [])
        core_vars = classification["core"]
        bgc_vars = classification["bgc"]

        if intent.intent in ("comparison", "comparison_plot") and len(intent.comparison_float_ids) >= 2:
            all_core = []
            all_bio = []
            for fid in intent.comparison_float_ids:
                f_crit = criteria.model_copy(update={"float_id": fid})
                fid_bio = []
                fid_core = []
                if plan.metadata_index in ("bio", "both") or plan.requires_bio:
                    fid_bio = self.metadata.search(f_crit.model_copy(update={"parameters": bgc_vars if plan.metadata_index == "both" else criteria.parameters}))
                if plan.metadata_index in ("core", "both") or plan.requires_core:
                    fid_core = self.metadata.search(f_crit.model_copy(update={"parameters": core_vars if plan.metadata_index == "both" else criteria.parameters}))
                if not fid_bio and not fid_core:
                    fid_core = self.metadata.search(f_crit.model_copy(update={"parameters": []}))
                all_bio.extend(fid_bio)
                all_core.extend(fid_core)
            groups = []
            if all_core and (core_vars or plan.metadata_index == "core" or not all_bio):
                groups.append((all_core, core_vars if plan.metadata_index == "both" else (intent.variables or [])))
            if all_bio and (bgc_vars or plan.metadata_index == "bio"):
                groups.append((all_bio, bgc_vars if plan.metadata_index == "both" else (intent.variables or [])))
            if groups:
                return groups

        if plan.metadata_index != "both":
            return [(self.metadata.search(criteria), intent.variables)]

        pair_limit = max(criteria.limit, 10)
        core_records: list[Any] = []
        bio_records: list[Any] = []
        if core_vars:
            core_criteria = criteria.model_copy(update={"parameters": core_vars, "limit": pair_limit})
            core_records = self.metadata.search(core_criteria)
        if bgc_vars:
            bio_criteria = criteria.model_copy(update={"parameters": bgc_vars, "limit": pair_limit})
            bio_records = self.metadata.search(bio_criteria)

        if core_records and bio_records:
            core_records, bio_records = self._pair_by_float_cycle(
                core_records, bio_records, criteria.limit
            )

        groups: list[tuple[list[Any], list[str]]] = []
        if core_records and core_vars:
            groups.append((core_records, core_vars))
        if bio_records and bgc_vars:
            groups.append((bio_records, bgc_vars))

        return groups

    @staticmethod
    def _pair_by_float_cycle(
        core_records: list[Any],
        bio_records: list[Any],
        limit: int,
    ) -> tuple[list[Any], list[Any]]:
        """Phase 24: Reorder records so pairs from the same float+cycle come first."""
        core_by_key: dict[tuple[str, str], list[Any]] = {}
        for r in core_records:
            key = _extract_float_cycle_key(r.file)
            core_by_key.setdefault(key, []).append(r)

        bio_by_key: dict[tuple[str, str], list[Any]] = {}
        for r in bio_records:
            key = _extract_float_cycle_key(r.file)
            bio_by_key.setdefault(key, []).append(r)

        paired_keys = set(core_by_key) & set(bio_by_key)

        if not paired_keys:
            return core_records[:limit], bio_records[:limit]

        paired_core: list[Any] = []
        paired_bio: list[Any] = []
        for key in sorted(paired_keys):
            paired_core.extend(core_by_key[key])
            paired_bio.extend(bio_by_key[key])

        unpaired_core: list[Any] = []
        for key in sorted(set(core_by_key) - paired_keys):
            unpaired_core.extend(core_by_key[key])
        unpaired_bio: list[Any] = []
        for key in sorted(set(bio_by_key) - paired_keys):
            unpaired_bio.extend(bio_by_key[key])

        def sort_key(record: Any):
            return record.date

        paired_core.sort(key=sort_key, reverse=True)
        paired_bio.sort(key=sort_key, reverse=True)
        unpaired_core.sort(key=sort_key, reverse=True)
        unpaired_bio.sort(key=sort_key, reverse=True)

        best_core = paired_core + unpaired_core
        best_bio = paired_bio + unpaired_bio

        logger.info(
            "Phase 24 pairing: %d paired floats, returning %d core + %d bio records",
            len(paired_keys), min(len(best_core), limit), min(len(best_bio), limit),
        )

        return best_core[:limit], best_bio[:limit]

    @staticmethod
    def _build_map_data(records: list[Any]) -> list[MapData]:
        """Build geographic marker data from metadata records."""
        markers: list[MapData] = []
        seen_floats: set[str] = set()
        for rec in records:
            float_id = _extract_float_id_from_path(rec.file)
            if float_id in seen_floats:
                continue
            seen_floats.add(float_id)
            p_num = getattr(rec, "cycle_number", getattr(rec, "profile_number", None))
            if p_num is None and hasattr(rec, "file") and rec.file:
                m = re.search(r"_(\d{1,4})[D]?\.nc$", str(rec.file))
                if m:
                    p_num = int(m.group(1))
            date_str = (
                rec.date.isoformat()
                if getattr(rec, "date", None) is not None and pd.notna(rec.date) and str(rec.date) != "NaT"
                else (str(getattr(rec, "date", ""))[:10] if getattr(rec, "date", None) is not None and str(rec.date) != "NaT" else None)
            )
            markers.append(
                MapData(
                    float_id=float_id,
                    latitude=rec.latitude,
                    longitude=rec.longitude,
                    profile_date=date_str,
                    profile_number=p_num,
                    dac=rec.institution or "",
                    variables=rec.parameters.split() if getattr(rec, "parameters", None) else [],
                    selected=False,
                )
            )
        return markers

    @staticmethod
    def _build_message(
        intent: ParsedIntent,
        records: list[Any],
        df: pd.DataFrame,
    ) -> str:
        parts = [
            f"Retrieved {len(records)} profile(s)",
            f"with {len(df)} total measurements",
        ]
        if intent.variables:
            parts.append(f"for variables {', '.join(intent.variables)}.")
        else:
            parts.append(".")
        return " ".join(parts)

    @staticmethod
    def _build_summary(df: pd.DataFrame, records: list[Any]) -> dict[str, Any]:
        date_min = df["profile_date"].min() if "profile_date" in df.columns else pd.NaT
        date_max = df["profile_date"].max() if "profile_date" in df.columns else pd.NaT
        return {
            "matched_records": len(records),
            "total_measurements": len(df),
            "unique_profiles": (
                int(df["profile_idx"].nunique()) if "profile_idx" in df.columns else 0
            ),
            "date_range": {
                "min": date_min.isoformat() if pd.notna(date_min) else None,
                "max": date_max.isoformat() if pd.notna(date_max) else None,
            },
            "files": [r.file for r in records],
        }

    @staticmethod
    def _get_error_suggestion(intent: ParsedIntent) -> str:
        """Return a helpful suggestion when no profiles are found."""
        if intent.variables and "TEMP" in intent.variables:
            return "This float may only contain BGC variables. Try requesting DOXY or CHLA instead."
        if intent.year and intent.year < 2015:
            return "Try a more recent year (many BGC floats were deployed after 2015)."
        if intent.region:
            return "Try broadening the region or removing the year filter."
        return "Try another year, different region, or a different variable."

    @staticmethod
    def _generate_suggestions(
        intent: ParsedIntent, records: list[Any]
    ) -> list[str]:
        """Generate context-aware follow-up suggestions."""
        suggestions = []
        vars_upper = [v.upper() for v in intent.variables]

        if "DOXY" in vars_upper or "DOXY_ADJUSTED" in vars_upper:
            suggestions.append("Compare with last year")
            suggestions.append("View chlorophyll")
        if "CHLA" in vars_upper or "CHLA_ADJUSTED" in vars_upper:
            suggestions.append("Inspect trajectory")
        if intent.region:
            suggestions.append("Show temperature")
            suggestions.append("Compare another float in same region")
        if not suggestions:
            suggestions = ["View oxygen", "Show salinity profile", "Compare with 2023"]
        return suggestions[:4]

    @staticmethod
    def _calculate_derived_insights(
        df: pd.DataFrame, variables: list[str]
    ) -> dict[str, Any]:
        """Deprecated: Use ScientificExplanationEngine._compute_stats instead."""
        return {}
