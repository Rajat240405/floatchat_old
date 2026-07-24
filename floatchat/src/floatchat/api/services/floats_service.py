"""Floats application service — deterministic, LLM-free data access.

Cleanup M3 (API layer decomposition): moved verbatim from the former
monolithic ``api/routes.py``. The route module (``api/routes/floats.py``) only
maps HTTP parameters onto these functions and wraps results in the response
schemas from ``floatchat.api.schemas``.

Contains all DuckDB/Parquet access used by the /floats/* endpoints
(registry aggregation, trajectory/cycle history, latest profile, available
plots, single-variable plots), registry metadata formatting, and the shared
float-id / variable-count helpers. SQL strings and fallbacks are unchanged.
"""

import logging
from pathlib import Path

from floatchat.api.schemas import (
    AvailablePlotItem,
    FloatAvailablePlotsResponse,
    FloatMetadataAPIResponse,
    FloatProfileAPIResponse,
    FloatRegistryResponse,
    FloatTrajectoryAPIResponse,
)
from floatchat.config import settings
from floatchat.variable_registry.registry import VariableRegistry

logger = logging.getLogger(__name__)


# ================================================
# Dedicated lightweight registry response
# Returns ALL floats from Phase 2 float_registry + latest positions
# from profile_index. No LIMIT truncation. No LLM.
# ================================================

