"""Deterministic fallback normalizer using RapidFuzz."""

import logging
from typing import Dict

try:
    from rapidfuzz import process, fuzz
except ImportError:
    from difflib import get_close_matches as process  # type: ignore

    fuzz = None  # type: ignore

logger = logging.getLogger(__name__)


# High-confidence canonical targets (used by both LLM and fallback)
_CANONICAL_TERMS = [
    "temperature",
    "chlorophyll",
    "oxygen",
    "dissolved oxygen",
    "salinity",
    "Arabian Sea",
    "Bay of Bengal",
    "Southern Ocean",
    "Mediterranean Sea",
    "TEMP",
    "CHLA",
    "DOXY",
    "PSAL",
]

# Lightweight abbreviation expansion (deterministic)
_ABBREV_MAP: Dict[str, str] = {
    "chl": "chlorophyll",
    "temp": "temperature",
    "dox": "dissolved oxygen",
    "o2": "oxygen",
    "psal": "salinity",
}


class FallbackQueryNormalizer:
    """Fast deterministic normalizer used when LLM is unavailable.

    Only corrects obvious spelling errors. Never changes correctly
    spelled scientific terms or region names.
    """

    def normalize(self, query: str) -> str:
        if not query:
            return query

        original = query
        text = query.lower()

        # 1. Abbreviation expansion (safe)
        for abbr, full in _ABBREV_MAP.items():
            if abbr in text.split():  # whole word only
                text = text.replace(abbr, full)

        # 2. Only correct very obvious typos (high threshold)
        words = text.split()
        corrected = []
        for word in words:
            if fuzz:
                match, score, _ = process.extractOne(
                    word, _CANONICAL_TERMS, scorer=fuzz.ratio
                )
                # Only correct if extremely close (typo) and not already correct
                if score >= 92 and word != match.lower():
                    corrected.append(match)
                    continue
            corrected.append(word)

        result = " ".join(corrected)
        if result != original:
            logger.info("Fallback normalized: %r → %r", original, result)
        return result