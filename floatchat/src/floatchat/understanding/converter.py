"""Deterministic conversion: SemanticUnderstanding → ParsedIntent.

This module is the deterministic heart of the Phase 2 Semantic Understanding
Layer. The LLM *understands*; this converter *grounds and validates*:

* every mention is resolved against the **Phase 1 domain ontology** (the only
  domain-knowledge source) — canonical variables, regions, intent names;
* every value is range-checked against the ``ParsedIntent`` validation rules
  *before* construction;
* anything that cannot be grounded deterministically is either dropped
  (recorded as a structured ambiguity — never invented) or, when the missing
  piece is essential, escalated to a :class:`ClarificationRequest` so the
  system asks instead of guesses.

No LLM, no SQL, no DuckDB, no computation. The same deterministic tables the
regex parser relies on are reused for non-ontological grounding:
``intent_parser.seasons`` (provisional season month-windows),
``intent_parser.gazetteer`` (place-name → coordinates, itself offline-first),
and ``intent_parser.fuzzy`` (typo tolerance built from ontology data).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field as dc_field
from datetime import datetime
from functools import lru_cache
from typing import Any, Callable

from floatchat.config import settings
from floatchat.models import ParsedIntent
from floatchat.ontology.intents import INTENT_DEFINITIONS
from floatchat.ontology.regions import REGIONS
from floatchat.ontology.variables import VARIABLES
from floatchat.understanding.exceptions import SemanticUnavailableError
from floatchat.understanding.models import (
    Ambiguity,
    ComparisonMention,
    SemanticUnderstanding,
    SpatialMention,
)
from floatchat.understanding.reasoner import (
    GroundedUtterance,
    ReasoningDecision,
    SemanticReasoner,
)

logger = logging.getLogger(__name__)

_FLOAT_ID_RE = re.compile(r"^\d{5,9}$")

#: Trailing filler tokens stripped from variable mentions before grounding
#: ("oxygen levels" → "oxygen"). Prompt scaffolding, not domain knowledge.
_MENTION_FILLERS = (
    "values", "value", "levels", "level", "content", "concentration",
    "measurements", "measurement", "readings", "reading", "profile",
    "profiles", "data",
)


def _normalize_mention(text: str) -> str:
    """Lowercase, collapse whitespace, drop a leading article."""
    normalized = re.sub(r"\s+", " ", text.strip().lower())
    for article in ("the ", "a ", "an "):
        if normalized.startswith(article):
            normalized = normalized[len(article) :]
            break
    return normalized.strip()


def _strip_fillers(mention: str) -> str:
    """Strip trailing filler tokens (deterministic, bounded loop)."""
    words = mention.split()
    while len(words) > 1 and words[-1] in _MENTION_FILLERS:
        words.pop()
    return " ".join(words)


@lru_cache(maxsize=1)
def _variable_index() -> dict[str, str]:
    """Normalized mention → canonical variable, built *only* from the ontology.

    Keys: canonical names, registry aliases, parser synonyms, abbreviations
    and adjusted names — exactly the vocabulary the legacy parser knew.
    """
    index: dict[str, str] = {}
    for canonical, definition in VARIABLES.items():
        keys = {
            canonical.lower(),
            *(alias.lower() for alias in definition.aliases),
            *(syn.lower() for syn in definition.parser_synonyms),
            *(abbr.lower() for abbr in definition.abbreviations),
        }
        if definition.adjusted_name:
            keys.add(definition.adjusted_name.lower())
        for key in keys:
            index.setdefault(_normalize_mention(key), canonical)
    return index


@lru_cache(maxsize=1)
def _region_index() -> dict[str, str]:
    """Normalized mention → canonical region, built *only* from the ontology.

    Keys: canonical snake_case (also space form), display names, aliases and
    place-name spellings — the legacy parser's exact region vocabulary.
    """
    index: dict[str, str] = {}
    for canonical, region in REGIONS.items():
        keys = {
            canonical,
            canonical.replace("_", " "),
            region.display_name.lower(),
            *(alias.lower() for alias in region.aliases),
            *(place.lower() for place in region.place_names),
        }
        for key in keys:
            index.setdefault(_normalize_mention(key), canonical)
    return index


def ground_variable_mention(mention: str) -> str | None:
    """Resolve one variable mention to a canonical variable, or None.

    Chain (deterministic): exact ontology index → filler-stripped index → the
    parser's ontology-backed typo correction. No invention on failure.
    """
    index = _variable_index()
    candidate = _normalize_mention(mention)
    if candidate in index:
        return index[candidate]
    stripped = _strip_fillers(candidate)
    if stripped != candidate and stripped in index:
        return index[stripped]
    from floatchat.intent_parser.fuzzy import correct_variables_with_fuzzy

    corrected = correct_variables_with_fuzzy([mention])[0]
    if corrected in VARIABLES and corrected.lower() != candidate:
        return corrected
    return None


def ground_region_mention(mention: str) -> str | None:
    """Resolve one ocean-region mention to a canonical region, or None."""
    index = _region_index()
    candidate = _normalize_mention(mention)
    return index.get(candidate)


def ground_intent_name(name: str) -> str | None:
    """Resolve an intent name against the ontology intent vocabulary."""
    candidate = (name or "").strip().lower().replace("-", "_").replace(" ", "_")
    return candidate if candidate in INTENT_DEFINITIONS else None


@dataclass
class ClarificationRequest:
    """Structured request for clarification — ask, never guess."""

    question: str
    field: str | None = None
    candidates: list[str] = dc_field(default_factory=list)
    ambiguities: list[Ambiguity] = dc_field(default_factory=list)


@dataclass
class ConversionOutcome:
    """Result of deterministic conversion: an executable intent OR a
    clarification request (exactly one is set).

    Phase 3: carries the Semantic Reasoner's chosen ``reasoning_rule`` and
    ``reasoning_resolutions`` trace (empty while the reasoner was not needed —
    e.g. clarification gates that fire before reasoning).
    """

    parsed_intent: ParsedIntent | None
    clarification: ClarificationRequest | None
    ambiguities: list[Ambiguity] = dc_field(default_factory=list)
    understanding: SemanticUnderstanding | None = None
    reasoning_rule: str | None = None
    reasoning_resolutions: list[str] = dc_field(default_factory=list)
    # Phase 4: Conversation Intelligence trace — what context was inherited,
    # updated, or left unresolved for this request (empty when CI is inactive).
    context_resolutions: list[str] = dc_field(default_factory=list)

    @property
    def kind(self) -> str:
        return "clarification" if self.clarification is not None else "intent"


def _log_reasoning(decision: ReasoningDecision, understanding: SemanticUnderstanding) -> None:
    """Explainability trace (Phase 3): one compact line whenever the
    reasoner resolved conflicts/defaults; DEBUG for plain passthroughs."""
    if decision.resolutions:
        logger.info(
            "SEMANTIC_REASONING rule=%s intent=%s resolutions=%s",
            decision.rule,
            decision.intent,
            "; ".join(decision.resolutions),
        )
    else:
        logger.debug("SEMANTIC_REASONING rule=%s intent=%s", decision.rule, decision.intent)


class SemanticConverter:
    """Grounds and validates SemanticUnderstandings into ParsedIntents."""

    def __init__(
        self,
        *,
        min_confidence: float | None = None,
        place_resolver: Callable[[str], dict[str, Any] | None] | None = None,
        reasoner: SemanticReasoner | None = None,
        conversation_intelligence: Any | None = None,
    ) -> None:
        self._min_confidence = (
            min_confidence
            if min_confidence is not None
            else settings.semantic_min_confidence
        )
        self._place_resolver = place_resolver
        # Phase 3: the deterministic Semantic Reasoner — single authority
        # for execution-intent selection. Injectable for tests.
        self._reasoner = reasoner if reasoner is not None else SemanticReasoner()
        # Phase 4: deterministic Conversation Intelligence — resolves
        # conversational references into grounded facts BEFORE the reasoner.
        # None → single-request behaviour, byte-identical to Phase 3.
        self._conversation = conversation_intelligence

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def convert(
        self,
        understanding: SemanticUnderstanding,
        *,
        session_id: str | None = None,
    ) -> ConversionOutcome:
        """Convert one understanding into a ParsedIntent or a clarification.

        Raises SemanticUnavailableError only for unrecoverable internal
        inconsistencies (caller falls back to the regex pipeline).
        """
        ambiguities: list[Ambiguity] = list(understanding.ambiguities)

        # 1) Explicit clarification request from the understanding ------- #
        if understanding.requires_clarification:
            question = (
                understanding.clarification_question
                or self._generic_clarification_question(understanding)
            )
            return ConversionOutcome(
                parsed_intent=None,
                clarification=ClarificationRequest(
                    question=question, ambiguities=ambiguities
                ),
                ambiguities=ambiguities,
                understanding=understanding,
            )

        # 2) Confidence gate — unsure output becomes a question, not data - #
        if understanding.confidence < self._min_confidence:
            question = (
                understanding.clarification_question
                or self._generic_clarification_question(understanding)
            )
            return ConversionOutcome(
                parsed_intent=None,
                clarification=ClarificationRequest(
                    question=question, ambiguities=ambiguities
                ),
                ambiguities=ambiguities,
                understanding=understanding,
            )

        # 3) Ground every entity deterministically (vocabulary stage) ------ #
        # Phase 3: grounding produces *facts*; the Semantic Reasoner (step 5)
        # is the single authority that interprets them into an execution
        # intent. No routing happens here anymore.
        intent_hint = ground_intent_name(understanding.intent_name)
        if intent_hint is None:
            ambiguities.append(
                Ambiguity(
                    field="intent",
                    description=(
                        f"Unrecognised intent name {understanding.intent_name!r}; "
                        "passed to the reasoner as 'unknown'."
                    ),
                )
            )

        variables, ungrounded_vars = self._ground_variables(understanding)
        for mention in ungrounded_vars:
            ambiguities.append(
                Ambiguity(
                    field="variables",
                    description=f"Variable mention {mention!r} is not a known Argo variable; ignored.",
                )
            )

        grounded_regions, ungrounded_regions = self._ground_all_regions(understanding)
        comparison_regions = self._ground_comparison_regions(understanding)
        float_ids = self._ground_float_ids(understanding)

        # 4) Deterministic spatial grounding ------------------------------- #
        primary_region = grounded_regions[0] if grounded_regions else None
        lat, lon, radius_km, spatial_amb, place_unresolved = self._ground_spatial(
            understanding, primary_region
        )
        ambiguities.extend(spatial_amb)

        # 4b) Grounding-level essential check: a region was mentioned but is
        # not an ontology region, and nothing else scopes the request → ask.
        has_scope = bool(primary_region or float_ids or (lat is not None and lon is not None))
        if ungrounded_regions and not has_scope and understanding.region_mentions:
            mentions = ", ".join(repr(m) for m in ungrounded_regions)
            display_names = [r.display_name for r in REGIONS.values()][:8]
            return ConversionOutcome(
                parsed_intent=None,
                clarification=ClarificationRequest(
                    question=(
                        f"I couldn't match {mentions} to a known ocean region. "
                        f"Known regions include: {', '.join(display_names)}. "
                        "Which one did you mean?"
                    ),
                    field="region",
                    candidates=display_names,
                    ambiguities=ambiguities,
                ),
                ambiguities=ambiguities,
                understanding=understanding,
            )

        temporal_fields, temporal_amb = self._ground_temporal(understanding)
        ambiguities.extend(temporal_amb)
        depth_min, depth_max = self._ground_depth(understanding)

        # 5) Semantic Reasoning — the single authority for intent selection - #
        comparison = understanding.comparison or ComparisonMention()
        utterance = GroundedUtterance(
            intent_hint=intent_hint,
            variables=tuple(variables),
            regions=tuple(grounded_regions),
            comparison_regions=tuple(comparison_regions),
            float_ids=tuple(float_ids),
            lat=lat,
            lon=lon,
            radius_km=radius_km,
            place_mentioned=bool(understanding.place_mentions),
            profile_number=self._ground_profile_number(understanding),
            existence_check=bool(understanding.existence_check),
            operational_filter=(
                "alive"
                if (understanding.operational_filter or "").strip().lower() == "alive"
                else None
            ),
            temporal_fields=temporal_fields,
            depth_min=depth_min,
            depth_max=depth_max,
            existence_comparison_hint=bool(comparison.is_comparison),
            follow_up_reference=bool(understanding.follow_up_reference),
        )

        # 5a) Conversation Intelligence (Phase 4) — resolve conversational
        # references into explicit grounded facts BEFORE the reasoner runs.
        # Only gaps are filled; explicit grounded facts always win. Inactive
        # (None) → the utterance passes through unchanged (Phase 3 behaviour).
        context_resolutions: list[str] = []
        if self._conversation is not None and session_id:
            context = self._conversation.complete(session_id, utterance, understanding)
            utterance = context.utterance
            context_resolutions = list(context.resolutions)
            if context.clarification is not None:
                self._conversation.update(session_id, None)
                return ConversionOutcome(
                    parsed_intent=None,
                    clarification=ClarificationRequest(
                        question=context.clarification.question,
                        field=context.clarification.field,
                        candidates=list(context.clarification.candidates),
                        ambiguities=ambiguities,
                    ),
                    ambiguities=ambiguities,
                    understanding=understanding,
                    context_resolutions=context_resolutions,
                )

        decision = self._reasoner.reason(utterance)
        _log_reasoning(decision, understanding)

        if decision.clarification is not None:
            if self._conversation is not None and session_id:
                self._conversation.update(session_id, None)
            return ConversionOutcome(
                parsed_intent=None,
                clarification=ClarificationRequest(
                    question=decision.clarification.question,
                    field=decision.clarification.field,
                    candidates=list(decision.clarification.candidates),
                    ambiguities=ambiguities,
                ),
                ambiguities=ambiguities,
                understanding=understanding,
                reasoning_rule=decision.rule,
                reasoning_resolutions=list(decision.resolutions),
                context_resolutions=context_resolutions,
            )

        # 5b) Post-decision essential check: discovery objective whose place
        # could not be resolved and no other scope exists → ask.
        decision_has_scope = bool(
            decision.region
            or decision.float_id
            or decision.comparison_float_ids
            or (decision.lat is not None and decision.lon is not None)
        )
        if (
            place_unresolved
            and not decision_has_scope
            and understanding.place_mentions
            and decision.intent in ("nearest_float", "radius_search")
        ):
            return ConversionOutcome(
                parsed_intent=None,
                clarification=ClarificationRequest(
                    question=(
                        f"I couldn't locate {'/'.join(understanding.place_mentions)!r}. "
                        "Try a coastal city name (e.g. 'nearest float to Goa') or "
                        "coordinates (e.g. '15.3, 73.9')."
                    ),
                    field="location",
                    candidates=understanding.place_mentions,
                    ambiguities=ambiguities,
                ),
                ambiguities=ambiguities,
                understanding=understanding,
                reasoning_rule=decision.rule,
                reasoning_resolutions=list(decision.resolutions),
                context_resolutions=context_resolutions,
            )

        # 6) Assemble the ParsedIntent (existing validators do the rest) --- #
        fields: dict[str, Any] = {
            "intent": decision.intent,
            "variables": list(decision.variables),
            "region": decision.region,
            "float_id": decision.float_id,
            "comparison_float_ids": list(decision.comparison_float_ids),
            "comparison_regions": list(decision.comparison_regions),
            "profile_number": utterance.profile_number,
            "lat": decision.lat,
            "lon": decision.lon,
            "radius_km": decision.radius_km,
            "depth_min": depth_min,
            "depth_max": depth_max,
            "existence_check": utterance.existence_check,
            "operational_filter": utterance.operational_filter,
            **temporal_fields,
        }
        try:
            parsed = ParsedIntent(**fields)
        except Exception as exc:  # pragma: no cover - defensive; validators pre-checked
            logger.exception("Semantic conversion produced invalid ParsedIntent: %s", exc)
            raise SemanticUnavailableError(
                "Semantic conversion failed validation; falling back to regex pipeline.",
                reason="conversion_invalid",
                details={"error": str(exc)[:200]},
            ) from exc

        logger.debug(
            "Semantic conversion: intent=%s vars=%s region=%s floats=%s ambiguities=%d rule=%s",
            parsed.intent, parsed.variables, parsed.region, parsed.float_id,
            len(ambiguities), decision.rule,
        )
        # Phase 4: the active scientific focus updates deterministically
        # after each successful request (bounded-turn conversation memory).
        if self._conversation is not None and session_id:
            self._conversation.update(session_id, decision, utterance)
        return ConversionOutcome(
            parsed_intent=parsed,
            clarification=None,
            ambiguities=ambiguities,
            understanding=understanding,
            reasoning_rule=decision.rule,
            reasoning_resolutions=list(decision.resolutions),
            context_resolutions=context_resolutions,
        )

    # ------------------------------------------------------------------ #
    # Grounding helpers (all deterministic, ontology-first)
    # ------------------------------------------------------------------ #

    def _ground_variables(
        self, understanding: SemanticUnderstanding
    ) -> tuple[list[str], list[str]]:
        grounded: list[str] = []
        ungrounded: list[str] = []
        for mention in understanding.variable_mentions:
            canonical = ground_variable_mention(mention)
            if canonical is None:
                ungrounded.append(mention)
            elif canonical not in grounded:
                grounded.append(canonical)
        return grounded, ungrounded

    def _ground_all_regions(
        self, understanding: SemanticUnderstanding
    ) -> tuple[list[str], list[str]]:
        """Ground every region mention (mention order, deduped).

        Phase 3: grounding returns facts, not decisions — which region is
        *primary* and whether several regions mean a comparison is for the
        reasoner to interpret.
        """
        grounded: list[str] = []
        ungrounded: list[str] = []
        for mention in understanding.region_mentions:
            canonical = ground_region_mention(mention)
            if canonical is None:
                ungrounded.append(mention)
            elif canonical not in grounded:
                grounded.append(canonical)
        return grounded, ungrounded

    def _ground_comparison_regions(
        self, understanding: SemanticUnderstanding
    ) -> list[str]:
        comparison = understanding.comparison or ComparisonMention()
        mentions = [
            *comparison.region_mentions,
            *(understanding.region_mentions if comparison.is_comparison else []),
        ]
        grounded: list[str] = []
        for mention in mentions:
            canonical = ground_region_mention(mention)
            if canonical is not None and canonical not in grounded:
                grounded.append(canonical)
        # Facts only: the reasoner decides whether these organise a
        # comparison axis.
        return grounded

    def _ground_float_ids(
        self, understanding: SemanticUnderstanding
    ) -> list[str]:
        """Validated, deduped float ids (mention order). Primary/comparison
        organisation is decided by the reasoner, not here."""
        valid: list[str] = []
        comparison = understanding.comparison or ComparisonMention()
        for raw in [*understanding.float_ids, *comparison.float_ids]:
            digits = str(raw).strip()
            if _FLOAT_ID_RE.match(digits) and digits not in valid:
                valid.append(digits)
        return valid

    def _ground_spatial(
        self, understanding: SemanticUnderstanding, region: str | None
    ) -> tuple[float | None, float | None, float | None, list[Ambiguity], bool]:
        ambiguities: list[Ambiguity] = []
        place_unresolved = False
        spatial = understanding.spatial or SpatialMention()

        lat = spatial.lat
        lon = spatial.lon
        radius = spatial.radius_km
        if lat is not None and not (-90.0 <= lat <= 90.0):
            ambiguities.append(Ambiguity(field="spatial", description=f"Latitude {lat} out of range; ignored."))
            lat = None
        if lon is not None and not (-180.0 <= lon <= 180.0):
            ambiguities.append(Ambiguity(field="spatial", description=f"Longitude {lon} out of range; ignored."))
            lon = None
        if (lat is None) != (lon is None):
            ambiguities.append(
                Ambiguity(field="spatial", description="Latitude and longitude must come as a pair; ignored.")
            )
            lat = lon = None
        if radius is not None and radius < 0:
            ambiguities.append(Ambiguity(field="spatial", description=f"Radius {radius} invalid; ignored."))
            radius = None

        # Gazetteer grounding for place mentions — only when no coordinates
        # and no region (mirrors the regex parser's ordering rule).
        if lat is None and region is None and understanding.place_mentions:
            resolver = self._get_place_resolver()
            place = understanding.place_mentions[0]
            try:
                resolved = resolver(place) if resolver else None
            except Exception as exc:
                logger.warning("Place resolution failed for %r: %s", place, exc)
                resolved = None
            if resolved:
                lat = float(resolved["lat"])
                lon = float(resolved["lon"])
                # Sprint 5 (Bug 1 — policy reversal of the Sprint-3 note that
                # previously occupied this spot): a named place is point
                # geometry WITH the gazetteer's documented radius (Goa →
                # 100 km). When the request carries no explicit radius, the
                # gazetteer radius is the place's semantics — it must not be
                # replaced by the arbitrary 500 km default. The regex parser
                # applies the identical rule at its gazetteer call site, so
                # both parsing paths still produce identical ParsedIntents
                # (Root Principle). The 500 km default remains, but only for
                # raw-coordinate searches without any named place/region.
                if radius is None and resolved.get("radius_km") is not None:
                    radius = float(resolved["radius_km"])
            else:
                place_unresolved = True
                ambiguities.append(
                    Ambiguity(
                        field="place",
                        description=f"Place mention {place!r} could not be resolved to coordinates.",
                        candidates=understanding.place_mentions,
                    )
                )
        return lat, lon, radius, ambiguities, place_unresolved

    def _ground_temporal(
        self, understanding: SemanticUnderstanding
    ) -> tuple[dict[str, Any], list[Ambiguity]]:
        ambiguities: list[Ambiguity] = []
        temporal = understanding.temporal
        fields: dict[str, Any] = {}
        if temporal is None:  # Phase 2.1: absent temporal concept — nothing to ground
            return fields, ambiguities

        if temporal.year is not None:
            if 1900 <= temporal.year <= 2100:
                fields["year"] = temporal.year
            else:
                ambiguities.append(
                    Ambiguity(field="temporal", description=f"Year {temporal.year} out of range; ignored.")
                )
        if temporal.month is not None:
            if 1 <= temporal.month <= 12:
                fields["month"] = temporal.month
            else:
                ambiguities.append(
                    Ambiguity(field="temporal", description=f"Month {temporal.month} out of range; ignored.")
                )
        if temporal.season and "month_window" not in fields:
            from floatchat.intent_parser.seasons import (
                SEASON_MONTH_WINDOWS,
                season_start_month,
            )

            window = SEASON_MONTH_WINDOWS.get(temporal.season.strip().lower())
            if window:
                fields["month_window"] = list(window)
                if "month" not in fields:
                    fields["month"] = season_start_month(window)
            else:
                ambiguities.append(
                    Ambiguity(
                        field="temporal",
                        description=f"Season mention {temporal.season!r} has no known month window; ignored.",
                    )
                )
        for key, value in (
            ("temporal_date_start", temporal.date_start),
            ("temporal_date_end", temporal.date_end),
        ):
            if not value:
                continue
            try:
                datetime.strptime(value.strip(), "%Y-%m-%d")
            except (ValueError, AttributeError):
                ambiguities.append(
                    Ambiguity(field="temporal", description=f"Date {value!r} is not ISO format; ignored.")
                )
                continue
            fields[key] = value.strip()
        return fields, ambiguities

    @staticmethod
    def _ground_depth(
        understanding: SemanticUnderstanding,
    ) -> tuple[float | None, float | None]:
        depth = understanding.depth
        depth_min = depth.min if depth else None
        depth_max = depth.max if depth else None
        if depth_min is not None and depth_min < 0:
            depth_min = None
        if depth_max is not None and depth_max < 0:
            depth_max = None
        return depth_min, depth_max

    @staticmethod
    def _ground_profile_number(understanding: SemanticUnderstanding) -> int | None:
        number = understanding.profile_number
        if number is None or number < 1:
            return None
        return int(number)

    # ------------------------------------------------------------------ #
    # Clarification decisions
    # ------------------------------------------------------------------ #

    @staticmethod
    def _generic_clarification_question(understanding: SemanticUnderstanding) -> str:
        parts = ["I want to make sure I understood your request correctly."]
        if understanding.variable_mentions:
            parts.append(
                "I recognised these variables: "
                + ", ".join(understanding.variable_mentions)
                + "."
            )
        if understanding.region_mentions:
            parts.append(
                "Regions mentioned: " + ", ".join(understanding.region_mentions) + "."
            )
        if understanding.ambiguities:
            first = understanding.ambiguities[0]
            parts.append(f"Unclear: {first.description}")
            if first.candidates:
                parts.append("Did you mean: " + ", ".join(first.candidates) + "?")
        parts.append("Could you rephrase or add the missing detail?")
        return " ".join(parts)

    def _get_place_resolver(self) -> Callable[[str], dict[str, Any] | None] | None:
        if self._place_resolver is not None:
            return self._place_resolver
        # Lazy import keeps the understanding package import-light; the
        # gazetteer is the same deterministic offline-first source the regex
        # parser uses (local table → cache → optional Nominatim honouring
        # settings.allow_live_geocoding).
        from floatchat.intent_parser.gazetteer import resolve_place_name

        return resolve_place_name


def convert_to_parsed_intent(
    understanding: SemanticUnderstanding, **converter_kwargs: Any
) -> ConversionOutcome:
    """Convenience one-shot conversion with a fresh SemanticConverter."""
    return SemanticConverter(**converter_kwargs).convert(understanding)
