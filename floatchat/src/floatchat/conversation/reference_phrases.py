"""Reference phrase detector for Priority 2: Conversation Context Repair.

Determines whether the user's message contains an explicit reference phrase
that signals intent to inherit context from a previous turn.

WITHOUT a reference phrase, NO context is inherited (each query stands alone).
WITH a reference phrase, ONLY the referenced fields are inherited.

Reference phrase taxonomy:
  - Spatial: "same region", "there", "that area", "same place"
  - Temporal: "same year", "same time", "that period"
  - Variable: "same variable", "same thing", "that variable"
  - Float: "same float", "that float", "it" (when referring to a float)
  - General: "same", "that", "compare that", "what about"
  - Metadata: "it" after a float query → inherit float_id only
"""

import re
import logging

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Reference phrase patterns — each pattern signals that the user WANTS to
# inherit the corresponding context field from the previous turn.
# --------------------------------------------------------------------------- #

# Spatial references → inherit region
_SPATIAL_REF_PATTERNS = [
    re.compile(r"\bsame\s+region\b", re.IGNORECASE),
    re.compile(r"\bsame\s+area\b", re.IGNORECASE),
    re.compile(r"\bsame\s+place\b", re.IGNORECASE),
    re.compile(r"\bthere\b", re.IGNORECASE),
    re.compile(r"\bthat\s+region\b", re.IGNORECASE),
    re.compile(r"\bthat\s+area\b", re.IGNORECASE),
    re.compile(r"\bin\s+the\s+same\s+place\b", re.IGNORECASE),
]

# Temporal references → inherit year
_TEMPORAL_REF_PATTERNS = [
    re.compile(r"\bsame\s+year\b", re.IGNORECASE),
    re.compile(r"\bsame\s+time\b", re.IGNORECASE),
    re.compile(r"\bthat\s+year\b", re.IGNORECASE),
    re.compile(r"\bthat\s+time\b", re.IGNORECASE),
    re.compile(r"\bthat\s+period\b", re.IGNORECASE),
]

# Variable references → inherit variables
_VARIABLE_REF_PATTERNS = [
    re.compile(r"\bsame\s+variable\b", re.IGNORECASE),
    re.compile(r"\bsame\s+thing\b", re.IGNORECASE),
    re.compile(r"\bthat\s+variable\b", re.IGNORECASE),
    re.compile(r"\bsame\s+parameter\b", re.IGNORECASE),
]

# Float references → inherit float_id
_FLOAT_REF_PATTERNS = [
    re.compile(r"\bsame\s+float\b", re.IGNORECASE),
    re.compile(r"\bthat\s+float\b", re.IGNORECASE),
    re.compile(r"\bthis\s+float\b", re.IGNORECASE),
]

# General reference phrases → inherit ALL context fields
# These are broad anaphoric references that signal the user is continuing
# the same topic. Examples: "same for Bay of Bengal", "compare that with..."
# Note: "same region" and "same year" are SPECIFIC references, not general.
# But "same region but in 2024" implies keeping the same variables too.
_GENERAL_REF_PATTERNS = [
    re.compile(r"\bsame\b(?!\s+(region|area|place|year|time|variable|thing|float|parameter))", re.IGNORECASE),
    re.compile(r"\bcompare\s+(that|those|the)\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+about\b", re.IGNORECASE),
    re.compile(r"\bhow\s+about\b", re.IGNORECASE),
    # Phase 7: operational follow-ups that implicitly reference previous context
    re.compile(r"\b(?:latest|newest|most recent|recent)\s+(?:float|profile|cycle|data)\b", re.IGNORECASE),
    re.compile(r"\b(?:latest|newest)\s+float\b", re.IGNORECASE),
]

# Compound reference patterns — when a specific reference ("same region") is
# combined with a temporal or variable modification, it implies inheriting
# ALL fields, not just the specifically referenced one. E.g.:
# "same region but in 2024" = same region + same variable + new year
_COMPOUND_REF_PATTERNS = [
    re.compile(r"\bsame\s+(region|area|place)\b.*\b(in\s+)?(19|20)\d{2}\b", re.IGNORECASE),
    re.compile(r"\bsame\s+(year|time|period)\b.*\b(in\s+)?(the\s+)?(arabian|bay|indian|bengal)\b", re.IGNORECASE),
]

# "it" as a reference → context-dependent:
#   - After a float query → inherit float_id only
#   - After a data query → inherit the dominant context (variable/region/year)
# We detect "it" separately because its meaning depends on context.
_IT_PATTERN = re.compile(r"\bit\b", re.IGNORECASE)

# Metadata follow-up patterns → always route to metadata_lookup,
# inherit float_id ONLY (never inherit variable/region/year)
_METADATA_FOLLOWUP_PATTERNS = [
    re.compile(r"\bbattery\b", re.IGNORECASE),
    re.compile(r"\bsensors?\b", re.IGNORECASE),
    re.compile(r"\bmetadata\b", re.IGNORECASE),
    re.compile(r"\bstatus\b", re.IGNORECASE),
    re.compile(r"\blasts?\s+report\b", re.IGNORECASE),
    re.compile(r"\bfirst\s+report\b", re.IGNORECASE),
    re.compile(r"\bparking\s+depth\b", re.IGNORECASE),
    re.compile(r"\bprofiler\b", re.IGNORECASE),
    re.compile(r"\bdac\b", re.IGNORECASE),
    re.compile(r"\binstitution\b", re.IGNORECASE),
    re.compile(r"\bmanufacturer\b", re.IGNORECASE),
    re.compile(r"\binfo(?:rmation)?\b", re.IGNORECASE),
    re.compile(r"\bdetails\b", re.IGNORECASE),
    re.compile(r"\bregistry\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+(?:is|are)\s+(?:the\s+)?(?:battery|sensor|status|manufacturer|dac)\b", re.IGNORECASE),
]


