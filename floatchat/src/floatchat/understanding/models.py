"""SemanticUnderstanding — the Phase 2 *understanding contract*.

This object records **what the scientist means**, before any deterministic
execution planning. It is produced by an LLM (structured JSON) inside the
Semantic Understanding Layer and is deliberately *not* a ``ParsedIntent``:

* ``ParsedIntent`` (:mod:`floatchat.models.intent`) remains the **execution
  contract**: canonical variable names, snake_case regions, validated ranges
  — the only object the Planner/QueryEngine may consume.
* ``SemanticUnderstanding`` is the **understanding contract**: natural-language
  *mentions* (``"salt levels"``, ``"the bay of bengal"``), ambiguity records,
  clarification requests, follow-up signals and a self-reported confidence.

The two contracts never mix: a deterministic converter
(:mod:`floatchat.understanding.converter`) grounds every mention against the
Phase 1 domain ontology and either produces a valid ``ParsedIntent`` or a
structured clarification request — it never invents values.

Design rules for this layer (per Phase 2 specification):
  * understand language only — never execute, never generate SQL, never touch
    DuckDB, never make routing decisions based on implementation details,
    never perform scientific computation;
  * the Phase 1 ontology is the only domain-knowledge source for grounding.

All sub-models tolerate provider quirks: unknown keys are ignored, scalar
values where a list is expected are wrapped, and **explicit ``null`` for an
absent concept is accepted** (Phase 2.1 — live logs showed models emitting
``"temporal": null`` for queries with no temporal expression; that is natural
language, not an error). An absent concept is represented as ``None`` — the
converter treats it as *not mentioned* and never invents content.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _coerce_str_list(value: Any) -> list[str]:
    """Tolerantly coerce LLM output into a clean list of non-empty strings."""
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    out: list[str] = []
    for item in value:
        if item is None:
            continue
        text = str(item).strip()
        if text:
            out.append(text)
    return out


def _tolerant_bool(value: Any) -> bool | None:
    """Coerce provider booleans (incl. "yes"/"no" strings); junk → None."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "yes", "1"):
            return True
        if lowered in ("false", "no", "0", ""):
            return False
        return None
    if isinstance(value, (int, float)):
        return bool(value)
    return None


class TemporalMention(BaseModel):
    """Temporal expressions as understood from the message."""

    model_config = ConfigDict(extra="ignore")

    year: int | None = None
    month: int | None = None
    #: Season token as understood ("monsoon", "winter", …). Resolved
    #: deterministically to a month window by the converter.
    season: str | None = None
    #: Explicit ISO date bounds ("2024-01-01"), if the scientist gave them.
    date_start: str | None = None
    date_end: str | None = None


class DepthMention(BaseModel):
    """Depth/pressure bounds in metres (or dbar), as understood."""

    model_config = ConfigDict(extra="ignore")

    min: float | None = None
    max: float | None = None


class SpatialMention(BaseModel):
    """Explicit coordinates, as understood."""

    model_config = ConfigDict(extra="ignore")

    lat: float | None = None
    lon: float | None = None
    radius_km: float | None = None


class ComparisonMention(BaseModel):
    """Comparison structure, as understood (compare X with Y)."""

    model_config = ConfigDict(extra="ignore")

    is_comparison: bool = False
    float_ids: list[str] = Field(default_factory=list)
    region_mentions: list[str] = Field(default_factory=list)

    _wrap_floats = field_validator("float_ids", "region_mentions", mode="before")(
        _coerce_str_list
    )


class Ambiguity(BaseModel):
    """One structured ambiguity — the alternative to inventing values."""

    model_config = ConfigDict(extra="ignore")

    field: str
    description: str
    candidates: list[str] = Field(default_factory=list)

    _wrap = field_validator("candidates", mode="before")(_coerce_str_list)


