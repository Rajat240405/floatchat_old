"""Fuzzy / typo recovery utilities (Phase 5 Part B — Expanded).

Provides lightweight Levenshtein-based correction for common variable typos.
Only suggests when confidence is high.

Phase 5: Expanded dictionary to comprehensively cover variable synonyms and
common typos across all Argo BGC variables.
"""

import difflib
import re
from typing import List, Optional

from floatchat.ontology.variables import (
    PARSER_VARIABLE_ORDER as _PARSER_VARIABLE_ORDER,
    TYPO_CORRECTIONS as _ONTOLOGY_TYPO_CORRECTIONS,
)

# Ontology 2.0 (Phase 1): the canonical variable list and the high-confidence
# typo-correction map live in the domain ontology (verbatim relocation).
# Ordering is preserved exactly — difflib tie-breaking makes it observable.

_VARIABLE_CANONICAL = list(_PARSER_VARIABLE_ORDER)

# High-confidence typo corrections — these are always applied regardless of
# similarity score. Covers common misspellings and shorthand forms.
_TYPO_MAP = _ONTOLOGY_TYPO_CORRECTIONS


def correct_variable_typo(token: str, cutoff: float = 0.75) -> Optional[str]:
    """Return the closest canonical variable if similarity is high enough."""
    matches = difflib.get_close_matches(
        token.upper(), _VARIABLE_CANONICAL, n=1, cutoff=cutoff
    )
    return matches[0] if matches else None


def _normalize_for_lookup(text: str) -> str:
    """Normalize a text string for typo map lookup."""
    # Collapse whitespace, strip, uppercase
    return re.sub(r'\s+', ' ', text.upper().strip())


def correct_variables_with_fuzzy(variables: List[str]) -> List[str]:
    """Apply fuzzy correction to a list of extracted variable tokens.

    Phase 5: Enhanced with multi-word synonym matching and more aggressive
    typo correction. First checks the high-confidence _TYPO_MAP, then falls
    back to difflib similarity. This ensures 'tembaratre' and 'chlorphyll'
    are corrected before conversational context is applied.
    """
    corrected = []
    for v in variables:
        upper = v.upper()
        normalized = _normalize_for_lookup(v)
        
        if upper in _VARIABLE_CANONICAL:
            corrected.append(upper)
            continue

        # High-confidence typo map first (try normalized form)
        if normalized in _TYPO_MAP:
            corrected.append(_TYPO_MAP[normalized])
            continue
        if upper in _TYPO_MAP:
            corrected.append(_TYPO_MAP[upper])
            continue

        # Then fuzzy similarity against canonical names
        suggestion = correct_variable_typo(v)
        if suggestion:
            corrected.append(suggestion)
        else:
            # Try fuzzy matching against typo map keys too
            typo_matches = difflib.get_close_matches(
                upper, list(_TYPO_MAP.keys()), n=1, cutoff=0.8
            )
            if typo_matches:
                corrected.append(_TYPO_MAP[typo_matches[0]])
            else:
                corrected.append(v)  # keep original
    return corrected
