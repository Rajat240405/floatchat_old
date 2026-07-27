"""Deterministic follow-up suggestions (Phase 5).

3–5 next questions derived only from the current intent, its grounded
entities, and the ontology's variable vocabulary (never an LLM). Suggestions
are *questions*, never data claims.
"""

from __future__ import annotations

from typing import Any

from floatchat.models import ParsedIntent
from floatchat.ontology.regions import INDIA_QUERY_REGIONS
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


#: Plottable-variable phrase for a sensor code from the metadata payload.
#: Keys are matched against the upper-cased sensor string.
_SENSOR_PLOT_PHRASE: tuple[tuple[str, str], ...] = (
    ("CTD", "temperature"),
    ("OPTODE", "dissolved oxygen"),
    ("DOXY", "dissolved oxygen"),
    ("OXYGEN", "dissolved oxygen"),
    ("FLUOROMETER", "chlorophyll"),
    ("CHLA", "chlorophyll"),
    ("NITRATE", "nitrate"),
    ("NO3", "nitrate"),
    ("SUNA", "nitrate"),
    ("ISUS", "nitrate"),
    ("BACKSCATTER", "particle backscattering"),
    ("BBP", "particle backscattering"),
    ("PH", "pH"),
    ("PAR", "PAR"),
    ("IRRADIANCE", "downwelling irradiance"),
)


def _sensor_plot_phrases(sensors: list[str]) -> list[str]:
    """Ordered, de-duplicated plottable-variable phrases for a sensor list.

    When the payload carries BGC sensors alongside the base CTD, the CTD's
    temperature suggestion is dropped — the BGC payload is what distinguishes
    the float, and temperature plotting is offered by every other trio.
    """
    phrases: list[str] = []
    for sensor in sensors:
        code = str(sensor).strip().upper()
        if not code:
            continue
        for marker, phrase in _SENSOR_PLOT_PHRASE:
            if marker in code:
                if phrase not in phrases:
                    phrases.append(phrase)
                break
    if "temperature" in phrases and len(phrases) > 1:
        phrases.remove("temperature")
    return phrases


#: Follow-up trio for a float once a metadata fact was answered — the
#: natural next explorations of that float (Sprint 4, Bug 5).
def _explore_float_trio(fid: str) -> list[str]:
    return [
        f"Show the trajectory of Float {fid}.",
        f"Show the latest profile of Float {fid}.",
        f"List the installed sensors on Float {fid}.",
    ]


def suggest(
    intent: ParsedIntent,
    *,
    has_context: bool = False,
    metadata_focus: str | None = None,
    float_info: dict[str, Any] | None = None,
) -> list[str]:
    """3–5 deterministic follow-ups for a successful data response.

    Sprint 4: ``metadata_focus`` + ``float_info`` make metadata answers
    field-aware — the follow-ups continue the scientist's actual line of
    questioning (operator → explore the float; sensors → plot what those
    sensors measure; last_seen → recent activity) instead of a fixed card.
    """
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
        focus = metadata_focus or "metadata_summary"
        if fid and focus == "metadata_summary":
            out.append(f"Plot the temperature profile of Float {fid}.")
            out.append(f"Show the trajectory of Float {fid}.")
            out.append(f"List the available variables for Float {fid}.")
            out.append(f"Show the latest profile of Float {fid}.")
        elif fid and focus == "last_seen":
            out.append(f"Show the latest profile of Float {fid}.")
            out.append(f"Show the recent trajectory of Float {fid}.")
            out.append(f"Check the operational status of Float {fid}.")
        elif fid and focus in ("sensors", "variables"):
            sensors = list((float_info or {}).get("sensors") or [])
            phrases = _sensor_plot_phrases(sensors)
            for phrase in phrases[:2]:
                out.append(f"Plot the {phrase} profile of Float {fid}.")
            if phrases:
                out.append(f"List the available variables for Float {fid}.")
            else:
                # Sensor payload unavailable — offer safe exploration.
                out.append(f"Show the latest profile of Float {fid}.")
                out.append(f"Show the trajectory of Float {fid}.")
                out.append(f"Plot the temperature profile of Float {fid}.")
        elif fid:
            # operator / dac / institution / status / profiles / cycles /
            # battery / platform / deployment → explore the float.
            out.extend(_explore_float_trio(fid))
    elif intent.intent in ("nearest_float", "radius_search"):
        if varp:
            out.append(f"Plot the {varp} profile of the nearest float.")
        out.append("Compare two of these floats.")
        out.append("Show their recent trajectories.")
        out.append("Restrict the search to the most recent year.")
    elif intent.intent == "count_aggregate":
        if intent.float_id:
            # Sprint 4: a float-scoped count answers "how many profiles?" —
            # the follow-ups explore that float (Bug 3/5 trio).
            out.extend(_explore_float_trio(intent.float_id))
        else:
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

    # De-duplicate; focused metadata trios are exactly 3 by construction,
    # other branches keep their established 3–5 items.
    seen: set[str] = set()
    unique: list[str] = []
    for item in out:
        if item and item not in seen:
            seen.add(item)
            unique.append(item)
    return unique[:5]


# --------------------------------------------------------------------- #
# Zero-result recovery suggestions (Post-architecture Sprint 1, Bug 5)
# --------------------------------------------------------------------- #

#: Widening ladder for radius searches (km). Fixed, documented rungs — never
#: derived per-query, so suggestions are stable and deterministic.
_RADIUS_LADDER_KM: tuple[float, ...] = (250.0, 500.0, 1000.0)


def zero_radius_suggestions(
    intent: ParsedIntent,
    summary: dict[str, Any],
    region_hint: str | None,
) -> list[str]:
    """Bug 5: deterministic "you could try" alternatives for a zero-hit
    float-discovery search. Every suggestion is a *question/action*, derived
    only from the executed scope (payload radius / coordinates) and the
    ontology's region vocabulary — nothing is computed about the data."""
    out: list[str] = []
    current = summary.get("radius_km") or intent.radius_km
    if current is not None and intent.lat is not None:
        wider = [r for r in _RADIUS_LADDER_KM if r > float(current)]
        for rung in wider[:2]:
            out.append(f"Increase the search radius to {rung:.0f} km.")
    if intent.region:
        # Region-scoped zero: point at the other India-lake region(s).
        for other in sorted(INDIA_QUERY_REGIONS - {intent.region}):
            out.append(f"Search the {region_name(other)} instead.")
        out.append("Try a coastal place name (e.g. 'floats near Goa') or explicit coordinates.")
    elif region_hint:
        out.append(f"Search the {region_name(region_hint)} instead.")
    if not out:
        out.append("Try another coastal place name or explicit coordinates.")
    # De-duplicate, cap at 3 recovery actions.
    seen: set[str] = set()
    unique: list[str] = []
    for item in out:
        if item and item not in seen:
            seen.add(item)
            unique.append(item)
    return unique[:3]
