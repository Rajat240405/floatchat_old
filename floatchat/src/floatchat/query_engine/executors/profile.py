"""Data-query executor: profile plots, region search, series, comparisons.

Extracted verbatim from the pre-M4 ``query_engine/engine.py`` monolith
(Milestone 4 decomposition). Executes every non-spatial, non-metadata data
intent (region_search, profile_plot, time_series, hovmoller, ts_diagram,
comparison, comparison_plot) exclusively against the injected local data
lake, renders figures through the injected visualization engine, and builds
the scientific explanation. When the lake is unavailable it defers to the
legacy GDAC executor only if remote fallback is explicitly enabled.
"""

from __future__ import annotations

import dataclasses
import logging
import time
from typing import TYPE_CHECKING

import pandas as pd

from floatchat.config import settings
from floatchat.exceptions import FloatChatError
from floatchat.models import ChatResponse, MapData, ParsedIntent
from floatchat.query_engine import response_builder
from floatchat.query_engine.executors.legacy import execute_via_legacy_gdac
from floatchat.query_engine.helpers import _figure_metrics
from floatchat.scientific_explanation.verification import (
    build_pipeline_trace,
    build_verification_section,
)

if TYPE_CHECKING:
    from floatchat.query_engine.dispatch import ExecutionDeps

logger = logging.getLogger(__name__)