class SemanticUnderstanding(BaseModel):
    """What the scientist means — the LLM-facing understanding contract.

    Every entity is a *mention* in the scientist's words (not a canonical
    execution value). Grounding to canonical ontology identifiers is the
    deterministic converter's job.
    """

    model_config = ConfigDict(extra="ignore")

    #: Canonical intent name from the ontology intent vocabulary, or "unknown".
    intent_name: str = "unknown"
    #: Model-reported confidence in [0, 1]. Clamped for provider tolerance;
    #: gated deterministically by the converter (``semantic_min_confidence``).
    confidence: float = 0.0

    # --- Entity mentions (natural language, ungrounded by design) ---------- #
    variable_mentions: list[str] = Field(default_factory=list)
    region_mentions: list[str] = Field(default_factory=list)
    #: Coastal/city place mentions ("Goa", "near Mumbai") — distinct from
    #: ocean-region mentions; ground via the deterministic gazetteer.
    place_mentions: list[str] = Field(default_factory=list)
    float_ids: list[str] = Field(default_factory=list)
    profile_number: int | None = None
    #: Scientific concept mentions ("BGC float", "parking depth"). Recorded
    #: for completeness; Phase 2 does not act on them (the Traffic-Cop KB
    #: path is unchanged), but understanding them is part of the contract.
    concept_mentions: list[str] = Field(default_factory=list)

    # --- Optional structured concepts --------------------------------------- #
    # Phase 2.1: these are None when the concept simply does not exist in the
    # request ("Plot dissolved oxygen" has no temporal/spatial/comparison
    # content). Absent concepts are NOT validation failures. The converter
    # treats None as "not mentioned".
    temporal: TemporalMention | None = None
    depth: DepthMention | None = None
    spatial: SpatialMention | None = None
    comparison: ComparisonMention | None = None

    #: "alive" when the scientist wants only currently-active floats.
    operational_filter: str | None = None
    #: True when a count question is really an existence ("is there …") check.
    #: None when the model did not say (treated as False by the converter).
    existence_check: bool | None = None

    # --- Conversation / ambiguity signalling -------------------------------- #
    #: True when the message refers to the previous turn ("that float",
    #: "same region"). Context merging itself stays deterministic (resolver).
    #: None when the model did not say.
    follow_up_reference: bool | None = None
    requires_clarification: bool = False
    clarification_question: str | None = None
    ambiguities: list[Ambiguity] = Field(default_factory=list)

    # --- Validators (tolerant, deterministic) ------------------------------ #
    _wrap = field_validator(
        "variable_mentions",
        "region_mentions",
        "place_mentions",
        "float_ids",
        "concept_mentions",
        mode="before",
    )(_coerce_str_list)

    @field_validator("temporal", "depth", "spatial", "comparison", mode="before")
    @classmethod
    def _tolerant_nested(cls, value: Any) -> Any:
        """Accept None, a dict, or an existing mention instance; junk → None.

        Phase 2.1: models often emit explicit nulls — or prose like ``"none"``
        — for concepts that do not exist in the request. Both mean "absent".
        """
        if value is None:
            return None
        if isinstance(value, (TemporalMention, DepthMention, SpatialMention, ComparisonMention, dict)):
            return value
        if isinstance(value, str) and value.strip().lower() in ("none", "null", "n/a", ""):
            return None
        return None

    _tolerant_existence = field_validator("existence_check", mode="before")(_tolerant_bool)
    _tolerant_followup = field_validator("follow_up_reference", mode="before")(_tolerant_bool)

    @field_validator("requires_clarification", mode="before")
    @classmethod
    def _tolerant_required_flag(cls, value: Any) -> bool:
        coerced = _tolerant_bool(value)
        return bool(coerced)

    @field_validator("profile_number", mode="before")
    @classmethod
    def _tolerant_profile_number(cls, value: Any) -> int | None:
        if value is None or isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
        return None

    @field_validator("ambiguities", mode="before")
    @classmethod
    def _tolerant_ambiguities(cls, value: Any) -> list[Any]:
        """Keep only dict/instance items; anything else means 'no records'."""
        if value is None or not isinstance(value, (list, tuple)):
            return []
        return [item for item in value if isinstance(item, dict)]

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_confidence(cls, value: Any) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, number))

    @field_validator("intent_name", mode="before")
    @classmethod
    def _tolerant_intent_name(cls, value: Any) -> str:
        """Null/garbage intent names mean 'unknown', not a validation failure."""
        if value is None:
            return "unknown"
        text = str(value).strip()
        return text if text else "unknown"
