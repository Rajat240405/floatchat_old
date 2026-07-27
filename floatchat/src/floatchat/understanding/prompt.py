"""Prompt construction for the Semantic Understanding Layer (Phase 2).

The system prompt's domain vocabulary is GENERATED from the Phase 1 ontology
(:mod:`floatchat.ontology`) at runtime — never hand-copied. Adding a variable,
region or intent to the ontology automatically teaches the understanding
layer about it; no alias list is duplicated anywhere.

The prompt asks the model for *mentions* in the scientist's own words. The
LLM never emits ``ParsedIntent`` fields, canonical variables, SQL or computed
values — grounding and conversion are deterministic steps that follow.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from floatchat.ontology.concepts import CONCEPTS
from floatchat.ontology.intents import INTENT_DEFINITIONS
from floatchat.ontology.regions import REGIONS
from floatchat.ontology.variables import VARIABLES

#: Short stable filler used only inside prompt examples (kept out of the
#: ontology; it is prompt scaffolding, not domain knowledge).
_ROLE = (
    "You are the semantic understanding component of FloatChat, an Argo "
    "ocean-data assistant. Your ONLY job is to understand what the scientist "
    "means and report it as one JSON object. You must NOT answer the "
    "question, run computations, produce SQL, or invent identifiers."
)

_SCHEMA_LINES = (
    ('"intent_name"', 'one intent name from the vocabulary below, or "unknown"'),
    ('"confidence"', "your confidence from 0.0 to 1.0"),
    ('"variable_mentions"', 'ocean variables mentioned, in the user\'s words (e.g. "salt levels", "o2")'),
    ('"region_mentions"', 'named ocean regions mentioned (e.g. "arabian sea")'),
    ('"place_mentions"', 'coastal or city place mentions (e.g. "Goa", "near Mumbai")'),
    ('"float_ids"', "5-9 digit Argo float WMO identifiers, digits only"),
    ('"profile_number"', "explicit profile/cycle number — omit if none"),
    ('"temporal"', '{"year": int, "month": int, "season": string, "date_start": string, "date_end": string} — include only the parts actually present; omit the whole object if no temporal expression'),
    ('"depth"', '{"min": float, "max": float} — depth/pressure bounds; omit if none'),
    ('"spatial"', '{"lat": float, "lon": float, "radius_km": float} — explicit coordinates only; omit if none'),
    ('"comparison"', '{"is_comparison": bool, "float_ids": [...], "region_mentions": [...]} — omit if not a comparison'),
    ('"concept_mentions"', 'Argo/science concepts mentioned (e.g. "parking depth", "BGC float")'),
    ('"operational_filter"', '"alive" when the user wants only currently-active floats — omit otherwise'),
    ('"existence_check"', "true for 'is there / are there any' questions"),
    ('"follow_up_reference"', "true when the message refers to the previous turn (\"that float\", \"same region\", \"what about 2023\")"),
    ('"requires_clarification"', "true when you cannot resolve something essential and must ask instead of guessing"),
    ('"clarification_question"', "the exact question to ask when clarification is required — omit otherwise"),
    ('"ambiguities"', '[{"field": string, "description": string, "candidates": [string]}] — omit when empty'),
)

_RULES = (
    "- Output ONLY the JSON object. No prose, no markdown fences.",
    "- Only include fields that are actually present in the user's request. "
    "Omit fields that are not applicable — a missing field means 'not "
    "mentioned'. Do NOT emit null values.",
    "- Use the vocabularies below; they are the complete Argo domain you know.",
    "- Copy float identifiers digit-for-digit; never make one up. If the user "
    "says 'the latest float' or no identifier exists, leave float_ids empty.",
    "- Report variables/regions as mentions in the user's words. Do not "
    "invent canonical names — deterministic software grounds them later.",
    "- Comparisons: set comparison.is_comparison and list BOTH sides "
    "(e.g. two float ids, or two regions).",
    "- If an essential part of the request is missing (e.g. an unintelligible "
    "region, or 'show oxygen' with nowhere to look and no prior context that "
    "supplies it), set requires_clarification=true and ask ONE precise "
    "question. Never guess a value you are unsure about.",
    "- intent_name must come from the intent vocabulary. If nothing fits, "
    "use \"unknown\" with a low confidence rather than inventing an intent.",
)


def _variable_vocab_lines() -> list[str]:
    lines = []
    for canonical, definition in VARIABLES.items():
        synonyms = list(definition.parser_synonyms or ())[:5]
        hint = f"; also said as: {', '.join(synonyms)}" if synonyms else ""
        registered = "" if definition.registered else " (known, limited query support)"
        lines.append(
            f"  - {definition.display_label or canonical} [{canonical}]: "
            f"{definition.description}{hint}{registered}"
        )
    return lines


def _region_vocab_lines() -> list[str]:
    lines = []
    for region in REGIONS.values():
        aliases = f"; aliases: {', '.join(region.aliases)}" if region.aliases else ""
        lines.append(f"  - {region.display_name}{aliases}")
    return lines


def _intent_vocab_lines() -> list[str]:
    lines = []
    for definition in INTENT_DEFINITIONS.values():
        lines.append(f"  - {definition.name} ({definition.kind}): {definition.description}")
    return lines


def _concept_vocab_lines() -> list[str]:
    return [f"  - {concept.term}: {concept.definition}" for concept in CONCEPTS.values()]


@lru_cache(maxsize=1)
def build_system_prompt() -> str:
    """Assemble the system prompt from the domain ontology (cached).

    Cached because the ontology is immutable at runtime; tests that patch the
    ontology must call ``build_system_prompt.cache_clear()`` first.
    """
    sections: list[str] = [
        _ROLE,
        "",
        "OUTPUT CONTRACT (JSON object with exactly these keys):",
        *("  " + key + " — " + desc for key, desc in _SCHEMA_LINES),
        "",
        "INTENT VOCABULARY (the only intents that exist):",
        *_intent_vocab_lines(),
        "",
        "VARIABLE VOCABULARY (the only ocean variables that exist):",
        *_variable_vocab_lines(),
        "",
        "REGION VOCABULARY (the only named ocean regions that exist):",
        *_region_vocab_lines(),
        "",
        "CONCEPT VOCABULARY (Argo concepts you should recognise):",
        *_concept_vocab_lines(),
        "",
        "RULES:",
        *_RULES,
        "",
        "EXAMPLES (note how inapplicable fields are simply omitted):",
        'User: "show tembaratre in arabian sea 2024" -> {"intent_name": '
        '"profile_plot", "confidence": 0.9, "variable_mentions": '
        '["tembaratre"], "region_mentions": ["arabian sea"], "temporal": '
        '{"year": 2024}}',
        'User: "compare salinity for floats 2902403 and 2903467" -> '
        '{"intent_name": "comparison_plot", "confidence": 0.93, '
        '"variable_mentions": ["salinity"], "comparison": {"is_comparison": '
        'true, "float_ids": ["2902403", "2903467"]}}',
        'User: "how much oxygen is there near goa during monsoon" -> '
        '{"intent_name": "count_aggregate", "confidence": 0.7, '
        '"variable_mentions": ["oxygen"], "place_mentions": ["goa"], '
        '"temporal": {"season": "monsoon"}, "existence_check": true}',
        'User: "plot dissolved oxygen" -> {"intent_name": "profile_plot", '
        '"confidence": 0.85, "variable_mentions": ["dissolved oxygen"], '
        '"requires_clarification": true, "clarification_question": "Which '
        'float, region, or location should I plot oxygen for?"}',
    ]
    return "\n".join(sections)


def _context_block(conversation_context: Any | None) -> list[str]:
    """Render prior-turn context for the prompt (read-only, best-effort).

    Accepts the duck-typed ConversationContext; missing attributes are
    skipped. Context merging itself remains the resolver's deterministic job —
    this block only helps the model interpret follow-up references.
    """
    if conversation_context is None:
        return []
    lines = ["", "PRIOR CONVERSATION CONTEXT (use only to interpret references):"]
    added = False

    def _add(label: str, value: Any) -> None:
        nonlocal added
        if value not in (None, [], ""):
            lines.append(f"  {label}: {value}")
            added = True

    _add("Float", getattr(conversation_context, "last_float_id", None))
    _add(
        "Variables",
        ", ".join(getattr(conversation_context, "last_variables", []) or []) or None,
    )
    region = getattr(conversation_context, "last_region", None)
    _add("Region", region.replace("_", " ") if region else None)
    _add("Year", getattr(conversation_context, "last_year", None))
    _add("Profile", getattr(conversation_context, "last_profile_number", None))
    _add("Intent", getattr(conversation_context, "last_intent", None))
    if not added:
        return []
    return lines


def build_user_prompt(message: str, conversation_context: Any | None = None) -> str:
    """Build the per-request user prompt: the message plus prior context."""
    lines = [f"Scientist's message: {message}"]
    lines.extend(_context_block(conversation_context))
    lines.append("Return ONLY the JSON object.")
    return "\n".join(lines)