def build_float_registry_response() -> FloatRegistryResponse:
    """Lightweight dashboard bootstrap endpoint.

    Returns every float in the local lake with:
    - latest known position
    - registry status (active / inactive / drifted) — authoritative
    - region_tag for Quick Region filters
    - network / DAC / sensors for sidebar filters

    IMPORTANT: Must NOT apply an arbitrary profile LIMIT. A previous
    ``get_profile_index(limit=10000)`` only saw floats present in the
    newest 10k profiles, which collapsed a ~1300-float registry to ~269.
    """
    try:
        from floatchat.data_lake.duckdb_lake import DuckDBDataLake
        from floatchat.config import settings
        import pandas as pd

        lake = DuckDBDataLake(
            phase2_root=Path(settings.data_lake_dir) if settings.data_lake_phase2_enabled else None,
            use_phase2=settings.data_lake_phase2_enabled,
        )

        map_data: list[dict] = []
        networks: set[str] = set()
        dacs: set[str] = set()
        variables: set[str] = set()
        statuses: set[str] = set()

        fr_df = (
            lake.get_float_registry()
            if hasattr(lake, "get_float_registry")
            else pd.DataFrame()
        )

        # Latest position per float — NO row limit. Aggregate in DuckDB so we
        # never load the full profile_index into Python.
        latest_by_float: dict[str, dict] = {}
        try:
            conn = lake._get_connection()
            pi_path = None
            levels_path = None
            if lake._phase2_root and (lake._phase2_root / "parquet" / "profile_index").exists():
                pi_path = (
                    lake._phase2_root / "parquet" / "profile_index" / "**" / "*.parquet"
                ).as_posix()
            if lake._phase2_root and (lake._phase2_root / "parquet" / "levels").exists():
                levels_path = (
                    lake._phase2_root / "parquet" / "levels" / "**" / "*.parquet"
                ).as_posix()
            elif lake._lake_root.exists():
                levels_path = (lake._lake_root / "**" / "*.parquet").as_posix()

            if pi_path:
                # Detect lat/lon column names from a 1-row sample
                sample = conn.execute(
                    f"SELECT * FROM read_parquet('{pi_path}', hive_partitioning=true) LIMIT 1"
                ).fetchdf()
                cols = {c.lower(): c for c in sample.columns}
                lat_col = cols.get("latitude") or cols.get("lat") or "latitude"
                lon_col = cols.get("longitude") or cols.get("lon") or "longitude"
                region_col = cols.get("region_tag")
                dac_col = cols.get("dac") or cols.get("institution")

                region_select = (
                    f"arg_max({region_col}, date) AS region_tag"
                    if region_col
                    else "CAST(NULL AS VARCHAR) AS region_tag"
                )
                dac_select = (
                    f"arg_max({dac_col}, date) AS dac"
                    if dac_col
                    else "CAST('' AS VARCHAR) AS dac"
                )

                sql = f"""
                SELECT
                    CAST(float_id AS VARCHAR) AS float_id,
                    arg_max({lat_col}, date) AS lat,
                    arg_max({lon_col}, date) AS lon,
                    max(date) AS profile_date,
                    {region_select},
                    {dac_select}
                FROM read_parquet('{pi_path}', hive_partitioning=true)
                GROUP BY float_id
                """
                pos_df = conn.execute(sql).fetchdf()
                for _, row in pos_df.iterrows():
                    fid = str(row["float_id"])
                    latest_by_float[fid] = {
                        "lat": float(row["lat"]) if pd.notna(row.get("lat")) else None,
                        "lon": float(row["lon"]) if pd.notna(row.get("lon")) else None,
                        "profile_date": (
                            str(row["profile_date"])[:10]
                            if pd.notna(row.get("profile_date"))
                            else None
                        ),
                        "region_tag": (
                            str(row["region_tag"])
                            if pd.notna(row.get("region_tag")) and row.get("region_tag")
                            else None
                        ),
                        "dac": str(row["dac"]) if pd.notna(row.get("dac")) else "",
                    }
            elif levels_path:
                sql = f"""
                SELECT
                    CAST(float_id AS VARCHAR) AS float_id,
                    arg_max(lat, date) AS lat,
                    arg_max(lon, date) AS lon,
                    max(date) AS profile_date,
                    arg_max(region_tag, date) AS region_tag,
                    COALESCE(arg_max(dac, date), '') AS dac
                FROM read_parquet('{levels_path}', hive_partitioning=true)
                GROUP BY float_id
                """
                pos_df = conn.execute(sql).fetchdf()
                for _, row in pos_df.iterrows():
                    fid = str(row["float_id"])
                    latest_by_float[fid] = {
                        "lat": float(row["lat"]) if pd.notna(row.get("lat")) else None,
                        "lon": float(row["lon"]) if pd.notna(row.get("lon")) else None,
                        "profile_date": (
                            str(row["profile_date"])[:10]
                            if pd.notna(row.get("profile_date"))
                            else None
                        ),
                        "region_tag": (
                            str(row["region_tag"])
                            if pd.notna(row.get("region_tag")) and row.get("region_tag")
                            else None
                        ),
                        "dac": str(row["dac"]) if pd.notna(row.get("dac")) else "",
                    }
        except Exception as exc:
            logger.warning("Registry position aggregation failed: %s", exc)

        _BGC_MARKERS = (
            "DOXY", "CHLA", "NITRATE", "BBP", "PH", "PAR", "DOWNWELLING_PAR",
            "OPTODE", "FLUOROMETER", "BACKSCATTER", "SUNA", "ISUS", "OCR",
        )

        # Prefer iterating float_registry (authoritative membership + status).
        # Fall back to positions-only if registry file is missing.
        source_ids: list[str]
        fr_map: dict[str, dict] = {}
        if not fr_df.empty:
            for _, r in fr_df.iterrows():
                fid = str(r.get("float_id", "")).strip()
                if not fid:
                    continue
                raw_sensors = r.get("sensors", "")
                if isinstance(raw_sensors, list):
                    sensors = [str(s).strip().upper() for s in raw_sensors if str(s).strip()]
                elif isinstance(raw_sensors, str) and raw_sensors:
                    sensors = [s.strip().upper() for s in raw_sensors.split(",") if s.strip()]
                else:
                    sensors = []
                sensor_blob = " ".join(sensors)
                network = (
                    "BGC Argo"
                    if any(k in sensor_blob for k in _BGC_MARKERS)
                    else "Core Argo"
                )
                region_tag = (
                    str(r.get("region_tag"))
                    if pd.notna(r.get("region_tag")) and r.get("region_tag")
                    else None
                )
                # Authoritative status from registry ETL (active/inactive/drifted)
                status = str(r.get("status", "unknown") or "unknown").lower()
                if status not in ("active", "inactive", "drifted", "unknown"):
                    status = "unknown"
                institution = str(r.get("institution", "") or "")
                pc = r.get("profile_count")
                try:
                    profile_count = int(pc) if pd.notna(pc) else None
                except (TypeError, ValueError):
                    profile_count = None
                fr_map[fid] = {
                    "status": status,
                    "sensors": sensors,
                    "institution": institution,
                    "network": network,
                    "region_tag": region_tag,
                    "profile_count": profile_count,
                    "last_report_date": (
                        str(r.get("last_report_date"))[:10]
                        if pd.notna(r.get("last_report_date"))
                        else None
                    ),
                    "profiler_type": str(r.get("profiler_type", "") or "") or None,
                    "manufacturer": str(r.get("manufacturer", "") or "") or None,
                }
            source_ids = list(fr_map.keys())
        else:
            source_ids = list(latest_by_float.keys())

        for fid in source_ids:
            pos = latest_by_float.get(fid, {})
            fr = fr_map.get(fid, {})
            lat = pos.get("lat")
            lon = pos.get("lon")
            # Skip floats with no usable coordinates
            if lat is None or lon is None:
                continue
            if not (-90.0 <= float(lat) <= 90.0 and -180.0 <= float(lon) <= 180.0):
                continue
            if float(lat) == 0.0 and float(lon) == 0.0:
                continue

            status = fr.get("status") or "unknown"
            sensors = fr.get("sensors") or []
            network = fr.get("network") or "Core Argo"
            region_tag = fr.get("region_tag") or pos.get("region_tag")
            dac = fr.get("institution") or pos.get("dac") or ""
            profile_date = pos.get("profile_date") or fr.get("last_report_date")

            map_data.append({
                "float_id": fid,
                "latitude": float(lat),
                "longitude": float(lon),
                "profile_date": profile_date,
                "dac": dac,
                "variables": sensors,
                "selected": False,
                "status": status,
                "network": network,
                "region_tag": region_tag,
                "wmo_id": fid,
                "profiler_type": fr.get("profiler_type"),
                "manufacturer": fr.get("manufacturer"),
                "profile_count": fr.get("profile_count"),
            })

        for m in map_data:
            if m.get("network"):
                networks.add(m["network"])
            if m.get("dac"):
                dacs.add(m["dac"])
            for v in m.get("variables") or []:
                variables.add(str(v).upper())
            if m.get("status"):
                statuses.add(m["status"])

        if not networks:
            networks = {"Core Argo", "BGC Argo"}
        if not dacs:
            dacs = {"INCOIS", "Coriolis", "AOML"}
        if not variables:
            variables = VariableRegistry.get_all_query_names()
        if not statuses:
            statuses = {"active", "inactive", "drifted"}

        logger.info(
            "Registry endpoint: %d floats (registry_rows=%d, positions=%d)",
            len(map_data),
            len(fr_map),
            len(latest_by_float),
        )

        return FloatRegistryResponse(
            float_count=len(map_data),
            map_data=map_data,
            networks=sorted(list(networks)),
            dacs=sorted(list(dacs)),
            variables=sorted(list(variables)),
            statuses=sorted(list(statuses)),
        )
    except Exception as exc:
        logger.exception("Registry endpoint failed: %s", exc)
        return FloatRegistryResponse(
            float_count=0,
            map_data=[],
            networks=["Core Argo", "BGC Argo"],
            dacs=["INCOIS", "Coriolis", "AOML"],
            variables=sorted(VariableRegistry.get_all_query_names()),
            statuses=["active", "inactive", "drifted"],
        )


