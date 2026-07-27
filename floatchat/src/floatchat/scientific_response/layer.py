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

The layer never calls an LLM, runs SQL/DuckDB, or alters execution results,
plots, or planner behavior.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable

from floatchat.config import settings
from floatchat.models import ChatResponse, ParsedIntent

from .narration import narrate, region_name, variable_phrase
from .suggestions import suggest
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
    ) -> ChatResponse:
        """Recompose *response*'s presentation. Never alters execution output.

        Returns *response* unchanged when the layer is disabled, the response
        is not a content-bearing data answer, or nothing useful could be said.
        """
        if not getattr(settings, "scientific_response_enabled", True):
            return response
        summary = response.data_summary or {}
        matched = int(summary.get("matched_records") or 0)
        has_content = bool(response.figure) or bool(response.map_data) or matched > 0
        if intent.intent in _NON_DATA_INTENTS or not has_content:
            return response

        context_lines = _context_lines(context_resolutions)
        resolutions = list(reasoning_resolutions)
        assumption_lines = _assumptions(intent, resolutions)
        reasoning_lines = (
            _reasoning_lines(intent, reasoning_rule, resolutions)
            if getattr(settings, "scientific_reasoning_explanation_enabled", False)
            else []
        )
        sections = ComposedSections(
            narration=narrate(intent, summary, matched),
            summary=tuple(summarize(response, intent, response.message)),
            context_used=tuple(context_lines),
            assumptions=tuple(assumption_lines),
            reasoning=tuple(reasoning_lines),
            followups=tuple(suggest(intent, has_context=bool(context_lines))),
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


# --------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------- #
def _render(s: ComposedSections) -> str:
    parts: list[str] = [s.narration]

    def _section(title: str, items: tuple[str, ...]) -> None:
        if items:
            parts.append(f"**{title}**\n" + "\n".join(f"- {i}" for i in items))

    _section("Scientific summary", s.summary)
    _section("Context used", s.context_used)
    _section("Assumptions used", s.assumptions)
    _section("Suggested follow-ups", s.followups)
    _section("Request interpretation", s.reasoning)
    return "\n\n".join(parts)


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
def _assumptions(intent: ParsedIntent, resolutions: list[str]) -> list[str]:
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
    if intent.intent == "radius_search" and intent.radius_km is not None and intent.lat is not None:
        lines.append(f"Search radius: {intent.radius_km:.0f} km.")
    return lines


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
