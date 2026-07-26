"""Response construction helpers for the QueryEngine execution layer.

Extracted verbatim from the pre-M4 ``query_engine/engine.py`` monolith
(Milestone 4 decomposition). Single home for all ChatResponse payload
construction: map markers (lake DataFrames and legacy metadata records),
data summaries, human-readable messages, and follow-up suggestions.
Not part of the public API.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from floatchat.models import MapData, ParsedIntent
from floatchat.ontology.sensors import BGC_VARIABLE_MARKER_TOKENS, NETWORK_BGC, NETWORK_CORE
from floatchat.query_engine.helpers import (
    _extract_cycle_from_filename,
    _extract_float_id_from_path,
)

logger = logging.getLogger(__name__)


def _build_map_data_from_lake(lake: Any, df: pd.DataFrame) -> list[MapData]:
    """Build map markers from lake DataFrame and registry status."""
    markers: list[MapData] = []
    registry_status: dict[str, str] = {}
    try:
        registry = lake.get_float_registry() if lake else pd.DataFrame()
        if registry is not None and not registry.empty:
            for _, registry_row in registry.iterrows():
                fid = str(registry_row.get("float_id", ""))
                status = str(registry_row.get("status", "") or "").strip().lower()
                if fid and status and status not in {"unknown", "none", "nan"}:
                    registry_status[fid] = status
    except Exception as exc:
        logger.debug("Float registry status lookup failed: %s", exc)
    seen: set[str] = set()
    # Pre-compute which floats carry any BGC variable, for Network derivation.
    # Ontology 2.0 (Phase 1): marker tokens come from the domain ontology;
    # contents are unchanged.
    _BGC_VAR_MARKERS = BGC_VARIABLE_MARKER_TOKENS
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
        status = registry_status.get(fid)
        if status is None and date_val is not None and pd.notna(date_val):
            report_ts = pd.Timestamp(date_val)
            if report_ts.tzinfo is None:
                report_ts = report_ts.tz_localize("UTC")
            age_days = (pd.Timestamp.now(tz="UTC") - report_ts).days
            status = "active" if age_days <= 365 else "inactive"
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
                status=status or "inactive",
                network=NETWORK_BGC if fid in bgc_floats else NETWORK_CORE,
                wmo_id=fid,
            )
        )
    return markers


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
            p_num = _extract_cycle_from_filename(str(rec.file))
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


def _get_error_suggestion(intent: ParsedIntent) -> str:
    """Return a helpful suggestion when no profiles are found."""
    if intent.variables and "TEMP" in intent.variables:
        return "This float may only contain BGC variables. Try requesting DOXY or CHLA instead."
    if intent.year and intent.year < 2015:
        return "Try a more recent year (many BGC floats were deployed after 2015)."
    if intent.region:
        return "Try broadening the region or removing the year filter."
    return "Try another year, different region, or a different variable."


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


def _calculate_derived_insights(
    df: pd.DataFrame, variables: list[str]
) -> dict[str, Any]:
    """Deprecated: Use ScientificExplanationEngine._compute_stats instead."""
    return {}
