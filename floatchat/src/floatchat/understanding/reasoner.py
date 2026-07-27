"""Semantic Reasoner — deterministic scientific-objective reasoning (Phase 3).

Pipeline position (FloatChat 2.0 — Phase 3):

    SemanticUnderstanding → Grounding (vocabulary, ontology) →
    **Semantic Reasoner (objective interpretation)** → assembly → ParsedIntent
    → existing Planner → Execution Engine (unchanged)

The reasoner is the **single authority for execution-intent selection** in the
semantic pipeline. It does not look at the scientist's words and it does not
match keywords: it receives the *grounded facts* of a request (canonical
variables, regions, float ids, coordinates, comparison structure, the
understanding's intent hint and semantic signals) and answers one question —
**what is the scientist actually trying to do?**

Determinism contract (identical to every other post-understanding stage):
  * no LLM, no SQL, no DuckDB, no planners, no computed data;
  * every emitted value comes from the grounded facts or from a rule that
    mirrors an established, documented engine-compatible default — nothing
    is invented;
  * ambiguity is ranked deterministically; clarification is requested only
    when the ranking cannot separate competing objectives.

Every decision carries ``rule`` (the rule that produced it) and
``resolutions`` (a human-readable trace of conflicts it resolved), which the
instrumentation layer logs — reasoning is always explainable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Tuple

from floatchat.ontology.variables import LEVELS_VARIABLE_ORDER

logger = logging.getLogger(__name__)

#: Intents the reasoner may select (data intents only — non-data buckets are
#: Traffic-Cop territory upstream of understanding).
_DISCOVERY_INTENTS = ("nearest_float", "radius_search")
_STRUCTURAL_HINTS = ("hovmoller", "ts_diagram", "time_series")
_COMPARISON_HINTS = ("comparison_plot", "comparison")

#: Variable defaults for user-named scientific forms, mirroring the
#: established engine-compatible defaults (verbatim legacy parser rules):
_TS_DIAGRAM_DEFAULT = ("TEMP", "PSAL")
_TIME_FORM_DEFAULT = ("TEMP",)

#: Default radius for radius_search without an explicit radius (verbatim
#: legacy parser default).
_RADIUS_SEARCH_DEFAULT_KM = 500.0


@dataclass(frozen=True)
class GroundedUtterance:
    """The grounded facts of one request (output of the grounding stage).

    All entities are canonical ontology identifiers; mentions that could not
    be grounded were dropped upstream (recorded as ambiguities).
    """

    #: grounded intent hint from the understanding (may be None / "unknown").
    intent_hint: str | None
    variables: Tuple[str, ...]
    #: ALL grounded ocean regions in mention order.
    regions: Tuple[str, ...]
    #: regions grounded from the comparison axis.
    comparison_regions: Tuple[str, ...]
    #: validated float ids (deduped, mention order).
    float_ids: Tuple[str, ...]
    lat: float | None
    lon: float | None
    radius_km: float | None
    #: place mentions existed (gazetteer-resolution already attempted).
    place_mentioned: bool
    profile_number: int | None
    existence_check: bool
    operational_filter: str | None
    temporal_fields: dict[str, Any] = field(default_factory=dict)
    depth_min: float | None = None
    depth_max: float | None = None
    existence_comparison_hint: bool = False  # understanding.comparison.is_comparison
    follow_up_reference: bool = False


@dataclass(frozen=True)
class ReasonedClarification:
    """The reasoner could not separate competing objectives deterministically."""

    question: str
    field: str | None = None
    candidates: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ReasoningDecision:
    """The interpreted scientific objective + organized execution fields."""

    intent: str
    variables: Tuple[str, ...]
    region: str | None
    float_id: str | None
    comparison_float_ids: Tuple[str, ...]
    comparison_regions: Tuple[str, ...]
    lat: float | None
    lon: float | None
    radius_km: float | None
    rule: str
    resolutions: Tuple[str, ...] = ()
    clarification: ReasonedClarification | None = None


class SemanticReasoner:
    """Deterministic interpreter of grounded requests into execution intents."""

    def reason(self, g: GroundedUtterance) -> ReasoningDecision:
        if not isinstance(g, GroundedUtterance):
            raise TypeError(
                "SemanticReasoner operates on grounded facts "
                f"(GroundedUtterance), not {type(g).__name__}; the converter "
                "must ground the SemanticUnderstanding before reasoning."
            )
        hints = g.intent_hint if g.intent_hint != "unknown" else None
        resolutions: list[str] = []

        builder = _DecisionBuilder(g, resolutions)

        # --------------------------------------------------------------- #
        # R0 — Comparison organization (multi-concept objective)
        # --------------------------------------------------------------- #
        comparison_signal = (
            g.existence_comparison_hint
            or hints in _COMPARISON_HINTS
            or len(g.float_ids) >= 2
            or len(g.comparison_regions) >= 2
            or len(g.regions) >= 2 and hints in _COMPARISON_HINTS
        )
        float_axis = len(g.float_ids) >= 2
        region_axis_grounded = (
            g.comparison_regions or (g.regions if hints in _COMPARISON_HINTS or g.existence_comparison_hint else ())
        )
        region_axis = len(region_axis_grounded) >= 2
        if comparison_signal and (float_axis or region_axis):
            return self._comparison(g, builder, bool(hints and hints.startswith("comparison")))
        if comparison_signal and not float_axis and not region_axis:
            # "compare" with no second side grounded — cannot rank which
            # objective the scientist meant. Ask, never guess.
            return builder.clarify(
                rule="comparison_incomplete",
                clarification=ReasonedClarification(
                    question=(
                        "You asked to compare, but I can only ground one side. "
                        "What should I compare — two floats (e.g. 'compare float "
                        "2902403 with float 1902190') or two regions (e.g. "
                        "'compare Arabian Sea with Bay of Bengal')?"
                    ),
                    field="comparison",
                    candidates=("two floats", "two regions"),
                ),
            )

        # --------------------------------------------------------------- #
        # R1 — Metadata objective ("tell me about float X")
        # --------------------------------------------------------------- #
        if hints == "metadata_lookup":
            return builder.decide(
                rule="metadata_objective",
                intent="metadata_lookup",
                variables=g.variables,
                region=builder.primary_region(),
                float_id=g.float_ids[0] if g.float_ids else None,
                keep_coords=False,
            )

        # --------------------------------------------------------------- #
        # R2 — User-named scientific forms (hovmoller / ts_diagram / series)
        # --------------------------------------------------------------- #
        if hints in _STRUCTURAL_HINTS:
            variables: Tuple[str, ...] = g.variables
            if not variables:
                if hints == "ts_diagram":
                    variables = _TS_DIAGRAM_DEFAULT
                    resolutions.append(
                        "ts_diagram named with no variables: defaulting to TEMP+PSAL (established form default)"
                    )
                else:
                    variables = _TIME_FORM_DEFAULT
                    resolutions.append(
                        f"{hints} named with no variables: defaulting to TEMP (established form default)"
                    )
            return builder.decide(
                rule="named_scientific_form",
                intent=hints,
                variables=variables,
                region=builder.primary_region(),
                float_id=g.float_ids[0] if g.float_ids else None,
                keep_coords=False,
            )

        # --------------------------------------------------------------- #
        # R3 — Trajectory (single-float drift objective)
        # --------------------------------------------------------------- #
        if hints == "trajectory":
            return builder.decide(
                rule="trajectory_objective",
                intent="trajectory",
                variables=g.variables,
                region=builder.primary_region(),
                float_id=g.float_ids[0] if g.float_ids else None,
                keep_coords=False,
            )

        # --------------------------------------------------------------- #
        # R4 — Count / existence objective
        # --------------------------------------------------------------- #
        if hints == "count_aggregate":
            return builder.decide(
                rule="count_objective",
                intent="count_aggregate",
                variables=g.variables,
                region=builder.primary_region(),
                float_id=g.float_ids[0] if g.float_ids else None,
                keep_coords=True,
            )

        # --------------------------------------------------------------- #
        # R5 — Discovery vs Measurement
        # --------------------------------------------------------------- #
        discovery_signal = hints in _DISCOVERY_INTENTS
        if discovery_signal and g.variables:
            # Variables make the objective a MEASUREMENT at a location, not
            # float discovery (mirrors the engine-compatible legacy routing
            # override, but decided from grounded concepts, not keywords).
            resolutions.append(
                f"variables {list(g.variables)} present: reinterpreting '{hints}' as a measurement objective (profile_plot)"
            )
            return builder.decide(
                rule="discovery_vs_measurement",
                intent="profile_plot",
                variables=g.variables,
                region=builder.primary_region(),
                float_id=g.float_ids[0] if g.float_ids else None,
                keep_coords=True,
            )
        if discovery_signal:
            return builder.decide(
                rule="discovery_objective",
                intent=hints,
                variables=g.variables,
                region=builder.primary_region(),
                float_id=g.float_ids[0] if g.float_ids else None,
                keep_coords=True,
                default_radius=True if hints == "radius_search" else False,
            )

        # --------------------------------------------------------------- #
        # R6 — Metadata vs Data (float + info-need, entity-driven)
        # --------------------------------------------------------------- #
        if (
            hints is None
            and g.float_ids
            and not g.variables
            and g.profile_number is None
        ):
            resolutions.append(
                f"float {g.float_ids[0]} mentioned with no variables and no profile: "
                "interpreting as a metadata objective"
            )
            return builder.decide(
                rule="metadata_vs_data",
                intent="metadata_lookup",
                variables=(),
                region=builder.primary_region(),
                float_id=g.float_ids[0],
                keep_coords=False,
            )

        # --------------------------------------------------------------- #
        # R7 — Entity-driven inference when the hint is unusable
        # --------------------------------------------------------------- #
        if hints is None:
            if g.float_ids and g.variables:
                resolutions.append("no intent hint: float + variables → profile measurement")
                return builder.decide(
                    rule="entity_inference",
                    intent="profile_plot",
                    variables=g.variables,
                    region=builder.primary_region(),
                    float_id=g.float_ids[0],
                    keep_coords=False,
                )
            if g.variables and (g.regions or (g.lat is not None)):
                resolutions.append("no intent hint: variables + scope → regional measurement")
                return builder.decide(
                    rule="entity_inference",
                    intent="region_search",
                    variables=g.variables,
                    region=builder.primary_region(),
                    float_id=None,
                    keep_coords=True,
                )
            if g.variables:
                resolutions.append("no intent hint: variables only → profile measurement (scope to follow)")
                return builder.decide(
                    rule="entity_inference",
                    intent="profile_plot",
                    variables=g.variables,
                    region=None,
                    float_id=None,
                    keep_coords=False,
                )
            return builder.decide(
                rule="unresolved_hint",
                intent="unknown",
                variables=g.variables,
                region=builder.primary_region(),
                float_id=g.float_ids[0] if g.float_ids else None,
                keep_coords=True,
            )

        # --------------------------------------------------------------- #
        # R9 — Hint passthrough (profile_plot / region_search and friends)
        # --------------------------------------------------------------- #
        intent = hints
        if intent not in ("profile_plot", "region_search", *_STRUCTURAL_HINTS, *_DISCOVERY_INTENTS):
            intent = "profile_plot" if g.variables else hints
        return builder.decide(
            rule="hint_passthrough",
            intent=intent,
            variables=g.variables,
            region=builder.primary_region(),
            float_id=g.float_ids[0] if g.float_ids else None,
            keep_coords=True,
        )

    # ------------------------------------------------------------------ #
    # R0 implementation — comparison organization
    # ------------------------------------------------------------------ #

    def _comparison(self, g: GroundedUtterance, builder: "_DecisionBuilder", explicit: bool) -> ReasoningDecision:
        floats = tuple(sorted(g.float_ids))
        regions = tuple(g.comparison_regions) if g.comparison_regions else tuple(g.regions)

        variables: Tuple[str, ...] = g.variables
        resolutions = builder.resolutions
        if not variables:
            if g.follow_up_reference:
                # Mirror the legacy conversational rule: a follow-up comparison
                # inherits variables from context — do not default-fill.
                resolutions.append(
                    "comparison follow-up: variables left empty for context inheritance (legacy conversational rule)"
                )
            else:
                variables = tuple(LEVELS_VARIABLE_ORDER)
                resolutions.append(
                    f"standalone comparison with no variables: defaulting to the full core+BGC set {list(LEVELS_VARIABLE_ORDER)}"
                )
        parts = []
        if len(floats) >= 2:
            parts.append(f"floats {list(floats)}")
        if len(regions) >= 2:
            parts.append(f"regions {list(regions)}")
        resolutions.append("comparison organized across " + " and ".join(parts))
        return builder.decide(
            rule="comparison_organization",
            intent="comparison_plot",
            variables=variables,
            float_id=floats[0] if len(floats) >= 2 else None,
            comparison_float_ids=floats if len(floats) >= 2 else (),
            comparison_regions=regions if len(regions) >= 2 else (),
            region=regions[0] if len(regions) >= 2 else None,
            keep_coords=False,
        )

class _DecisionBuilder:
    """Assembles ReasoningDecisions with the shared organizational rules."""

    def __init__(self, g: GroundedUtterance, resolutions: list[str]) -> None:
        self.g = g
        self.resolutions = resolutions

    def primary_region(self) -> str | None:
        return self.g.regions[0] if self.g.regions else None

    def decide(
        self,
        *,
        rule: str,
        intent: str,
        variables: Tuple[str, ...],
        region: str | None,
        float_id: str | None,
        comparison_float_ids: Tuple[str, ...] = (),
        comparison_regions: Tuple[str, ...] = (),
        keep_coords: bool,
        default_radius: bool = False,
    ) -> ReasoningDecision:
        g = self.g
        lat, lon, radius = g.lat, g.lon, g.radius_km

        # --- Specificity precedence ------------------------------------- #
        # A concrete float (even more a concrete float+profile) is the most
        # specific scientific objective. Place-derived coordinates lose:
        # "Show salinity near Goa for float 1902190 profile 284" is a
        # float-284-profile measurement, not a Goa-area search.
        if float_id and keep_coords and intent not in _DISCOVERY_INTENTS:
            if lat is not None:
                self.resolutions.append(
                    f"specificity precedence: float {float_id} scope outranks place-derived "
                    f"coordinates ({lat}, {lon}) — coordinates dropped"
                )
            lat = lon = None
            if not (intent in _DISCOVERY_INTENTS):
                radius = None
        if not keep_coords:
            lat = lon = radius = None

        # Sprint 5 (Bugs 1/2/3): a NAMED-REGION discovery is region geometry,
        # not point+radius — never assign the default radius (and never
        # record the "defaulting to 500 km" resolution) when a named region
        # scopes the search. The default remains for point-geometry searches
        # whose radius is neither explicit nor gazetteer-derived.
        if default_radius and radius is None and region is None:
            radius = _RADIUS_SEARCH_DEFAULT_KM
            self.resolutions.append(
                f"radius_search without an explicit radius: defaulting to {_RADIUS_SEARCH_DEFAULT_KM:.0f} km (established default)"
            )
        return ReasoningDecision(
            intent=intent,
            variables=tuple(variables),
            region=region,
            float_id=float_id,
            comparison_float_ids=comparison_float_ids,
            comparison_regions=comparison_regions,
            lat=lat,
            lon=lon,
            radius_km=radius,
            rule=rule,
            resolutions=tuple(self.resolutions),
        )

    def clarify(self, *, rule: str, clarification: ReasonedClarification) -> ReasoningDecision:
        return ReasoningDecision(
            intent="unknown",
            variables=(),
            region=None,
            float_id=None,
            comparison_float_ids=(),
            comparison_regions=(),
            lat=None,
            lon=None,
            radius_km=None,
            rule=rule,
            resolutions=tuple(self.resolutions),
            clarification=clarification,
        )