# ================================================
# Deterministic float resources — NO LLM, NO chat
# Used by UI actions: marker click, float search,
# View Trajectory, Show Latest Profile, cycle history.
# ================================================

def _get_lake():
    """Return the application-scoped deterministic data-lake singleton."""
    from floatchat.api.dependencies import get_data_lake

    return get_data_lake()


def _profile_api_response(
    float_id: str, response, fallback_message: str
) -> FloatProfileAPIResponse:
    """Consolidated ChatResponse → FloatProfileAPIResponse conversion.

    Cleanup M3: identical construction was duplicated across the
    latest-profile and plot endpoints (including a dead secondary strip,
    removed here — the while-loop already removes all trailing newlines, so
    behavior is unchanged).
    """
    msg = response.message or fallback_message
    while msg.endswith("\n"):
        msg = msg[:-1]
    return FloatProfileAPIResponse(
        float_id=float_id,
        intent=response.intent,
        message=msg,
        figure=response.figure,
        figures=response.figures,
        data_summary=response.data_summary or {},
        map_data=[
            m.model_dump() if hasattr(m, "model_dump") else m
            for m in (response.map_data or [])
        ],
    )


def build_float_metadata_response(float_id: str) -> FloatMetadataAPIResponse:
    """Deterministic metadata lookup. No LLM. No chat routing."""
    clean = _normalize_float_id(float_id)
    lake = _get_lake()
    info = lake.query_metadata_lookup(clean) if lake else {"found": False, "float_id": clean}
    # Guarantee float_id is the clean form
    if isinstance(info, dict):
        info["float_id"] = clean
        info["wmo_id"] = clean

    map_data: list[dict] = []
    if info.get("last_lat") is not None and info.get("last_lon") is not None:
        map_data.append(
            {
                "float_id": clean,
                "latitude": float(info["last_lat"]),
                "longitude": float(info["last_lon"]),
                "profile_date": info.get("last_report_date"),
                "dac": info.get("dac") or info.get("institution") or "",
                "variables": info.get("sensors") or [],
                "selected": True,
                "status": info.get("status") or "unknown",
                "network": info.get("network") or "Core Argo",
                "wmo_id": clean,
                "region_tag": info.get("region_tag"),
                "manufacturer": info.get("manufacturer"),
                "profiler_type": info.get("profiler_type"),
            }
        )

    return FloatMetadataAPIResponse(float_info=info, map_data=map_data)


