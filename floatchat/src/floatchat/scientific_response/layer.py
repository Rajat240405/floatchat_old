"""Scientific Response Layer — deterministic post-execution composition (Phase 5).

Consumes the Execution Engine's `ChatResponse` (frozen output) plus upstream
reasoning/context traces and recomposes the **presentation** only:

    Scientific Narration        — natural scientific opening (narration.py)
    Scientific Summary          — facts: engine interpretation + computed stats (summary.py)
    Context Used                — only when Conversation Intelligence inherited facts
    Assumptions                 — only defaults actually applied (from intent + traces)
    Request interpretation      — optional/configurable Phase-3 reasoning view
    Suggested follow-ups        — deterministic next questions (suggestions.py)

Figure, map data, and every original ``data_summary`` key pass through
byte-identical; the original engine message is preserved under
``data_summary["engine_message"]``.

Sprint 4 (response quality): metadata answers are *field-aware* — the layer
detects which single metadata field the scientist asked about and composes
exactly that answer (see metadata_focus.py). All presentation is plain
text: no ``**bold**`` markers, ``•`` bullets, and every fact appears once
(repeated facts are dropped from the summary sections).

The layer never calls an LLM, runs SQL/DuckDB, or alters execution results,
plots, or planner behavior.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from floatchat.config import settings
from floatchat.intent_parser.gazetteer import reverse_place_name
from floatchat.models import ChatResponse, ParsedIntent
from floatchat.ontology.regions import tag_india_region

from .metadata_focus import metadata_focus
from .narration import narrate, region_name, variable_phrase, zero_radius_narration
from .suggestions import suggest, zero_radius_suggestions
from .summary import summarize

logger = logging.getLogger(__name__)

#: Intents for which a composed scientific response makes sense. Everything
#: else (clarifications, control acks, errors, unsupported scopes, zero-result
#: explanations) passes through untouched.
_NON_DATA_INTENTS = {
    "unknown", "clarification", "error", "small_talk", "out_of_domain",
    "general_chat", "knowledge_base", "available_plots",
}

#: Profile-shaped forms to which profile-related assumptions apply.
_PROFILE_FORMS = {"profile_plot", "region_search", "ts_diagram", "hovmoller"}
_DATA_FORMS = _PROFILE_FORMS | {
    "comparison_plot", "comparison", "trajectory", "time_series",
    "nearest_float", "radius_search", "count_aggregate", "metadata_lookup",
}

#: Objective labels for the optional reasoning view (from the final intent —
#: a fact about what was executed, not a claim).
_OBJECTIVE_LABEL = {
    "profile_plot": "Measurement (depth profile)",
    "region_search": "Measurement (regional)",
    "ts_diagram": "Measurement (T–S form)",
    "hovmoller": "Measurement (time–depth form)",
    "time_series": "Measurement (temporal)",
    "comparison_plot": "Comparative analysis",
    "comparison": "Comparative analysis",
    "trajectory": "Drift trajectory",
    "nearest_float": "Float discovery (nearest)",
    "radius_search": "Float discovery (area)",
    "count_aggregate": "Coverage counting",
    "metadata_lookup": "Metadata",
}


@dataclass(frozen=True)
class ComposedSections:
    """Structured form of a composed response (mirrors the message sections)."""

    narration: str
    summary: tuple[str, ...] = ()
    context_used: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    reasoning: tuple[str, ...] = ()
    followups: tuple[str, ...] = ()


class ScientificResponseLayer:
    """Deterministic presentation layer for successful data responses."""

    # ------------------------------------------------------------------ #

    def compose(
        self,
        response: ChatResponse,
        *,
        intent: ParsedIntent,
        context_resolutions: Iterable[str] = (),
        reasoning_rule: str | None = None,
        reasoning_resolutions: Iterable[str] = (),
        user_message: str | None = None,
    ) -> ChatResponse:
        """Recompose *response*'s presentation. Never alters execution output.

        Returns *response* unchanged when the layer is disabled, the response
        is not a content-bearing data answer, or nothing useful could be said.

        ``user_message`` (Post-architecture Sprint 1) is used only to select
        wording that matches the scientist's question (e.g. which counted
        entity leads a count narration) — never to compute anything.
        """
        if not getattr(settings, "scientific_response_enabled", True):
            return response
        summary = response.data_summary or {}
        matched = int(summary.get("matched_records") or 0)
        has_content = bool(response.figure) or bool(response.map_data) or matched > 0
        resolutions = list(reasoning_resolutions)
        # Bug 3: the Semantic Reasoner records when it applied its
        # established default radius — narration must not present that
        # internal default as the user's requested scope.
        radius_defaulted = any(
            str(r).startswith("radius_search without an explicit radius")
            for r in resolutions
        )
        if intent.intent in _NON_DATA_INTENTS:
            return response
        if not has_content:
            # Bug 5: zero-hit float-discovery searches get a gentle,
            # deterministic recovery response instead of the raw engine line.
            # Gate on summary["radius_km"]: only the executor's coordinate
            # branch reports it, so a genuine zero-hit search is composed —
            # while degraded fallbacks ("lake may not have coordinates",
            # lake-unavailable) keep their honest engine messages untouched.
            if (
                intent.intent == "radius_search"
                and not response.figure
                and not response.map_data
                and summary.get("radius_km") is not None
            ):
                return self._compose_zero_radius(
                    response, intent=intent, summary=summary,
                )
            return response

        # Sprint 4: which metadata field did the scientist ask about? A
        # focused metadata question replaces the generic card with exactly
        # the requested fact; broad requests keep the full card.
        focus: str | None = None
        if intent.intent == "metadata_lookup":
            focus = metadata_focus(user_message)
        focused_metadata = bool(focus and focus != "metadata_summary")

        context_lines = _context_lines(context_resolutions)
        assumption_lines = _assumptions(intent, resolutions, radius_defaulted)
        if focused_metadata:
            # A focused registry fact has no execution defaults to disclose —
            # the "all dates included" line is noise next to one fact.
            assumption_lines = []
        reasoning_lines = (
            _reasoning_lines(intent, reasoning_rule, resolutions)
            if getattr(settings, "scientific_reasoning_explanation_enabled", False)
            else []
        )
        narration = narrate(
            intent, summary, matched,
            radius_defaulted=radius_defaulted,
            count_hint=_count_entity_hint(user_message),
            metadata_focus=focus,
        )
        summary_lines = _drop_repeated_facts(
            narration,
            summarize(response, intent, response.message, metadata_focus=focus),
        )
        sections = ComposedSections(
            narration=narration,
            summary=tuple(summary_lines),
            context_used=tuple(context_lines),
            assumptions=tuple(assumption_lines),
            reasoning=tuple(reasoning_lines),
            followups=tuple(
                suggest(
                    intent,
                    has_context=bool(context_lines),
                    metadata_focus=focus,
                    float_info=(
                        summary.get("float_info")
                        if intent.intent == "metadata_lookup"
                        else None
                    ),
                )
            ),
        )
        message = _render(sections)
        if message.strip() == response.message.strip():
            return response

        enriched_summary = {
            **summary,
            "engine_message": response.message,
            "scientific_response": {
                "narration": sections.narration,
                "summary": list(sections.summary),
                "context_used": list(sections.context_used),
                "assumptions": list(sections.assumptions),
                "reasoning": list(sections.reasoning),
                "suggested_followups": list(sections.followups),
            },
        }
        logger.debug(
            "SCIENTIFIC_RESPONSE intent=%s sections=[narration,%ds,%dc,%da,%dr,%df]",
            intent.intent,
            len(sections.summary),
            len(sections.context_used),
            len(sections.assumptions),
            len(sections.reasoning),
            len(sections.followups),
        )
        return response.model_copy(
            update={"message": message, "data_summary": enriched_summary}
        )

    # ------------------------------------------------------------------ #

    def _compose_zero_radius(
        self,
        response: ChatResponse,
        *,
        intent: ParsedIntent,
        summary: dict[str, Any],
    ) -> ChatResponse:
        """Bug 5: gentle, deterministic zero-hit response for radius searches.

        Composition only — execution output is untouched (the engine's exact
        message is preserved under ``data_summary["engine_message"]``). The
        recovery suggestions come from the executed scope (radius, point,
        ontology region containing the point), never from an LLM.
        """
        coords = (
            intent.lat is not None and intent.lon is not None
        )
        place_label = (
            reverse_place_name(intent.lat, intent.lon) if coords else None
        )
        region_hint = (
            tag_india_region(intent.lat, intent.lon) if coords else None
        )
        narration = zero_radius_narration(intent, summary, place_label)
        recovery = zero_radius_suggestions(intent, summary, region_hint)
        lines = [narration]
        if recovery:
            lines.append("You could try:\n" + "\n".join(f"• {r}" for r in recovery))
        message = "\n\n".join(lines)
        if message.strip() == response.message.strip():
            return response
        enriched_summary = {
            **summary,
            "engine_message": response.message,
            "scientific_response": {
                "narration": narration,
                "summary": [],
                "context_used": [],
                "assumptions": [],
                "reasoning": [],
                "suggested_followups": list(recovery),
            },
        }
        logger.debug(
            "SCIENTIFIC_RESPONSE intent=radius_search zero-result recovery (%d suggestions)",
            len(recovery),
        )
        return response.model_copy(
            update={"message": message, "data_summary": enriched_summary}
        )


# --------------------------------------------------------------------- #
# Count entity hint (Post-architecture Sprint 1, Bug 4)
# --------------------------------------------------------------------- #
def _count_entity_hint(user_message: str | None) -> str | None:
    """Which counted entity should lead a count narration.

    Deterministic wording-only signal read from the scientist's sentence;
    the VALUES always come from the execution payload. ``None`` → the
    default float-led ordering (the planner's terminal op is count_floats).
    """
    if not user_message:
        return None
    text = user_message.lower()
    if "float" in text:
        return "floats"
    if "profile" in text or "cycle" in text:
        return "profiles"
    if any(w in text for w in ("observation", "measurement", "data", "reading")):
        return "profiles"  # the executor's data-unit count is profiles
    return None


# --------------------------------------------------------------------- #
# Rendering — plain text (Sprint 4: no **bold**, • bullets)
# --------------------------------------------------------------------- #
def _render(s: ComposedSections) -> str:
    parts: list[str] = [s.narration]

    def _section(title: str, items: tuple[str, ...]) -> None:
        if items:
            parts.append(f"{title}\n" + "\n".join(f"• {i}" for i in items))

    _section("Summary", s.summary)
    _section("Context used", s.context_used)
    _section("Assumptions", s.assumptions)
    _section("Next you could:", s.followups)
    _section("Request interpretation", s.reasoning)
    return "\n\n".join(parts)


# --------------------------------------------------------------------- #
# Fact de-duplication (Sprint 4, Bug 4): every fact appears once
# --------------------------------------------------------------------- #
#: Unit words whose accompanying numbers count as "facts". Normalized to a
#: canonical singular — the executor's payloads count profiles as "records",
#: so "Profiles on record: 142." and "… has 142 profiles." are the same fact.
_FACT_UNITS = {
    "profile": "profile",
    "profiles": "profile",
    "float": "float",
    "floats": "float",
    "cycle": "cycle",
    "cycles": "cycle",
    "measurement": "measurement",
    "measurements": "measurement",
    "record": "profile",
    "records": "profile",
    "location": "location",
    "locations": "location",
}
_FACT_NUMBER_RE = re.compile(r"^\d[\d,]*(?:\.\d+)?$")


def _fact_pairs(text: str) -> set[tuple[str, str]]:
    """(unit, number) facts stated in a text: each unit word paired with any
    number token inside a ±3-token window. Dates and ranges are not number
    tokens ("2024-01-01", "4.0–28.0" do not match)."""
    tokens = [tok.strip("()[]{};:,.") for tok in str(text).split()]
    pairs: set[tuple[str, str]] = set()
    for i, tok in enumerate(tokens):
        unit = _FACT_UNITS.get(tok.lower())
        if unit is None:
            continue
        for j in range(max(0, i - 3), min(len(tokens), i + 3)):
            if j == i:
                continue
            candidate = tokens[j]
            if _FACT_NUMBER_RE.match(candidate):
                pairs.add((unit, candidate.replace(",", "")))
    return pairs


_COVERAGE_SPAN_RE = re.compile(
    r"^(Coverage: .+?) \((\d{4}-\d{2}-\d{2}) → (\d{4}-\d{2}-\d{2})\)\.$"
)


def _drop_repeated_facts(narration: str, bullets: Iterable[str]) -> list[str]:
    """Sprint 4 (Bug 4): every fact appears once.

    A summary bullet is dropped only when ALL its extractable (unit, number)
    facts already appear in the narration (subset-only semantics) — a bullet
    carrying any new fact, or no extractable facts, is kept whole. As a
    finer-grained case, the trailing "(min → max)" span of a "Coverage:"
    bullet is stripped when both dates already appear in the narration.
    """
    narr_facts = _fact_pairs(narration)
    kept: list[str] = []
    for bullet in bullets:
        facts = _fact_pairs(bullet)
        if facts and narr_facts and facts <= narr_facts:
            continue  # the narration already stated every fact in this bullet
        match = _COVERAGE_SPAN_RE.match(bullet)
        if match:
            body, dmin, dmax = match.groups()
            if dmin in narration and dmax in narration:
                bullet = body + "."
        kept.append(bullet)
    return kept


# --------------------------------------------------------------------- #
# Context Used — phrases built ONLY from Conversation Intelligence trace
# --------------------------------------------------------------------- #
def _context_lines(trace: Iterable[str]) -> list[str]:
    lines: list[str] = []
    for entry in trace:
        text = str(entry)
        if text.startswith("inherited float_id="):
            fid = text.split("=", 1)[1].split(" ", 1)[0]
            lines.append(f"Continuing with the previously selected float ({fid}).")
        elif text.startswith("inherited profile="):
            num = text.split("=", 1)[1].split(" ", 1)[0]
            lines.append(f"Using the previously selected profile ({num}).")
        elif text.startswith("inherited variable="):
            codes = text.split("=", 1)[1].split(" ", 1)[0].split(",")
            lines.append(
                "Continuing with " + variable_phrase(codes[0]) + " from the previous step."
            )
        elif text.startswith("inherited comparison partner float="):
            fid = text.split("=", 1)[1].split(" ", 1)[0]
            lines.append(f"Comparing against the previously selected float ({fid}).")
        elif text.startswith("inherited ongoing comparison (floats "):
            members = text.split("(", 1)[1].rstrip(")").split(" ", 1)[1]
            ids = members.rstrip(")").split(",")
            if len(ids) >= 2:
                lines.append(
                    f"Continuing the existing comparison between Float {ids[0]} and Float {ids[1]}."
                )
        elif text.startswith("inherited ongoing comparison (regions "):
            members = text.split("(", 1)[1].rstrip(")").split(" ", 1)[1]
            ids = members.rstrip(")").split(",")
            if len(ids) >= 2:
                lines.append(
                    f"Continuing the existing comparison between the "
                    f"{region_name(ids[0])} and the {region_name(ids[1])}."
                )
        elif text.startswith("inherited region="):
            code = text.split("=", 1)[1].split(" ", 1)[0]
            lines.append(f"Continuing within the {region_name(code)}.")
        # Anything not explicitly mapped is skipped — context explanations
        # are shown only when they can be phrased faithfully.
    return lines


# --------------------------------------------------------------------- #
# Assumptions — only defaults actually applied, from intent + traces
# --------------------------------------------------------------------- #
def _assumptions(
    intent: ParsedIntent, resolutions: list[str], radius_defaulted: bool = False
) -> list[str]:
    lines: list[str] = []
    for resolution in resolutions:
        # Facts the Semantic Reasoner already records ("… defaulting to …").
        if "default" in resolution.lower():
            text = resolution[0].upper() + resolution[1:]
            lines.append(text if text.endswith(".") else text + ".")
    if intent.intent in _PROFILE_FORMS:
        if intent.profile_number is None:
            lines.append("Latest available profile selected (no cycle specified).")
        if intent.depth_min is None and intent.depth_max is None:
            lines.append("No depth range specified — the full water column is shown.")
    if intent.intent in _DATA_FORMS and _temporal_unrestricted(intent):
        lines.append("No time range specified — all available dates are included.")
    elif _range_not_applied(intent):
        # Post-architecture Sprint 1 (Bug 2): open-ended date bounds are
        # honoured by the count path (and by alive-filtered radius searches);
        # every other data form still executes unfiltered in time. Say so —
        # the old "no time range" line is correctly suppressed, but silence
        # would overstate what execution did.
        lines.append(
            "Open-ended date bounds (after/before) are currently applied to "
            "count queries only — this result includes all available dates."
        )
    if (
        intent.intent == "radius_search"
        and intent.radius_km is not None
        and intent.lat is not None
        and not radius_defaulted
    ):
        # Bug 3: a defaulted radius is disclosed by the reasoner's own
        # "… defaulting to …" line above; don't restate it as a bare fact.
        lines.append(f"Search radius: {intent.radius_km:.0f} km.")
    return lines


#: Data forms that currently honour open-ended date bounds at execution time.
_RANGE_AWARE_INTENTS = {"count_aggregate"}


def _range_not_applied(intent: ParsedIntent) -> bool:
    if not (intent.temporal_date_start or intent.temporal_date_end):
        return False
    if intent.intent in _RANGE_AWARE_INTENTS:
        return False
    if intent.intent not in _DATA_FORMS:
        return False
    # Alive-filtered radius searches consume the window via _build_alive_window.
    if intent.intent == "radius_search" and intent.operational_filter == "alive":
        return False
    return True


def _temporal_unrestricted(intent: ParsedIntent) -> bool:
    return (
        intent.year is None
        and intent.month is None
        and not intent.month_window
        and not intent.temporal_date_start
        and not intent.temporal_date_end
    )


# --------------------------------------------------------------------- #
# Optional reasoning explanation (debug/demo/transparency; default off)
# --------------------------------------------------------------------- #
def _reasoning_lines(
    intent: ParsedIntent, rule: str | None, resolutions: list[str]
) -> list[str]:
    lines = [f"Scientific objective: {_OBJECTIVE_LABEL.get(intent.intent, intent.intent)}."]
    if rule:
        pretty = rule.replace("_", " ")
        lines.append(f"Reasoning rule: {pretty}.")
    if intent.variables:
        lines.append("Variables present: " + ", ".join(intent.variables) + ".")
    scope = (
        region_name(intent.region)
        if intent.region
        else (
            f"({intent.lat:.2f}, {intent.lon:.2f})"
            if intent.lat is not None and intent.lon is not None
            else (f"Float {intent.float_id}" if intent.float_id else None)
        )
    )
    if scope:
        lines.append(f"Scope: {scope}.")
    for resolution in resolutions[:2]:
        text = resolution[0].upper() + resolution[1:]
        lines.append("Resolution: " + (text if text.endswith(".") else text + "."))
    return lines
