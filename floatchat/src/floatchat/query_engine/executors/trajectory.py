"""Trajectory executor: float coordinate history across cycles.

Extracted verbatim from the pre-M4 ``query_engine/engine.py`` monolith
(Milestone 4 decomposition). Reads the local lake profile index (with an
internal DuckDB schema-sniffing fallback) and, only when remote fallback is
explicitly enabled, the GDAC metadata service.
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING

import pandas as pd

from floatchat.config import settings
from floatchat.models import ChatResponse, MapData, ParsedIntent, SearchCriteria
from floatchat.ontology.sensors import BGC_VARIABLE_MARKER_TOKENS, NETWORK_BGC, NETWORK_CORE
from floatchat.query_engine.helpers import _extract_cycle_from_filename

if TYPE_CHECKING:
    from floatchat.query_engine.dispatch import ExecutionDeps

logger = logging.getLogger(__name__)


def execute_trajectory(deps: ExecutionDeps, intent: ParsedIntent, pipeline_t0: float) -> ChatResponse:
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
    lake = deps.lake
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
    if df.empty and deps.metadata and settings.allow_remote_gdac_fallback and settings.enable_gdac_runtime:
        logger.warning(
            "GDAC trajectory fallback triggered for float %s — remote HTTP call.",
            clean_fid,
        )
        try:
            records = deps.metadata.search(SearchCriteria(float_id=clean_fid, limit=2000))
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
            p_num = _extract_cycle_from_filename(str(row["file"]))
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
    # Ontology 2.0 (Phase 1): marker tokens and network names come from the
    # domain ontology; contents are unchanged.
    _all_vars = " ".join(v.upper() for m in map_data for v in m.variables)
    _BGC_VAR_MARKERS = BGC_VARIABLE_MARKER_TOKENS
    _traj_network = NETWORK_BGC if any(mk in _all_vars for mk in _BGC_VAR_MARKERS) else NETWORK_CORE
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
    if deps.explanation_engine:
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
            if deps.explanation_engine.prompt_builder and deps.explanation_engine.narrator and deps.explanation_engine.output_parser and deps.explanation_engine.verification_guard and deps.explanation_engine._narration_is_enabled():
                prompt = deps.explanation_engine.prompt_builder.build(facts)
                raw_out = deps.explanation_engine.narrator.generate(prompt)
                parsed_out = deps.explanation_engine.output_parser.parse(raw_out)
                verified = deps.explanation_engine.verification_guard.verify(parsed_out, facts)
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
