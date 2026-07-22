"""Verification & Transparency Layer (Phase 20 Improvement 1 + 3)."""

from typing import Any, Dict, List
from ..models.intent import ParsedIntent
from ..models.metadata import MetadataRecord


def build_verification_section(
    intent: ParsedIntent,
    records: List[MetadataRecord],
    resolved_variables: List[str],
    alias_map: Dict[str, str],
) -> Dict[str, Any]:
    """Build the verification section shown to scientists."""
    if not records:
        return {}

    first = records[0]
    return {
        "selection_reason": {
            "region_matched": intent.region,
            "variables_requested": intent.variables,
            "year": intent.year,
            "float_id": intent.float_id,
        },
        "verification": {
            "dac": first.institution,
            "profile_files": [r.file for r in records[:3]],
            "observation_dates": [r.date.isoformat() for r in records if r.date][:3],
            "variables_present": resolved_variables,
            "adjusted_variables_used": [alias_map.get(v, v) for v in resolved_variables],
            "source": "Official Argo GDAC (https://data-argo.ifremer.fr)",
        },
    }


def build_pipeline_trace(
    intent: ParsedIntent, timings: Dict[str, float], context_used: bool
) -> Dict[str, Any]:
    """Developer diagnostics trace (Improvement 3)."""
    return {
        "pipeline": [
            "User Query",
            "Intent Parser + Fuzzy Correction",
            "Conversation Memory",
            "Variable Resolution (adjusted preferred)",
            "Metadata Search (polygon filter)",
            "Profiles Selected",
            "NetCDF Fetch + Read",
            "Visualization",
            "Scientific Interpretation",
            "Verification & Suggestions",
        ],
        "timings_ms": {k: round(v * 1000, 1) for k, v in timings.items()},
        "context_reused": context_used,
        "inferred_variables": intent.variables,
    }