def build_float_trajectory_response(float_id: str) -> FloatTrajectoryAPIResponse:
    """Deterministic trajectory + full cycle history. No LLM. No chat routing.

    Returns ALL cycles for the float (safety cap 50_000). Cycles without valid
    coordinates are still included so Cycle History is complete; the map simply
    skips plotting those points.
    """
    import math
    import pandas as pd

    clean = _normalize_float_id(float_id)

    lake = _get_lake()
    df = pd.DataFrame()

    if lake and (lake.is_available() or lake.is_phase2_available()):
        if hasattr(lake, "get_profile_index"):
            df = lake.get_profile_index(float_id=clean, limit=50000)
            # Retry with alternate string forms if empty (id type mismatch)
            if df.empty:
                for alt in (f"{clean}.0", clean.lstrip("0") or clean):
                    if alt != clean:
                        df = lake.get_profile_index(float_id=alt, limit=50000)
                        if not df.empty:
                            break
        if df.empty and hasattr(lake, "_lake_root") and lake._lake_root.exists():
            try:
                conn = lake._get_connection()
                pi_path = (
                    (lake._phase2_root / "parquet" / "profile_index" / "**" / "*.parquet").as_posix()
                    if lake._phase2_root
                    and (lake._phase2_root / "parquet" / "profile_index").exists()
                    else (lake._lake_root / "**" / "*.parquet").as_posix()
                )
                sample = conn.execute(
                    f"SELECT * FROM read_parquet('{pi_path}', hive_partitioning=true) LIMIT 1"
                ).fetchdf()
                cols = [c.lower() for c in sample.columns]
                lat_col = "lat" if "lat" in cols else ("latitude" if "latitude" in cols else "lat")
                lon_col = "lon" if "lon" in cols else ("longitude" if "longitude" in cols else "lon")
                has_cycle = "cycle_number" in cols
                has_av = "available_variables" in cols
                cycle_sel = "cycle_number" if has_cycle else "CAST(NULL AS INTEGER) AS cycle_number"
                av_sel = (
                    "COALESCE(available_variables, '') AS available_variables"
                    if has_av
                    else "CAST('' AS VARCHAR) AS available_variables"
                )
                # One row per cycle when cycle_number exists; else one per date
                if has_cycle:
                    sql = (
                        f"SELECT CAST(float_id AS VARCHAR) AS float_id, "
                        f"cycle_number, "
                        f"min(date) AS date, "
                        f"arg_max({lat_col}, date) AS lat, "
                        f"arg_max({lon_col}, date) AS lon, "
                        f"COALESCE(arg_max(dac, date), '') AS dac, "
                        f"{av_sel.replace('available_variables', 'arg_max(available_variables, date)') if has_av else av_sel} "
                        f"FROM read_parquet('{pi_path}', hive_partitioning=true) "
                        f"WHERE float_id = ? "
                        f"GROUP BY float_id, cycle_number "
                        f"ORDER BY min(date) ASC"
                    )
                else:
                    sql = (
                        f"SELECT CAST(float_id AS VARCHAR) AS float_id, date, "
                        f"arg_max({lat_col}, date) AS lat, arg_max({lon_col}, date) AS lon, "
                        f"COALESCE(arg_max(dac, date), '') AS dac, "
                        f"CAST(NULL AS INTEGER) AS cycle_number, "
                        f"CAST('' AS VARCHAR) AS available_variables "
                        f"FROM read_parquet('{pi_path}', hive_partitioning=true) "
                        f"WHERE float_id = ? "
                        f"GROUP BY float_id, date ORDER BY date ASC"
                    )
                df = conn.execute(sql, [clean]).fetchdf()
            except Exception as exc:
                logger.warning("Trajectory endpoint lake query failed: %s", exc)

    if df.empty:
        return FloatTrajectoryAPIResponse(
            float_id=clean, cycle_count=0, map_data=[], distance_km=0.0, date_range={}
        )

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.sort_values(
            by=["cycle_number", "date"] if "cycle_number" in df.columns else ["date"],
            ascending=True,
        )

    # Authoritative status from registry
    status = "unknown"
    network = "Core Argo"
    try:
        fr = lake.get_float_registry(float_id=clean) if lake else None
        if fr is not None and not fr.empty:
            status = str(fr.iloc[0].get("status", "unknown") or "unknown").lower()
            sensors_raw = fr.iloc[0].get("sensors", "")
            sensor_blob = str(sensors_raw).upper()
            if any(
                k in sensor_blob
                for k in ("DOXY", "CHLA", "NITRATE", "BBP", "PH", "OPTODE", "FLUOROMETER")
            ):
                network = "BGC Argo"
    except Exception:
        pass

    # Optional per-cycle stats from levels (max depth, surface TEMP/PSAL)
    cycle_stats: dict[int, dict] = {}
    try:
        levels_path = None
        if lake._phase2_root and (lake._phase2_root / "parquet" / "levels").exists():
            levels_path = (lake._phase2_root / "parquet" / "levels" / "**" / "*.parquet").as_posix()
        elif lake._lake_root.exists():
            levels_path = (lake._lake_root / "**" / "*.parquet").as_posix()
        if levels_path:
            conn = lake._get_connection()
            stats_sql = f"""
            SELECT
                CAST(cycle_number AS INTEGER) AS cycle_number,
                max(pressure) AS max_depth,
                avg(CASE WHEN pressure <= 20 THEN COALESCE(temp_adjusted, temp) END) AS temp_surface,
                avg(CASE WHEN pressure <= 20 THEN COALESCE(psal_adjusted, psal) END) AS psal_surface
            FROM read_parquet('{levels_path}', hive_partitioning=true)
            WHERE float_id = ?
            GROUP BY cycle_number
            """
            sdf = conn.execute(stats_sql, [clean]).fetchdf()
            for _, r in sdf.iterrows():
                try:
                    cn = int(r["cycle_number"])
                except Exception:
                    continue
                cycle_stats[cn] = {
                    "max_depth": float(r["max_depth"]) if pd.notna(r.get("max_depth")) else None,
                    "temp": float(r["temp_surface"]) if pd.notna(r.get("temp_surface")) else None,
                    "salinity": float(r["psal_surface"]) if pd.notna(r.get("psal_surface")) else None,
                }
    except Exception as exc:
        logger.debug("cycle stats from levels failed: %s", exc)

    lat_col = "lat" if "lat" in df.columns else "latitude"
    lon_col = "lon" if "lon" in df.columns else "longitude"

    # Distance only over consecutive valid points
    valid_coords = []
    for _, row in df.iterrows():
        try:
            la = float(row[lat_col]) if pd.notna(row.get(lat_col)) else None
            lo = float(row[lon_col]) if pd.notna(row.get(lon_col)) else None
        except Exception:
            la = lo = None
        if la is not None and lo is not None and math.isfinite(la) and math.isfinite(lo):
            if not (la == 0.0 and lo == 0.0):
                valid_coords.append((la, lo))
    total_dist_km = 0.0
    for i in range(len(valid_coords) - 1):
        lat1, lon1 = valid_coords[i]
        lat2, lon2 = valid_coords[i + 1]
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(math.radians(lat1))
            * math.cos(math.radians(lat2))
            * math.sin(dlon / 2) ** 2
        )
        c = 2 * math.asin(math.sqrt(max(0.0, min(1.0, a))))
        total_dist_km += 6371.0 * c

    map_data: list[dict] = []
    for idx_count, (_, row) in enumerate(df.iterrows()):
        try:
            lat_val = float(row[lat_col]) if pd.notna(row.get(lat_col)) else None
            lon_val = float(row[lon_col]) if pd.notna(row.get(lon_col)) else None
        except Exception:
            lat_val = lon_val = None
        if lat_val is not None and (not math.isfinite(lat_val) or (lat_val == 0.0 and lon_val == 0.0)):
            lat_val = None
        if lon_val is not None and not math.isfinite(lon_val):
            lon_val = None

        date_val = None
        if "date" in df.columns and pd.notna(row.get("date")) and str(row.get("date")) != "NaT":
            d = row["date"]
            if hasattr(d, "strftime"):
                date_val = d.strftime("%Y-%m-%d")
            else:
                date_val = str(d)[:10]

        p_num = None
        for col in ("cycle_number", "profile_number"):
            if col in df.columns and pd.notna(row.get(col)):
                try:
                    p_num = int(float(row[col]))
                    break
                except Exception:
                    pass
        # Do NOT invent sequential numbers that skip real cycle 1 —
        # only fall back when the source has no cycle_number column at all.
        if p_num is None and "cycle_number" not in df.columns:
            p_num = idx_count + 1

        cycle_vars: list[str] = []
        if "available_variables" in df.columns and pd.notna(row.get("available_variables")):
            cycle_vars = [
                v
                for v in str(row.get("available_variables")).split()
                if v and v.upper() not in {"NAN", "NONE"}
            ]

        stats = cycle_stats.get(p_num or -1, {})

        map_data.append(
            {
                "float_id": clean,
                "latitude": lat_val if lat_val is not None else 0.0,
                "longitude": lon_val if lon_val is not None else 0.0,
                "has_position": lat_val is not None and lon_val is not None,
                "profile_date": date_val,
                "profile_number": p_num,
                "dac": str(row.get("dac", "") or ""),
                "variables": cycle_vars,
                "selected": idx_count == len(df) - 1,
                "status": status,
                "network": network,
                "wmo_id": clean,
                "max_depth": stats.get("max_depth"),
                "temp": stats.get("temp"),
                "salinity": stats.get("salinity"),
            }
        )

    min_d = None
    max_d = None
    if "date" in df.columns and not df["date"].isna().all():
        try:
            min_d = pd.to_datetime(df["date"].min()).strftime("%Y-%m-%d")
            max_d = pd.to_datetime(df["date"].max()).strftime("%Y-%m-%d")
        except Exception:
            pass

    return FloatTrajectoryAPIResponse(
        float_id=clean,
        cycle_count=len(map_data),
        map_data=map_data,
        distance_km=round(total_dist_km, 1),
        date_range={"min": min_d, "max": max_d},
    )