def execute_data_query_via_lake(
    deps: ExecutionDeps,
    intent: ParsedIntent,
    pipeline_t0: float,
) -> ChatResponse:
    """Execute a data query EXCLUSIVELY from DuckDBDataLake.

    Priority 1A: No GDAC fallback. Zero rows = explain, don't download.
    Priority 1A: No max_profiles=5 cap. Uses data_lake_max_profiles.
    Priority 1D: Zero-result explanations with availability probe.
    """
    from floatchat.data_lake.base import LakeQueryCriteria

    t_planning_start = time.perf_counter()
    lake = deps.lake
    if lake is None or not (lake.is_available() or lake.is_phase2_available()):
        # Priority 1A: Check if remote fallback is allowed
        if settings.allow_remote_gdac_fallback and settings.enable_gdac_runtime:
            logger.warning(
                "Data lake unavailable; FALLING BACK to GDAC pipeline — "
                "this makes remote HTTP calls!"
            )
            return execute_via_legacy_gdac(deps, intent, pipeline_t0)

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
    # A profile-aware request must never use the broad multi-profile limit.
    # The cycle predicate is also applied inside DuckDB via criteria.
    query_limit = (
        1
        if intent.profile_number is not None or intent.intent == "profile_plot"
        else settings.data_lake_max_profiles
    )

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

    t_planning_end = time.perf_counter()
    logger.info(
        "PIPELINE planning: %.3fs float=%s profile=%s vars=%s limit=%d",
        t_planning_end - t_planning_start,
        intent.float_id,
        intent.profile_number,
        intent.variables,
        query_limit,
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

    t_df_start = time.perf_counter()
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

    logger.info(
        "PIPELINE dataframe_postprocessing: %.3fs rows_in=%d rows_out=%d columns=%d",
        time.perf_counter() - t_df_start,
        lake_result.total_measurements,
        len(df),
        len(df.columns),
    )

    # Build map_data from the ACTUAL filtered DataFrame — guarantees map
    # markers match the data that was queried and returned. Previous approach
    # used a separate get_map_markers query which could return different
    # floats due to type mismatches or filter inconsistencies.
    map_data = response_builder._build_map_data_from_lake(lake, df)
    logger.info("Map markers from filtered data: %d markers", len(map_data))

    # Sprint 1 (Bug 4): region_search is a discovery query — the DataFrame is
    # profile-capped (data_lake_max_profiles, default 100) so the figure stays
    # plottable, but the map must show EVERY matching float ("The backend
    # should return every matching float"). Union the uncapped lake marker set
    # (`get_map_markers` has no profile limit) with the df-derived markers so
    # floats beyond the profile cap still appear on the map. Enrichment is
    # best-effort: a failure here must never fail the query itself.
    if intent.intent == "region_search" and hasattr(lake, "get_map_markers"):
        try:
            covered = {m.float_id for m in map_data}
            for marker in lake.get_map_markers(criteria):
                fid = str(marker.get("float_id", ""))
                if not fid or fid in covered:
                    continue
                covered.add(fid)
                lat_v = marker.get("lat")
                lon_v = marker.get("lon")
                p_date = marker.get("profile_date")
                map_data.append(
                    MapData(
                        float_id=fid,
                        latitude=float(lat_v) if lat_v is not None else None,
                        longitude=float(lon_v) if lon_v is not None else None,
                        profile_date=str(p_date)[:10] if p_date else None,
                        dac=str(marker.get("dac", "")),
                        variables=[],
                        selected=False,
                        status="unknown",
                        network=None,
                        wmo_id=fid,
                        region_tag=intent.region,
                    )
                )
            logger.info(
                "Region-search map markers after union: %d markers", len(map_data)
            )
        except Exception as exc:
            logger.warning("Region-search marker union failed: %s", exc)

    # --- Visualization --- #
    t_viz_t0 = time.perf_counter()
    try:
        figure = deps.viz.render(intent, df)
    except FloatChatError:
        logger.exception("Visualization failed for data lake result")
        return ChatResponse(
            intent=intent.intent,
            message="Data retrieved from lake but visualization failed.",
            data_summary=response_builder._build_lake_summary(lake_result, df),
            map_data=map_data,
        )
    t_viz_end = time.perf_counter()

    # --- Per-variable figures for the redesigned stacked plot drawer --- #
    # A single-variable request already has exactly the figure needed by
    # both the main response and the drawer. Reuse it instead of traversing
    # the DataFrame and rebuilding an equivalent Plotly figure.
    #
    # For multi-variable requests, retain the combined main figure because
    # the existing chat UI consumes response.figure, and additionally build
    # one standalone figure per variable for the drawer.
    figures: list[dict] | None = None
    if len(intent.variables) == 1 and figure is not None:
        if isinstance(figure, dict):
            figure.setdefault("variable", intent.variables[0])
        figures = [figure]
        logger.info(
            "PIPELINE per_variable_plots: reused_combined_single_variable "
            "variable=%s figures=1",
            intent.variables[0],
        )
    else:
        per_var_fn = getattr(deps.viz, "render_per_variable", None)
        if callable(per_var_fn):
            try:
                figures = per_var_fn(intent, df) or None
            except Exception as exc:
                logger.warning("Per-variable figure render failed: %s", exc)
                figures = None

    combined_metrics = _figure_metrics([figure] if figure else None)
    drawer_metrics = _figure_metrics(figures)
    logger.info(
        "PIPELINE plot_output: render_total=%.3fs combined_traces=%d "
        "combined_points=%d combined_payload=%.2fKB drawer_traces=%d "
        "drawer_points=%d drawer_payload=%.2fKB rows_plotted_input=%d",
        t_viz_end - t_viz_t0,
        combined_metrics[0],
        combined_metrics[1],
        combined_metrics[2] / 1024,
        drawer_metrics[0],
        drawer_metrics[1],
        drawer_metrics[2] / 1024,
        len(df),
    )

    # --- Scientific Explanation --- #
    t_sci_t0 = time.perf_counter()
    data_summary = response_builder._build_lake_summary(lake_result, df)
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
    explanation = deps.explanation_engine.generate_explanation(
        intent, [], intent.variables, data_summary, df=df
    )
    # User-facing wording describes the scientific object being shown,
    # not storage/query implementation details.
    profile_date = None
    if "date" in df.columns and not df["date"].isna().all():
        profile_date = pd.to_datetime(df["date"].min()).strftime("%Y-%m-%d %H:%M UTC")
    if intent.profile_number is not None:
        cycle_text = f"Cycle {intent.profile_number}"
    elif lake_result.unique_profiles == 1 and "cycle_number" in df.columns:
        cycle_text = f"Cycle {int(df['cycle_number'].iloc[0])}"
    else:
        cycle_text = "the latest available profile"
    selected_float_id = intent.float_id
    if selected_float_id is None and "float_id" in df.columns and not df.empty:
        selected_float_id = str(df["float_id"].iloc[0])
    float_text = f" for Float {selected_float_id}" if selected_float_id else ""
    missing_text = ""
    # Sprint 1 (Bug 7): a comparison must name every float actually compared —
    # not just the primary float_id, which made one-float results read as a
    # single-float profile. Also disclose requested floats that returned no
    # data so "compare A and B" can never silently degrade to only A.
    if (
        intent.intent in ("comparison", "comparison_plot")
        and len(intent.comparison_float_ids) >= 2
        and "float_id" in df.columns
    ):
        returned_ids = sorted(df["float_id"].astype(str).unique())
        if returned_ids:
            float_text = f" for Floats {', '.join(returned_ids)}"
        missing_ids = [f for f in intent.comparison_float_ids if f not in set(returned_ids)]
        if missing_ids:
            missing_text = (
                f" No matching"
                f"{' ' + ', '.join(intent.variables) if intent.variables else ''}"
                f" data was found for: {', '.join(missing_ids)}."
            )
    date_text = f" collected on {profile_date}" if profile_date else ""
    if intent.intent == "region_search" and lake_result.unique_floats > 1:
        # Sprint 1 (Bug 4): a region discovery response must describe the
        # whole match set — naming a single float read as if the query had
        # collapsed to one float. The "latest profile" reduction only applies
        # when explicitly requested (profile_number / single-float queries).
        region_label = (intent.region or "the requested region").replace("_", " ").title()
        base_message = (
            f"Showing {', '.join(intent.variables) or 'the requested variables'} "
            f"profiles for {lake_result.unique_floats} floats in {region_label} "
            f"({lake_result.unique_profiles} profiles total).{missing_text}"
        )
    else:
        base_message = (
            f"Showing {', '.join(intent.variables) or 'the requested variables'} "
            f"profile{float_text}, {cycle_text}{date_text}.{missing_text}"
        )
    if lake_result.unique_profiles > 1:
        base_message += " Additional profile history is available for comparison."
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
