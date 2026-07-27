"""Deterministic scientific narration (Phase 5).

Turns the resolved intent + engine facts into one natural opening sentence
(+ one static, honest clause about the visualization form). Phrasing is
templated only from grounded facts: canonical variables (ontology display
labels), regions (ontology display names), float ids, and result counts.

Nothing here computes or asserts anything about the data itself — that is
the summary module's job.
"""

from __future__ import annotations

from typing import Any

from floatchat.models import ParsedIntent
from floatchat.ontology.regions import REGIONS
from floatchat.ontology.variables import VARIABLES


def variable_phrase(code: str) -> str:
    """Human phrase for a canonical variable, derived from the ontology.

    "TEMP" → "temperature", "DOXY" → "dissolved oxygen",
    "PH_IN_SITU_TOTAL" → "pH". Falls back to the raw code.
    """
    definition = VARIABLES.get(code)
    if definition is None or not definition.display_label:
        return code
    phrase = definition.display_label.split("(")[0].strip().lower()
    # Friendly normalisations that stay faithful to the ontology labels.
    return {
        "practical salinity": "salinity",
        "sea water temperature": "temperature",
        "ph": "pH",
    }.get(phrase, phrase)


def variables_phrase(variables: list[str] | tuple[str, ...]) -> str:
    """Oxford-joined human phrase: "temperature and dissolved oxygen"."""
    phrases = [variable_phrase(v) for v in variables]
    if not phrases:
        return "the requested measurements"
    if len(phrases) == 1:
        return phrases[0]
    if len(phrases) == 2:
        return f"{phrases[0]} and {phrases[1]}"
    return ", ".join(phrases[:-1]) + f", and {phrases[-1]}"


def region_name(code: str) -> str:
    """Display name for an ontology region code ("arabian_sea" → "Arabian Sea")."""
    region = REGIONS.get(code)
    return region.display_name if region is not None else code.replace("_", " ").title()


def _cycle_text(intent: ParsedIntent, summary: dict[str, Any]) -> str:
    if intent.profile_number is not None:
        return f" (cycle {intent.profile_number})"
    if summary.get("unique_profiles") == 1:
        return " (the available cycle)"
    return " (the latest available cycle)"


def _datetime_span(summary: dict[str, Any]) -> str:
    span = summary.get("date_range") or {}
    dmin, dmax = span.get("min"), span.get("max")
    if dmin and dmax:
        return f" between {dmin} and {dmax}"
    if dmin:
        return f" from {dmin}"
    return ""


#: One static, honest clause per visualization form (no data claims).
_FORM_CLAUSE = {
    "profile_plot": "The visualization shows how the measurements change with depth and highlights the vertical structure of the water column.",
    "region_search": "The visualization shows how the measurements change with depth and highlights the vertical structure of the water column.",
    "comparison_plot": "All matching observations within the requested scope are included.",
    "trajectory": "Each marker is a recorded profile location along the float's drift path.",
    "time_series": "The visualization tracks how the measurements evolve through time.",
    "hovmoller": "The visualization tracks the measurements across both depth and time.",
    "ts_diagram": "Each point is one observation placed in temperature–salinity space.",
    "nearest_float": "Map markers show the matching floats and their latest positions.",
    "radius_search": "Map markers show the matching floats and their latest positions.",
    "count_aggregate": "",
    "metadata_lookup": "",
}


def narrate(intent: ParsedIntent, summary: dict[str, Any], matched: int) -> str:
    """One natural opening line for a successful data response."""
    vp = variables_phrase(list(intent.variables))
    clause = _FORM_CLAUSE.get(intent.intent, "")
    tail = f" {clause}" if clause else ""

    if intent.intent in ("profile_plot", "region_search"):
        if intent.float_id:
            return (
                f"Showing the {vp} profile for **Float {intent.float_id}**"
                f"{_cycle_text(intent, summary)}.{tail}"
            )
        if intent.region:
            floats = summary.get("unique_floats")
            profiles = summary.get("unique_profiles")
            counts = (
                f" — {profiles} profiles from {floats} floats"
                if floats and profiles
                else ""
            )
            return (
                f"Showing the {vp} profiles across the **{region_name(intent.region)}**"
                f"{counts} within the requested scope.{tail}"
            )
        if intent.lat is not None and intent.lon is not None:
            return (
                f"Showing the {vp} profiles near "
                f"({intent.lat:.2f}, {intent.lon:.2f}).{tail}"
            )
        return f"Showing the {vp} profiles within the requested scope.{tail}"

    if intent.intent in ("comparison_plot", "comparison"):
        pairs = list(intent.comparison_float_ids) or []
        region_pairs = list(intent.comparison_regions) or []
        if len(pairs) >= 2:
            sides = " and ".join(f"**Float {p}**" for p in pairs[:2])
        elif len(region_pairs) >= 2:
            sides = f"the **{region_name(region_pairs[0])}** and the **{region_name(region_pairs[1])}**"
        else:
            sides = "the requested subjects"
        return (
            f"Comparing {vp} between {sides} using all matching observations "
            f"within the requested scope.{tail}"
        )

    if intent.intent == "trajectory":
        points = summary.get("trajectory_points") or matched
        span = _datetime_span(summary)
        return f"Showing the drift trajectory of **Float {intent.float_id}** — {points} recorded profile locations{span}.{tail}"

    if intent.intent == "nearest_float":
        detail = (
            f" to ({intent.lat:.2f}, {intent.lon:.2f})"
            if intent.lat is not None and intent.lon is not None
            else ""
        )
        return f"Found **{matched}** float{'s' if matched != 1 else ''} nearest{detail}.{tail}"

    if intent.intent == "radius_search":
        detail = (
            f" of ({intent.lat:.2f}, {intent.lon:.2f})"
            if intent.lat is not None and intent.lon is not None
            else ""
        )
        radius = f" within {intent.radius_km:.0f} km" if intent.radius_km else ""
        return f"Found **{matched}** float{'s' if matched != 1 else ''}{radius}{detail}.{tail}"

    if intent.intent == "count_aggregate":
        return f"Counting all matching {vp} observations within the requested scope."

    if intent.intent == "metadata_lookup":
        return f"Metadata summary for **Float {intent.float_id}** from the local Argo metadata index."

    if intent.intent == "time_series":
        scope = f" for **Float {intent.float_id}**" if intent.float_id else (f" across the **{region_name(intent.region)}**" if intent.region else "")
        return f"Showing how {vp} evolves over time{scope}.{_datetime_span(summary)}.{tail}"

    if intent.intent == "hovmoller":
        scope = f" for **Float {intent.float_id}**" if intent.float_id else (f" across the **{region_name(intent.region)}**" if intent.region else "")
        return f"Showing a time–depth (Hovmöller) view of {vp}{scope}.{tail}"

    if intent.intent == "ts_diagram":
        scope = f" for **Float {intent.float_id}**" if intent.float_id else (f" across the **{region_name(intent.region)}**" if intent.region else "")
        return f"Showing the temperature–salinity (T–S) relationship{scope}.{tail}"

    # Unknown/new intent: a sober generic line rather than a system log.
    return f"Results for your request ({matched} matching record{'s' if matched != 1 else ''})."
