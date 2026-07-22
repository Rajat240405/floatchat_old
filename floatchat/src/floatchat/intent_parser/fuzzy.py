"""Fuzzy / typo recovery utilities (Phase 5 Part B — Expanded).

Provides lightweight Levenshtein-based correction for common variable typos.
Only suggests when confidence is high.

Phase 5: Expanded dictionary to comprehensively cover variable synonyms and
common typos across all Argo BGC variables.
"""

import difflib
import re
from typing import List, Optional


_VARIABLE_CANONICAL = [
    "TEMP",
    "PSAL",
    "DOXY",
    "CHLA",
    "NITRATE",
    "BBP700",
    "PH_IN_SITU_TOTAL",
    "DOWNWELLING_PAR",
    "DOWN_IRRADIANCE380",
    "DOWN_IRRADIANCE412",
    "DOWN_IRRADIANCE490",
]

# High-confidence typo corrections — these are always applied regardless of
# similarity score. Covers common misspellings and shorthand forms.
_TYPO_MAP = {
    # --- Temperature ---
    "TEMPARATURE": "TEMP",
    "TEMPERATURE": "TEMP",
    "TEMBAATRE": "TEMP",
    "TEMBARATRE": "TEMP",
    "TEMBARATURE": "TEMP",
    "TEMBARATUE": "TEMP",
    "TEMBARTURE": "TEMP",
    "TEMERATURE": "TEMP",
    "TEMPERATUE": "TEMP",
    "TEMPERTAURE": "TEMP",
    "TEMPEARTURE": "TEMP",
    "TEMPRAURE": "TEMP",
    "TEMPEARUTRE": "TEMP",
    "TMEPERATURE": "TEMP",
    "TEMPRATURE": "TEMP",
    "TEMPARTURE": "TEMP",
    "WATER TEMP": "TEMP",
    "SEA TEMP": "TEMP",
    "SST": "TEMP",

    # --- Salinity ---
    "SALINTY": "PSAL",
    "SALINITY": "PSAL",
    "SALINETY": "PSAL",
    "SALINATY": "PSAL",
    "SALT": "PSAL",
    "SALTN": "PSAL",
    "SALINIT": "PSAL",
    "SAILNITY": "PSAL",
    "SALNITY": "PSAL",
    "SALINIY": "PSAL",
    "SEA SALT": "PSAL",
    "WATER SALINITY": "PSAL",

    # --- Dissolved Oxygen ---
    "OXIGEN": "DOXY",
    "OXYGEN": "DOXY",
    "OXY": "DOXY",
    "DOX": "DOXY",
    "DISSOLVED OXYGEN": "DOXY",
    "DISOLVED OXYGEN": "DOXY",
    "DISSOLVED O2": "DOXY",
    "OXYGENE": "DOXY",
    "OXIGENE": "DOXY",
    "OXEGEN": "DOXY",
    "DOXYGEN": "DOXY",
    "DISSOLVED OXY": "DOXY",
    "O2": "DOXY",

    # --- Chlorophyll ---
    "CHLORPHYLL": "CHLA",
    "CHLOROPHYLL": "CHLA",
    "CHLOROPHIL": "CHLA",
    "CHLOROPHYL": "CHLA",
    "CHLOROPHLL": "CHLA",
    "CHLOROPHYLLA": "CHLA",
    "CHLOROPHILL": "CHLA",
    "CHL": "CHLA",
    "CHLOR": "CHLA",
    "CHL A": "CHLA",
    "CHL-A": "CHLA",
    "CHLOROPHYLL A": "CHLA",
    "CHLOROPHYLL-A": "CHLA",
    "PHYTOPLANKTON": "CHLA",
    "ALGAE": "CHLA",
    "GREEN": "CHLA",

    # --- Nitrate ---
    "NITRAT": "NITRATE",
    "NITRATE": "NITRATE",
    "NO3": "NITRATE",
    "NITRITE": "NITRATE",
    "NITROGEN": "NITRATE",
    "NO3-N": "NITRATE",
    "NITRTE": "NITRATE",

    # --- Backscattering ---
    "BACKSCATTERING": "BBP700",
    "BACKSCATTER": "BBP700",
    "BACK SCATTER": "BBP700",
    "BBP": "BBP700",
    "PARTICLE BACKSCATTERING": "BBP700",
    "PARTICULATE BACKSCATTER": "BBP700",
    "PARTICLES": "BBP700",

    # --- pH ---
    "PH": "PH_IN_SITU_TOTAL",
    "ACIDITY": "PH_IN_SITU_TOTAL",
    "PH LEVEL": "PH_IN_SITU_TOTAL",
    "WATER PH": "PH_IN_SITU_TOTAL",
    "OCEAN PH": "PH_IN_SITU_TOTAL",

    # --- PAR ---
    "PAR": "DOWNWELLING_PAR",
    "PHOTOSYNTHETICALLY ACTIVE RADIATION": "DOWNWELLING_PAR",
    "PHOTOSYNTHETIC RADIATION": "DOWNWELLING_PAR",
    "LIGHT": "DOWNWELLING_PAR",
    "SUNLIGHT": "DOWNWELLING_PAR",
    "IRRADIANCE": "DOWNWELLING_PAR",

    # --- Downwelling Irradiance ---
    "IR380": "DOWN_IRRADIANCE380",
    "IRRADIANCE 380": "DOWN_IRRADIANCE380",
    "IR412": "DOWN_IRRADIANCE412",
    "IRRADIANCE 412": "DOWN_IRRADIANCE412",
    "IR490": "DOWN_IRRADIANCE490",
    "IRRADIANCE 490": "DOWN_IRRADIANCE490",
}


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