def build_latest_profile_response(float_id: str) -> FloatProfileAPIResponse:
    """Deterministic latest-profile plot. No LLM. No chat routing.

    Builds a ParsedIntent and runs the lake-only QueryEngine path with the
    scientific narrator forced off so this UI action never invokes an LLM.
    """
    from floatchat.models import ParsedIntent
    from floatchat.config import settings

    clean = str(float_id).strip()
    selected_profile = None
    try:
        lake = _get_lake()
        profile_index = lake.get_profile_index(float_id=clean, limit=50000)
        if not profile_index.empty and "cycle_number" in profile_index.columns:
            cycles = profile_index["cycle_number"].dropna().astype(int)
            if not cycles.empty:
                selected_profile = int(cycles.max())
    except Exception as exc:
        logger.warning("Could not resolve latest profile for %s: %s", clean, exc)

    intent = ParsedIntent(
        intent="profile_plot",
        float_id=clean,
        variables=sorted(VariableRegistry.get_all_query_names() - {"PRES"}),
        profile_number=selected_profile,
        limit=1,
    )

    # Force narrator off for this request (restore afterward)
    prev_flag = getattr(settings, "sci_narrator_enabled", True)
    settings.sci_narrator_enabled = False
    try:
        from floatchat.api.dependencies import get_runtime_query_engine

        engine = get_runtime_query_engine()
        response = engine.execute(intent)
    finally:
        settings.sci_narrator_enabled = prev_flag

    return _profile_api_response(
        clean, response, f"Latest profile for float {clean}."
    )


