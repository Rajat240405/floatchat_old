"""Scientific Reasoning helpers (Phase 19 Improvement 2).

Provides domain-specific scientific statements drawn from the Argo KB
without hallucination. Used by the ExplanationEngine.
"""

from typing import List


def get_scientific_reasoning(
    region: str | None, variables: List[str], data_mode_hint: str | None = None
) -> List[str]:
    """Return a list of scientifically accurate statements."""
    reasons: List[str] = []

    region_lower = (region or "").lower().replace("_", " ")

    if "arabian sea" in region_lower or "bay of bengal" in region_lower:
        if any(v.upper().startswith("DOXY") for v in variables):
            reasons.append(
                "This region naturally contains an Oxygen Minimum Zone (OMZ) between approximately 100–1000 m."
            )

    if any(v.upper().startswith("CHLA") for v in variables):
        reasons.append(
            "Surface chlorophyll indicates phytoplankton biomass and primary productivity."
        )

    if any(v.upper().startswith("PSAL") for v in variables) and "arabian sea" in region_lower:
        reasons.append(
            "High surface salinity in the Arabian Sea is typically caused by strong evaporation."
        )

    if data_mode_hint == "D":
        reasons.append(
            "Delayed-mode data has undergone expert QC and sensor drift corrections."
        )
    elif data_mode_hint == "R":
        reasons.append(
            "Real-time data may contain uncorrected sensor drift; delayed-mode is preferred for research."
        )

    return reasons