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

from .metadata_focus import focused_narration, secondary_fact


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


def _measurements_clause(vp: str, noun: str) -> str:
    """'the temperature profile' / 'the requested measurements' — the empty
    variable fallback already carries its own article, so prefixing another
    one would produce "the the requested measurements" (Sprint 4 fix)."""
    if vp.startswith("the "):
        return vp
    return f"the {vp} {noun}"


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


def narrate(
    intent: ParsedIntent,
    summary: dict[str, Any],
    matched: int,
    *,
    radius_defaulted: bool = False,
    count_hint: str | None = None,
    metadata_focus: str | None = None,
) -> str:
    """One natural opening line for a successful data response.

    Post-architecture Sprint 1:

    * ``radius_defaulted`` (Bug 3) — when the Semantic Reasoner applied its
      established default radius (the user never asked for one), the
      narration reflects the user's *conceptual* scope ("in the Arabian
      Sea"), never the internal planner default ("within 500 km").
    * ``count_hint`` (Bugs 1/4) — which entity the scientist asked about
      ("floats"/"profiles"); it only orders the two executor-computed
      counts — both are always rendered from the payload, never invented.

    Sprint 4:

    * ``metadata_focus`` — which single metadata field the question asked
      about (see metadata_focus.py); a focused metadata answer replaces the
      generic card opening, optionally followed by one secondary fact.
    * All presentation is plain text — no ``**bold**`` markers.
    """
    vp = variables_phrase(list(intent.variables))
    clause = _FORM_CLAUSE.get(intent.intent, "")
    tail = f" {clause}" if clause else ""

    if intent.intent in ("profile_plot", "region_search"):
        if intent.float_id:
            return (
                f"Showing {_measurements_clause(vp, 'profile')} for Float {intent.float_id}"
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
                f"Showing {_measurements_clause(vp, 'profiles')} across the {region_name(intent.region)}"
                f"{counts} within the requested scope.{tail}"
            )
        if intent.lat is not None and intent.lon is not None:
            return (
                f"Showing {_measurements_clause(vp, 'profiles')} near "
                f"({intent.lat:.2f}, {intent.lon:.2f}).{tail}"
            )
        return f"Showing {_measurements_clause(vp, 'profiles')} within the requested scope.{tail}"

    if intent.intent in ("comparison_plot", "comparison"):
        pairs = list(intent.comparison_float_ids) or []
        region_pairs = list(intent.comparison_regions) or []
        if len(pairs) >= 2:
            sides = " and ".join(f"Float {p}" for p in pairs[:2])
        elif len(region_pairs) >= 2:
            sides = f"the {region_name(region_pairs[0])} and the {region_name(region_pairs[1])}"
        else:
            sides = "the requested subjects"
        return (
            f"Comparing {vp} between {sides} using all matching observations "
            f"within the requested scope.{tail}"
        )

    if intent.intent == "trajectory":
        points = summary.get("trajectory_points") or matched
        span = _datetime_span(summary)
        return f"Showing the drift trajectory of Float {intent.float_id} — {points} recorded profile locations{span}.{tail}"

    if intent.intent == "nearest_float":
        detail = (
            f" to ({intent.lat:.2f}, {intent.lon:.2f})"
            if intent.lat is not None and intent.lon is not None
            else ""
        )
        return f"Found {matched} float{'s' if matched != 1 else ''} nearest{detail}.{tail}"

    if intent.intent == "radius_search":
        # Bug 3: narrate the user's conceptual scope. A defaulted radius is
        # an internal planner choice — it belongs in "Assumptions", not
        # in the narration; it renders only when the user explicitly gave it.
        # "active" is claimed only when execution actually applied the alive
        # filter (the coordinate branch reports alive_filter=true).
        active = "active " if summary.get("alive_filter") else ""
        noun = f"{active}float{'s' if matched != 1 else ''}"
        explicit_radius = (
            f" within {intent.radius_km:.0f} km"
            if intent.radius_km and not radius_defaulted
            else ""
        )
        if intent.region:
            return f"Found {matched} {noun} in the {region_name(intent.region)}{explicit_radius}.{tail}"
        detail = (
            f"({intent.lat:.2f}, {intent.lon:.2f})"
            if intent.lat is not None and intent.lon is not None
            else ""
        )
        if explicit_radius and detail:
            return f"Found {matched} {noun}{explicit_radius} of {detail}.{tail}"
        if detail:
            return f"Found {matched} {noun} near {detail}.{tail}"
        return f"Found {matched} {noun} matching your request.{tail}"

    if intent.intent == "count_aggregate":
        return _count_narration(intent, summary, matched, count_hint, vp, radius_defaulted)

    if intent.intent == "metadata_lookup":
        if metadata_focus and metadata_focus != "metadata_summary":
            main = focused_narration(intent, summary, metadata_focus)
            extra = secondary_fact(intent, summary, metadata_focus)
            return f"{main} {extra}" if extra else main
        return f"Metadata summary for Float {intent.float_id} from the local Argo metadata index."

    if intent.intent == "time_series":
        scope = f" for Float {intent.float_id}" if intent.float_id else (f" across the {region_name(intent.region)}" if intent.region else "")
        return f"Showing how {vp} evolves over time{scope}.{_datetime_span(summary)}.{tail}"

    if intent.intent == "hovmoller":
        scope = f" for Float {intent.float_id}" if intent.float_id else (f" across the {region_name(intent.region)}" if intent.region else "")
        return f"Showing a time–depth (Hovmöller) view of {vp}{scope}.{tail}"

    if intent.intent == "ts_diagram":
        scope = f" for Float {intent.float_id}" if intent.float_id else (f" across the {region_name(intent.region)}" if intent.region else "")
        return f"Showing the temperature–salinity (T–S) relationship{scope}.{tail}"

    # Unknown/new intent: a sober generic line rather than a system log.
    return f"Results for your request ({matched} matching record{'s' if matched != 1 else ''})."