# ================================================
# Deterministic scientific plots catalogue + render
# No LLM. No chat.
# ================================================

_VAR_TITLES = {
    "TEMP": "Temperature",
    "PSAL": "Salinity",
    "DOXY": "Oxygen",
    "CHLA": "Chlorophyll",
    "NITRATE": "Nitrate (µmol kg⁻¹)",
    "BBP700": "Particle Backscattering 700 nm (m⁻¹)",
    "PH_IN_SITU_TOTAL": "In-situ pH (total scale)",
    "DOWNWELLING_PAR": "Downwelling PAR (µmol photons m⁻² s⁻¹)",
    "PRES": "Pressure",
}

_CORE_PLOT_VARS = ("TEMP", "PSAL", "DOXY", "CHLA", "NITRATE", "BBP700", "PH_IN_SITU_TOTAL", "DOWNWELLING_PAR")


def _normalize_float_id(float_id: str) -> str:
    clean = str(float_id).strip()
    try:
        if clean.endswith(".0") and float(clean) == int(float(clean)):
            clean = str(int(float(clean)))
    except (TypeError, ValueError):
        pass
    return clean


def _count_profiles_with_variable(lake, float_id: str, var: str) -> int:
    """Count distinct cycles with valid measurements for *var* in the levels lake."""
    import pandas as pd

    var_u = var.upper()
    col_map = {
        "TEMP": ("temp_adjusted", "temp"),
        "PSAL": ("psal_adjusted", "psal"),
        "DOXY": ("doxy_adjusted", "doxy"),
        "CHLA": ("chla_adjusted", "chla"),
        "BBP700": ("bbp700_adjusted", "bbp700"),
        "NITRATE": ("nitrate_adjusted", "nitrate"),
        "PH_IN_SITU_TOTAL": ("ph_in_situ_total_adjusted", "ph_in_situ_total"),
        "DOWNWELLING_PAR": ("downwelling_par_adjusted", "downwelling_par"),
    }
    # Prefer levels parquet for TEMP/PSAL/DOXY/CHLA
    if var_u in col_map and lake is not None:
        try:
            levels_path = None
            if lake._phase2_root and (lake._phase2_root / "parquet" / "levels").exists():
                levels_path = (lake._phase2_root / "parquet" / "levels" / "**" / "*.parquet").as_posix()
            elif getattr(lake, "_lake_root", None) and lake._lake_root.exists():
                levels_path = (lake._lake_root / "**" / "*.parquet").as_posix()
            if levels_path:
                adj, raw = col_map[var_u]
                conn = lake._get_connection()
                sql = f"""
                SELECT COUNT(DISTINCT cycle_number) AS n
                FROM read_parquet('{levels_path}', hive_partitioning=true)
                WHERE float_id = ?
                  AND (
                    ({adj} IS NOT NULL AND NOT isnan({adj}))
                    OR ({raw} IS NOT NULL AND NOT isnan({raw}))
                  )
                """
                row = conn.execute(sql, [float_id]).fetchone()
                n = int(row[0]) if row and row[0] is not None else 0
                if n > 0:
                    return n
        except Exception as exc:
            logger.debug("levels variable count failed for %s/%s: %s", float_id, var_u, exc)

    # Fallback: profile_index.available_variables token match
    try:
        if lake is not None and hasattr(lake, "get_profile_index"):
            pi = lake.get_profile_index(float_id=float_id, limit=50000)
            if pi is not None and not pi.empty and "available_variables" in pi.columns:
                count = 0
                for _, r in pi.iterrows():
                    av = str(r.get("available_variables") or "").upper().split()
                    if var_u in av or any(var_u in tok for tok in av):
                        count += 1
                return count
    except Exception as exc:
        logger.debug("profile_index variable count failed for %s/%s: %s", float_id, var_u, exc)
    return 0


