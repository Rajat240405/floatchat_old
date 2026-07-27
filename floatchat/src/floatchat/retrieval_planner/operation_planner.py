"""Phase 2-5: Operation-based Planner.

Converts a user query + extracted entities into a sequence of Operations.
The planner is a PURE FUNCTION — no side effects, no LLM calls, no I/O.

Phase 5: The planner detects mixed knowledge+data queries and produces
multi-operation plans. Single-intent queries are unchanged.

Operation taxonomy:
  find_floats, filter_region, filter_variable, filter_year, filter_active,
  filter_depth, filter_location, filter_float, sort_latest,
  plot_profile, plot_trajectory, plot_timeseries, plot_hovmoller,
  plot_ts_diagram, plot_comparison, metadata_lookup, count_floats,
  explain_topic, summarize
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from floatchat.models import ParsedIntent

logger = logging.getLogger(__name__)

_TERMINAL_OPS = frozenset({
    "plot_profile", "plot_trajectory", "plot_timeseries",
    "plot_hovmoller", "plot_ts_diagram", "plot_comparison",
    "find_floats", "find_nearest", "metadata_lookup",
    "count_floats", "explain_topic", "summarize",
})

_KNOWLEDGE_CONCEPTS = re.compile(
    r"\b(what\s+is|what\s+are|explain|describe|tell\s+me\s+about|"
    r"how\s+does|how\s+do|why\s+is|definition\s+of)\b",
    re.IGNORECASE,
)

_DATA_REQUEST_VERBS = re.compile(
    r"\b(show|plot|display|graph|visualize|draw|get|fetch|"
    r"find|list|profile|trajectory|compare)\b",
    re.IGNORECASE,
)


def _find_floats_params(intent: ParsedIntent) -> dict[str, Any]:
    """Terminal-op parameters for float discovery (Sprint 5, Bugs 1/3).

    Region search and radius search are distinct concepts:

    * named-region scope ("Arabian Sea") → REGION geometry — no radius is
      invented (execution filters inside the named region directly);
    * point scope (raw coordinates / named place) → POINT geometry + radius
      — the user's explicit radius or the gazetteer's place radius, else
      the established 500 km default for bare coordinates.
    """
    region_scoped = intent.region is not None and intent.lat is None
    return {
        "lat": intent.lat,
        "lon": intent.lon,
        "radius_km": None if region_scoped else (intent.radius_km or 500.0),
    }


@dataclass
class Operation:
    name: str
    params: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        p = ", ".join(f"{k}={v}" for k, v in self.params.items() if v is not None)
        return f"{self.name}({p})" if p else self.name


@dataclass
class Plan:
    operations: list[Operation] = field(default_factory=list)
    legacy_intent: str = "profile_plot"
    is_mixed: bool = False

    def __repr__(self) -> str:
        tag = " [MIXED]" if self.is_mixed else ""
        ops = " → ".join(str(op) for op in self.operations)
        return f"Plan[{self.legacy_intent}]{tag}: {ops}"

    def has(self, name: str) -> bool:
        return any(op.name == name for op in self.operations)

    def get(self, name: str) -> Operation | None:
        for op in self.operations:
            if op.name == name:
                return op
        return None

    @property
    def terminal_operations(self) -> list[Operation]:
        return [op for op in self.operations if op.name in _TERMINAL_OPS]


def _detect_mixed_query(message: str, intent: ParsedIntent) -> str | None:
    """Detect if a query mixes knowledge + data requests."""
    text = message.lower()
    has_concept = bool(_KNOWLEDGE_CONCEPTS.search(text))
    has_data = bool(_DATA_REQUEST_VERBS.search(text)) or bool(intent.variables)
    if not (has_concept and has_data):
        return None
    for pattern in [
        r"(?:what\s+is|what\s+are|explain|describe)\s+(?:a|an|the)?\s*(\w+(?:\s+\w+)?)",
        r"(?:tell\s+me\s+about)\s+(\w+(?:\s+\w+)?)",
        r"(?:how\s+does|how\s+do)\s+(?:a|an)?\s*(\w+(?:\s+\w+)?)",
    ]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return "general"


def plan_from_intent(intent: ParsedIntent, message: str = "") -> Plan:
    """Convert a ParsedIntent into a Plan (sequence of Operations)."""
    ops: list[Operation] = []
    legacy = intent.intent

    # --- Shared filters --- #
    if intent.region:
        ops.append(Operation("filter_region", {"region": intent.region}))
    if intent.lat is not None and intent.lon is not None:
        ops.append(Operation("filter_location", {
            "lat": intent.lat, "lon": intent.lon, "radius_km": intent.radius_km,
        }))
    if intent.variables:
        ops.append(Operation("filter_variable", {"variables": intent.variables}))
    if intent.year is not None:
        params: dict[str, Any] = {"year": intent.year}
        if intent.month_window:
            params["month_window"] = intent.month_window
        elif intent.month:
            params["month"] = intent.month
    else:
        params = {}
    # Sprint 1 (Bug 2): an open-ended temporal window is part of the plan.
    # "after 2023" is not "year = 2023" — surface the resolved ISO bounds so
    # the plan shows filter_year(after=…/before=…) instead of dropping the
    # constraint entirely.
    if intent.temporal_date_start:
        params["after"] = intent.temporal_date_start
    if intent.temporal_date_end:
        params["before"] = intent.temporal_date_end
    if params:
        ops.append(Operation("filter_year", params))
    if intent.depth_min is not None or intent.depth_max is not None:
        ops.append(Operation("filter_depth", {
            "depth_min": intent.depth_min, "depth_max": intent.depth_max,
        }))
    if intent.operational_filter == "alive":
        ops.append(Operation("filter_active", {}))
    if intent.float_id:
        ops.append(Operation("filter_float", {"float_id": intent.float_id}))

    # --- Phase 5: Mixed query detection --- #
    knowledge_topic = _detect_mixed_query(message, intent) if message else None
    if knowledge_topic:
        ops.append(Operation("explain_topic", {"topic": knowledge_topic}))
        if intent.intent in ("profile_plot", "region_search"):
            ops.append(Operation("plot_profile", {}))
        elif intent.intent == "radius_search":
            ops.append(Operation("find_floats", _find_floats_params(intent)))
        if intent.intent in (
            "profile_plot", "region_search", "time_series",
            "hovmoller", "ts_diagram", "comparison_plot",
        ):
            ops.append(Operation("summarize", {}))
        plan = Plan(operations=ops, legacy_intent=legacy, is_mixed=True)
        logger.info("Mixed plan: %s", plan)
        return plan

    # --- Standard single-intent operations --- #
    if intent.intent == "metadata_lookup":
        ops.append(Operation("metadata_lookup", {"float_id": intent.float_id}))
    elif intent.intent == "trajectory":
        ops.append(Operation("plot_trajectory", {"float_id": intent.float_id}))
    elif intent.intent == "nearest_float":
        ops.append(Operation("find_nearest", {
            "lat": intent.lat, "lon": intent.lon, "limit": intent.limit,
        }))
    elif intent.intent == "radius_search":
        # Sprint 5 (Bugs 1/3): named-region scopes plan a radius-free
        # find_floats (region geometry); point scopes keep the explicit or
        # gazetteer radius, else the established 500 km default.
        ops.append(Operation("find_floats", _find_floats_params(intent)))
    elif intent.intent == "count_aggregate":
        ops.append(Operation("count_floats", {"existence_check": intent.existence_check}))
    elif intent.intent == "time_series":
        ops.append(Operation("plot_timeseries", {}))
    elif intent.intent == "hovmoller":
        ops.append(Operation("plot_hovmoller", {}))
    elif intent.intent == "ts_diagram":
        ops.append(Operation("plot_ts_diagram", {}))
    elif intent.intent in ("comparison_plot", "comparison"):
        ops.append(Operation("plot_comparison", {
            "float_ids": intent.comparison_float_ids,
            "regions": intent.comparison_regions,
        }))
    elif intent.intent in ("profile_plot", "region_search"):
        ops.append(Operation("plot_profile", {}))

    if intent.intent in (
        "profile_plot", "region_search", "time_series",
        "hovmoller", "ts_diagram", "comparison_plot",
    ):
        ops.append(Operation("summarize", {}))

    plan = Plan(operations=ops, legacy_intent=legacy)
    logger.info("Planner output: %s", plan)
    return plan
