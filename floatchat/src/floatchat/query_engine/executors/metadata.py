"""Metadata executors: float metadata lookup and count aggregates.

Extracted verbatim from the pre-M4 ``query_engine/engine.py`` monolith
(Milestone 4 decomposition). The lookup executor supplements missing registry
fields from the (disabled-by-default) GDAC metadata service only when the
remote-fallback settings allow it — semantics unchanged.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pandas as pd

from floatchat.config import settings
from floatchat.models import ChatResponse, MapData, ParsedIntent, SearchCriteria
from floatchat.query_engine.helpers import _resolve_manufacturer

if TYPE_CHECKING:
    from floatchat.query_engine.dispatch import ExecutionDeps

logger = logging.getLogger(__name__)


def execute_metadata_lookup(deps: ExecutionDeps, intent: ParsedIntent, pipeline_t0: float) -> ChatResponse:
    """Priority 1A: metadata_lookup uses ONLY the local data lake.

    No GDAC metadata service fallback when FLOATCHAT_ALLOW_REMOTE_GDAC_FALLBACK=False.
    """
    lake = deps.lake
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
    if _needs_gdac and deps.metadata and settings.allow_remote_gdac_fallback and settings.enable_gdac_runtime:
        logger.warning(
            "GDAC metadata fallback triggered for float %s — "
            "this is a remote HTTP call. Set FLOATCHAT_ALLOW_REMOTE_GDAC_FALLBACK=False to prevent.",
            float_id,
        )
        try:
            records = deps.metadata.search(SearchCriteria(float_id=float_id, limit=2000))
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


def execute_count_aggregate(deps: ExecutionDeps, intent: ParsedIntent, pipeline_t0: float) -> ChatResponse:
    lake = deps.lake

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