def build_available_plots_response(float_id: str) -> FloatAvailablePlotsResponse:
    """List scientific variables available for a float. Deterministic. No LLM."""
    clean = _normalize_float_id(float_id)
    plots: list[AvailablePlotItem] = []
    try:
        lake = _get_lake()
    except Exception as exc:
        logger.exception("available-plots: lake init failed: %s", exc)
        return FloatAvailablePlotsResponse(float_id=clean, plots=[])
    if lake is None:
        return FloatAvailablePlotsResponse(float_id=clean, plots=[])

    # Discover candidate variables from registry sensors + profile_index tokens + levels
    candidates: list[str] = []
    try:
        info = lake.query_metadata_lookup(clean) if lake else {}
        sensors = info.get("sensors") or []
        sensor_blob = " ".join(str(s).upper() for s in sensors)
        # Map sensors → Argo vars
        if any(k in sensor_blob for k in ("CTD", "TEMP", "PSAL")) or not sensors:
            candidates.extend(["TEMP", "PSAL"])
        if any(k in sensor_blob for k in ("OPTODE", "DOXY", "OXYGEN")):
            candidates.append("DOXY")
        if any(k in sensor_blob for k in ("FLUOROMETER", "CHLA", "CHLOROPHYLL")):
            candidates.append("CHLA")
        if any(k in sensor_blob for k in ("NITRATE", "SUNA", "ISUS")):
            candidates.append("NITRATE")
        if any(k in sensor_blob for k in ("BBP", "BACKSCATTER")):
            candidates.append("BBP700")
        if any(k in sensor_blob for k in ("PH",)):
            candidates.append("PH_IN_SITU_TOTAL")
    except Exception:
        pass

    # Always probe core lake vars
    for v in _CORE_PLOT_VARS:
        if v not in candidates:
            candidates.append(v)

    seen: set[str] = set()
    for var in candidates:
        if var in seen:
            continue
        seen.add(var)
        n = _count_profiles_with_variable(lake, clean, var)
        if n > 0:
            plots.append(
                AvailablePlotItem(
                    variable=var,
                    title=_VAR_TITLES.get(var, var),
                    profiles=n,
                )
            )

    # Stable scientific order
    order = {v: i for i, v in enumerate(_CORE_PLOT_VARS)}
    plots.sort(key=lambda p: order.get(p.variable, 100))

    return FloatAvailablePlotsResponse(float_id=clean, plots=plots)


