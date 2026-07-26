"""Spatial executors: nearest-float and radius-search queries.

Extracted verbatim from the pre-M4 ``query_engine/engine.py`` monolith
(Milestone 4 decomposition). Both executors operate exclusively against the
injected local data lake via ``deps.lake`` (no GDAC HTTP calls).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pandas as pd

from floatchat.config import settings
from floatchat.models import ChatResponse, MapData, ParsedIntent
from floatchat.query_engine.helpers import (
    _build_alive_window,
    _derive_marker_network,
    _filter_floats_by_variable,
    _marker_region_tag,
    _resolve_manufacturer,
)

if TYPE_CHECKING:
    from floatchat.query_engine.dispatch import ExecutionDeps

logger = logging.getLogger(__name__)


def execute_nearest_float(deps: ExecutionDeps, intent: ParsedIntent, pipeline_t0: float) -> ChatResponse:
    lake = deps.lake
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
                marker_vars = [s.strip() for s in sensors.split(",") if s.strip()] if sensors else []

                map_data.append(
                    MapData(
                        float_id=fid,
                        latitude=lat_val,
                        longitude=lon_val,
                        profile_date=last_date if last_date else None,
                        dac=str(row.get("institution", "")),
                        variables=marker_vars,
                        selected=False,
                        status=status,
                        manufacturer=mfr,
                        profiler_type=profiler_code if profiler_code else None,
                        network=_derive_marker_network(marker_vars),
                        wmo_id=fid,
                        region_tag=_marker_region_tag(lat_val, lon_val),
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


def execute_radius_search(deps: ExecutionDeps, intent: ParsedIntent, pipeline_t0: float) -> ChatResponse:
    lake = deps.lake
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
                                network=_derive_marker_network([]),
                                wmo_id=fid,
                                region_tag=_marker_region_tag(lat_val, lon_val),
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
            marker_vars = [s.strip() for s in sensors.split(",") if s.strip()] if sensors else []

            map_data.append(
                MapData(
                    float_id=fid,
                    latitude=lat_val,
                    longitude=lon_val,
                    profile_date=last_date if last_date else None,
                    dac=str(row.get("institution", "")),
                    variables=marker_vars,
                    selected=False,
                    status=status,
                    manufacturer=mfr,
                    profiler_type=profiler_code if profiler_code else None,
                    network=_derive_marker_network(marker_vars),
                    wmo_id=fid,
                    region_tag=_marker_region_tag(lat_val, lon_val),
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