class ReferencePhraseResult:
    """Result of reference phrase detection on a user message.

    Each boolean flag indicates whether that context field SHOULD be inherited.
    """

    def __init__(
        self,
        has_reference: bool = False,
        inherit_region: bool = False,
        inherit_year: bool = False,
        inherit_variables: bool = False,
        inherit_float_id: bool = False,
        is_metadata_followup: bool = False,
        has_general_ref: bool = False,
        has_it_ref: bool = False,
    ) -> None:
        self.has_reference = has_reference
        self.inherit_region = inherit_region
        self.inherit_year = inherit_year
        self.inherit_variables = inherit_variables
        self.inherit_float_id = inherit_float_id
        self.is_metadata_followup = is_metadata_followup
        self.has_general_ref = has_general_ref
        self.has_it_ref = has_it_ref

    def __repr__(self) -> str:
        parts = []
        if self.inherit_region:
            parts.append("region")
        if self.inherit_year:
            parts.append("year")
        if self.inherit_variables:
            parts.append("vars")
        if self.inherit_float_id:
            parts.append("float_id")
        if self.is_metadata_followup:
            parts.append("METADATA_FOLLOWUP")
        if self.has_general_ref:
            parts.append("GENERAL")
        if self.has_it_ref:
            parts.append("IT")
        return f"ReferencePhraseResult({'|'.join(parts) or 'NONE'})"


def detect_reference_phrases(message: str) -> ReferencePhraseResult:
    """Analyze *message* for explicit reference phrases.

    Returns a :class:`ReferencePhraseResult` indicating which context fields
    the user intends to inherit.

    Rules:
        1. NO reference phrases → NO inheritance at all.
        2. Specific reference phrase → inherit ONLY that field.
        3. General reference ("same", "that", "what about") → inherit ALL
           context fields (region, year, variables, float_id).
        4. "it" after a float query → inherit float_id ONLY.
        5. Metadata follow-up patterns → inherit float_id ONLY, route to
           metadata_lookup, never inherit variable/region/year.
        6. New explicit values in the parsed intent ALWAYS override inherited
           values (this is enforced in merge_context, not here).
    """
    text = message.strip()

    # Check metadata follow-up first — highest priority because it
    # fundamentally changes the routing and inheritance behavior
    is_metadata_followup = any(p.search(text) for p in _METADATA_FOLLOWUP_PATTERNS)

    # Check specific reference patterns
    inherit_region = any(p.search(text) for p in _SPATIAL_REF_PATTERNS)
    inherit_year = any(p.search(text) for p in _TEMPORAL_REF_PATTERNS)
    inherit_variables = any(p.search(text) for p in _VARIABLE_REF_PATTERNS)
    inherit_float_id = any(p.search(text) for p in _FLOAT_REF_PATTERNS)

    # Check general reference patterns
    has_general_ref = any(p.search(text) for p in _GENERAL_REF_PATTERNS)

    # Check compound reference patterns (e.g., "same region but in 2024")
    has_compound_ref = any(p.search(text) for p in _COMPOUND_REF_PATTERNS)

    # Check "it" reference
    has_it_ref = bool(_IT_PATTERN.search(text))

    # If general reference, inherit ALL fields
    if has_general_ref:
        inherit_region = True
        inherit_year = True
        inherit_variables = True
        inherit_float_id = True

    # If compound reference, also inherit variables (the user is modifying
    # one aspect but expects the rest to stay the same)
    if has_compound_ref:
        inherit_variables = True

    # If "it" is present (and no more specific float reference was detected),
    # it typically means the user is referring to the same entity.
    # After a float discussion, "it" = the float.
    # After a data query, "it" = the same topic.
    # We set float_id inheritance for "it" only when no other reference
    # phrase is more specific.
    if has_it_ref and not inherit_float_id and not has_general_ref:
        # "it" by itself — will be resolved by merge_context based on
        # whether the previous intent was float-centric
        inherit_float_id = True  # tentative; merge_context will check

    # If metadata follow-up: ONLY float_id is inherited, never vars/region/year
    if is_metadata_followup:
        inherit_region = False
        inherit_year = False
        inherit_variables = False
        # float_id inheritance for metadata is handled by "it" or explicit float ref
        # If no specific float ref, but "it" is present or previous was float-centric,
        # we still allow float_id inheritance
        inherit_float_id = inherit_float_id or has_it_ref

    has_reference = (
        inherit_region or inherit_year or inherit_variables
        or inherit_float_id or is_metadata_followup or has_general_ref
    )

    result = ReferencePhraseResult(
        has_reference=has_reference,
        inherit_region=inherit_region,
        inherit_year=inherit_year,
        inherit_variables=inherit_variables,
        inherit_float_id=inherit_float_id,
        is_metadata_followup=is_metadata_followup,
        has_general_ref=has_general_ref,
        has_it_ref=has_it_ref,
    )

    logger.debug(
        "Reference phrase detection for %r: %s",
        text,
        result,
    )

    return result