def build_float_plot_response(
    float_id: str, var: str, profile_number: int | None
) -> FloatProfileAPIResponse:
    """Render a deterministic profile plot for one variable. No LLM. No chat."""
    from floatchat.models import ParsedIntent
    from floatchat.config import settings

    clean = _normalize_float_id(float_id)
    # A plot request without an explicit cycle uses the latest known cycle as
    # a backward-compatible default. It never silently retrieves 100 cycles.
    selected_profile = profile_number
    if selected_profile is None:
        try:
            lake = _get_lake()
            profile_index = lake.get_profile_index(float_id=clean, limit=50000)
            if not profile_index.empty and "cycle_number" in profile_index.columns:
                cycles = profile_index["cycle_number"].dropna().astype(int)
                if not cycles.empty:
                    selected_profile = int(cycles.max())
        except Exception as exc:
            logger.warning("Could not resolve latest profile for %s: %s", clean, exc)

    intent = ParsedIntent(
        intent="profile_plot",
        float_id=clean,
        variables=[var],
        profile_number=selected_profile,
        limit=1,
    )

    prev_flag = getattr(settings, "sci_narrator_enabled", True)
    settings.sci_narrator_enabled = False
    try:
        from floatchat.api.dependencies import get_runtime_query_engine

        engine = get_runtime_query_engine()
        response = engine.execute(intent)
    finally:
        settings.sci_narrator_enabled = prev_flag

    response.data_summary = {
        **(response.data_summary or {}),
        "profile_number": selected_profile,
        "float_id": clean,
    }
    title = _VAR_TITLES.get(var, var)
    return _profile_api_response(
        clean, response, f"{title} profile for float {clean}."
    )