# --------------------------------------------------------------------- #
# Count narration (Post-architecture Sprint 1, Bugs 1/4)
# --------------------------------------------------------------------- #
def _plural(n: int, singular: str, plural: str | None = None) -> str:
    word = singular if n == 1 else (plural or singular + "s")
    return f"{n:,} {word}"


def _temporal_window_text(intent: ParsedIntent) -> str:
    """Human clause for the temporal constraint execution actually received."""
    start, end = intent.temporal_date_start, intent.temporal_date_end
    if start and end:
        return f" between {start} and {end}"
    if start:
        return f" from {start} onward"
    if end:
        return f" until {end}"
    if intent.year is not None:
        return f" in {intent.year}"
    return ""


def _count_scope_text(intent: ParsedIntent, radius_defaulted: bool) -> str:
    """The scientist's conceptual scope for a count (never internal defaults)."""
    if intent.region:
        return f" in the {region_name(intent.region)}"
    if intent.float_id:
        return f" for Float {intent.float_id}"
    if intent.lat is not None and intent.lon is not None:
        coords = f"({intent.lat:.2f}, {intent.lon:.2f})"
        if intent.radius_km and not radius_defaulted:
            return f" within {intent.radius_km:.0f} km of {coords}"
        return f" near {coords}"
    # No scope fields: the count executor covers the whole local lake, which
    # is the India deployment region (its own message says "India Region").
    return " across the local India-region data lake"


def _count_narration(
    intent: ParsedIntent,
    summary: dict[str, Any],
    matched: int,
    count_hint: str | None,
    vp: str,
    radius_defaulted: bool = False,
) -> str:
    """Bugs 1/4: the computed counts ARE the answer — always rendered, with
    wording that names the entity actually counted (executor payloads carry
    both ``unique_floats`` and the profile count under ``matched_records``;
    each reported value sits next to its true unit, never a generic label).
    ``count_hint`` only chooses which fact leads the sentence."""
    floats = summary.get("unique_floats")
    profiles = matched if matched else summary.get("matched_records")
    scope = _count_scope_text(intent, radius_defaulted)
    window = _temporal_window_text(intent)
    variables = f" for {vp}" if intent.variables else ""

    if intent.existence_check:
        facts = []
        if profiles:
            facts.append(_plural(int(profiles), "profile"))
        if floats:
            facts.append("from " + _plural(int(floats), "float"))
        detail = " ".join(facts) if facts else "matching data"
        return f"Yes — Argo data exists{scope}{variables}{window}: {detail}."

    # Sprint 4: a float-scoped count counts profiles of that one float —
    # answer exactly that ("Float 5906969 has 142 profiles.") instead of
    # the generic "1 float with N matching profiles" pair.
    if intent.float_id:
        return (
            f"Float {intent.float_id} has "
            f"{_plural(int(profiles or 0), 'profile')}{variables}{window}."
        )

    if floats and profiles:
        pair = (
            f"{_plural(int(floats), 'float')} "
            f"with {_plural(int(profiles), 'matching profile')}"
            if count_hint != "profiles"
            else f"{_plural(int(profiles), 'profile')} "
            f"collected by {_plural(int(floats), 'float')}"
        )
    elif floats:
        pair = f"{_plural(int(floats), 'float')}"
    else:
        pair = f"{_plural(int(profiles or 0), 'profile')}"
    return f"There are {pair}{scope}{variables}{window}."


# --------------------------------------------------------------------- #
# Zero-result narration (Post-architecture Sprint 1, Bug 5)
# --------------------------------------------------------------------- #
def zero_radius_narration(
    intent: ParsedIntent, summary: dict[str, Any], place_label: str | None
) -> str:
    """Bug 5: gentle zero-result line for float-discovery searches.

    The effective radius is stated from the *execution* payload
    (``summary["radius_km"]`` — what the engine actually searched), and the
    place is named only when the coordinates provably came from the
    gazetteer; coordinates otherwise. Unlike success narration, the radius
    is always shown here: it is the factual scope that produced zero hits.
    """
    active = "currently active " if summary.get("alive_filter") else ""
    if intent.region and intent.lat is None:
        return f"No {active}floats were found in the {region_name(intent.region)}."
    target = place_label or (
        f"({intent.lat:.2f}, {intent.lon:.2f})"
        if intent.lat is not None and intent.lon is not None
        else None
    )
    radius = summary.get("radius_km") or intent.radius_km
    if radius and target:
        return f"No {active}floats were found within {float(radius):.0f} km of {target}."
    if target:
        return f"No {active}floats were found near {target}."
    return f"No {active}floats matched your search."
