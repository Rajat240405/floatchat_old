"""Legacy GDAC executor: remote metadata search + live NetCDF downloads.

Extracted verbatim from the pre-M4 ``query_engine/engine.py`` monolith
(Milestone 4 decomposition). This path makes remote HTTP calls to
data-argo.ifremer.fr and is reachable ONLY when
FLOATCHAT_ALLOW_REMOTE_GDAC_FALLBACK=True (default: False). It also hosts the
legacy-pipeline support functions (intent→criteria mapping, metadata group
search, core/BGC record pairing) that nothing else uses.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

import pandas as pd

from floatchat.config import settings
from floatchat.exceptions import FloatChatError
from floatchat.models import ChatResponse, ParsedIntent, SearchCriteria
from floatchat.query_engine import response_builder
from floatchat.query_engine.helpers import (
    _extract_float_cycle_key,
    _extract_float_id_from_path,
)
from floatchat.scientific_explanation.verification import (
    build_pipeline_trace,
    build_verification_section,
)
from floatchat.variable_registry.registry import VariableRegistry

if TYPE_CHECKING:
    from floatchat.query_engine.dispatch import ExecutionDeps

logger = logging.getLogger(__name__)


def execute_via_legacy_gdac(
    deps: ExecutionDeps,
    intent: ParsedIntent,
    pipeline_t0: float,
) -> ChatResponse:
    """Legacy GDAC pipeline — makes remote HTTP calls to data-argo.ifremer.fr.

    This path is ONLY accessible when FLOATCHAT_ALLOW_REMOTE_GDAC_FALLBACK=True.
    It is retained for backwards compatibility and for the offline phase2_builder.
    """
    logger.warning("Executing via LEGACY GDAC pipeline — remote HTTP calls will be made!")

    # --- Phase 21: Retrieval Planning --- #
    plan = deps.planner.plan(intent.variables or [])
    logger.info("Retrieval Plan: %s", plan.reasoning)

    # --- Step 1: Metadata search --- #
    t0 = time.perf_counter()
    criteria = _intent_to_criteria(intent)
    search_groups = _search_metadata_groups(deps, intent, criteria, plan)
    records = [record for group_records, _ in search_groups for record in group_records]
    t1 = time.perf_counter()
    logger.info("Metadata search: %.3fs (%d records)", t1 - t0, len(records))

    if not records:
        logger.warning("No metadata records matched criteria: %s", criteria)
        suggestion = response_builder._get_error_suggestion(intent)
        return ChatResponse(
            intent=intent.intent,
            message=f"No Argo profiles matched your query criteria. {suggestion}",
            data_summary={"matched_records": 0},
        )

    map_data = response_builder._build_map_data(records)

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
            ncd = deps.repository.fetch(rec.file)
            t_fetch_t1 = time.perf_counter()
            logger.info("NetCDF fetch: %.3fs (%s) [GDAC HTTP]", t_fetch_t1 - t_fetch_t0, rec.file)

            t_read_t0 = time.perf_counter()
            try:
                df = deps.reader.read(ncd, variables)
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
        figure = deps.viz.render(intent, combined)
    except FloatChatError:
        logger.exception("Visualization failed")
        return ChatResponse(
            intent=intent.intent,
            message="Data retrieved but visualization failed.",
            data_summary=response_builder._build_summary(combined, records),
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

    base_message = response_builder._build_message(intent, records, combined)
    data_summary = response_builder._build_summary(combined, records)
    explanation = deps.explanation_engine.generate_explanation(
        intent, records, intent.variables, data_summary, df=combined
    )
    final_message = f"{base_message}\n\n{explanation}"

    data_summary.update({
        "verification": verification,
        "pipeline_trace": pipeline_trace,
        "suggestions": response_builder._generate_suggestions(intent, records),
        "derived_insights": {},
    })

    return ChatResponse(
        intent=intent.intent,
        message=final_message,
        figure=figure,
        data_summary=data_summary,
        map_data=map_data,
    )


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
    deps: ExecutionDeps,
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
                fid_bio = deps.metadata.search(f_crit.model_copy(update={"parameters": bgc_vars if plan.metadata_index == "both" else criteria.parameters}))
            if plan.metadata_index in ("core", "both") or plan.requires_core:
                fid_core = deps.metadata.search(f_crit.model_copy(update={"parameters": core_vars if plan.metadata_index == "both" else criteria.parameters}))
            if not fid_bio and not fid_core:
                fid_core = deps.metadata.search(f_crit.model_copy(update={"parameters": []}))
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
        return [(deps.metadata.search(criteria), intent.variables)]

    pair_limit = max(criteria.limit, 10)
    core_records: list[Any] = []
    bio_records: list[Any] = []
    if core_vars:
        core_criteria = criteria.model_copy(update={"parameters": core_vars, "limit": pair_limit})
        core_records = deps.metadata.search(core_criteria)
    if bgc_vars:
        bio_criteria = criteria.model_copy(update={"parameters": bgc_vars, "limit": pair_limit})
        bio_records = deps.metadata.search(bio_criteria)

    if core_records and bio_records:
        core_records, bio_records = _pair_by_float_cycle(
            core_records, bio_records, criteria.limit
        )

    groups: list[tuple[list[Any], list[str]]] = []
    if core_records and core_vars:
        groups.append((core_records, core_vars))
    if bio_records and bgc_vars:
        groups.append((bio_records, bgc_vars))

    return groups


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
