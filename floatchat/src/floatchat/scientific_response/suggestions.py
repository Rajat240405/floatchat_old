"""Deterministic follow-up suggestions (Phase 5).

3–5 next questions derived only from the current intent, its grounded
entities, and the ontology's variable vocabulary (never an LLM). Suggestions
are *questions*, never data claims.
"""

from __future__ import annotations

from floatchat.models import ParsedIntent
from floatchat.ontology.variables import LEVELS_VARIABLE_ORDER

from .narration import region_name, variable_phrase

#: Variable-specific concept prompts ("Explain the thermocline.").
_CONCEPT_HINT = {
    "TEMP": "Explain the thermocline in more detail.",
    "PSAL": "Explain the halocline in more detail.",
    "DOXY": "Explain the oxygen minimum zone.",
    "CHLA": "Explain the deep chlorophyll maximum.",
}


def _alternate_variable(current: list[str]) -> str | None:
    for code in LEVELS_VARIABLE_ORDER:
        if code not in current:
            return code
    return None


def suggest(intent: ParsedIntent, *, has_context: bool = False) -> list[str]:
    """3–5 deterministic follow-ups for a successful data response."""
    out: list[str] = []
    fid = intent.float_id
    var = intent.variables[0] if intent.variables else None
    varp = variable_phrase(var) if var else None
    alt = _alternate_variable(list(intent.variables))
    altp = variable_phrase(alt) if alt else None

    if intent.intent in ("profile_plot", "region_search", "ts_diagram", "hovmoller"):
        if fid:
            out.append(f"Compare this profile with an earlier cycle of Float {fid}.")
        if altp:
            if fid:
                out.append(f"Plot {altp} alongside {varp or 'the current variable'} for Float {fid}.")
            else:
                out.append(f"Show {altp} for the same scope.")
        if fid:
            out.append(f"Show the trajectory of Float {fid}.")
        if var in _CONCEPT_HINT:
            out.append(_CONCEPT_HINT[var])
        if intent.region:
            out.append(f"Compare {varp or 'this variable'} with another region.")
        if not out:
            out.append("Show the matching floats on the map.")
    elif intent.intent in ("comparison_plot", "comparison"):
        pairs = list(intent.comparison_regions) or []
        if altp:
            out.append(f"Compare {altp} for the same subjects.")
        if len(pairs) >= 2:
            out.append("Restrict the comparison to the summer months.")
        if varp:
            out.append(f"Show how {varp} changes with depth in both subjects.")
        out.append("Summarize the statistical differences between the two sides.")
    elif intent.intent == "trajectory":
        if fid:
            out.append(f"Show a temperature profile for Float {fid}.")
            out.append(f"Show the most recent position of Float {fid} on the map.")
        if fid and varp:
            out.append(f"Show how {varp} varied for Float {fid} during this period.")
        out.append("Compare this float's path with another float.")
    elif intent.intent == "metadata_lookup":
        if fid:
            out.append(f"Plot the temperature profile of Float {fid}.")
            out.append(f"Show the trajectory of Float {fid}.")
            out.append(f"List the available variables for Float {fid}.")
            out.append(f"Show the latest profile of Float {fid}.")
    elif intent.intent in ("nearest_float", "radius_search"):
        if varp:
            out.append(f"Plot the {varp} profile of the nearest float.")
        out.append("Compare two of these floats.")
        out.append("Show their recent trajectories.")
        out.append("Restrict the search to the most recent year.")
    elif intent.intent == "count_aggregate":
        out.append("Plot the underlying profiles.")
        out.append("Show the matching floats on the map.")
        out.append("Break the count down by year.")
    elif intent.intent == "time_series":
        if varp:
            out.append(f"Show the {varp} depth profile for the same scope.")
        if altp:
            out.append(f"Add {altp} to the time series.")
        out.append("Restrict the series to a single season.")
        out.append("Compare the same period with another year.")

    # De-duplicate, always 3–5 when anything applies.
    seen: set[str] = set()
    unique: list[str] = []
    for item in out:
        if item and item not in seen:
            seen.add(item)
            unique.append(item)
    return unique[:5]
