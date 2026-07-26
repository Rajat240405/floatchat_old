"""Canonical scientific concept glossary (Domain Ontology, Phase 1).

Reusable Argo/BGC terminology in one place. The full vetted question-answer
text stays in ``llm_service/knowledge_base.json`` (the knowledge base remains
the answer source); this glossary centralizes the *terms* — canonical name,
one-line definition and aliases — and links each concept to its knowledge
base entry where one exists.

Phase 1 has no behavioural consumer for this module; it is the reference
vocabulary later phases (semantic understanding) will build on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple


@dataclass(frozen=True)
class ScientificConcept:
    """Canonical definition of a reusable Argo scientific concept."""

    concept_id: str
    term: str
    definition: str
    aliases: Tuple[str, ...] = ()
    kb_entry_id: Optional[str] = None
    """Link to the vetted Q&A entry in ``llm_service/knowledge_base.json``."""


CONCEPTS: dict[str, ScientificConcept] = {
    "argo": ScientificConcept(
        "argo",
        "Argo",
        "International program maintaining a global array of free-drifting profiling floats that measure the temperature and salinity of the upper ocean.",
        ("argo program", "argo float"),
        "what_is_argo",
    ),
    "core_float": ScientificConcept(
        "core_float",
        "Core float",
        "Standard Argo float measuring pressure, temperature and salinity (CTD) on a ~10-day cycle between the surface and 2000 dbar.",
        ("core argo", "core argo float", "ctd float"),
        "what_is_core_float",
    ),
    "bgc_float": ScientificConcept(
        "bgc_float",
        "BGC float",
        "Biogeochemical Argo float: a Core float additionally equipped with sensors such as oxygen, chlorophyll, nitrate, pH, backscatter and irradiance.",
        ("bgc argo", "bgc argo float", "biogeochemical float"),
        "what_is_bgc_float",
    ),
    "profile": ScientificConcept(
        "profile",
        "Profile",
        "One set of vertical measurements collected by a float, typically during its ascent from parking/profiling depth to the surface.",
        ("vertical profile",),
        "profile_cycle",
    ),
    "cycle": ScientificConcept(
        "cycle",
        "Cycle",
        "One full mission loop of a float (descent, drift at parking depth, profiling ascent, surface transmission), identified by its cycle number.",
        ("cycle number", "profile number"),
        "profile_cycle",
    ),
    "parking_depth": ScientificConcept(
        "parking_depth",
        "Parking depth",
        "Depth (commonly ~1000 dbar) at which a float drifts with the currents between profiles.",
        ("drift depth", "park depth"),
        "parking_depth",
    ),
    "profiling_depth": ScientificConcept(
        "profiling_depth",
        "Profiling depth",
        "Maximum depth from which a float starts its profiling ascent (commonly 2000 dbar for Core and BGC floats).",
        ("profile depth",),
        "profile_depth",
    ),
    "trajectory": ScientificConcept(
        "trajectory",
        "Trajectory",
        "The successive surface positions of a float between cycles, driven by currents at parking depth and at the surface.",
        ("float trajectory", "drift track"),
        None,
    ),
    "delayed_mode": ScientificConcept(
        "delayed_mode",
        "Delayed mode",
        "Argo data mode in which an expert scientist has reviewed and adjusted the measurements (highest quality; filenames/values marked D or _ADJUSTED).",
        ("delayed-mode", "adjusted data", "d files"),
        "data_quality",
    ),
    "real_time_mode": ScientificConcept(
        "real_time_mode",
        "Real time mode",
        "Argo data mode distributed within ~24 hours of reception with automatic (not expert) quality control.",
        ("real-time", "realtime", "r files"),
        "data_quality",
    ),
    "wmo_id": ScientificConcept(
        "wmo_id",
        "WMO ID",
        "Unique 7-digit World Meteorological Organization identifier assigned to each Argo float.",
        ("wmo", "float id", "wmo number"),
        "wmo_id",
    ),
    "gdac": ScientificConcept(
        "gdac",
        "GDAC",
        "Global Data Assembly Centre — one of the two global Argo data repositories (IFREMER/Coriolis, France and US GODAE).",
        ("global data assembly centre",),
        "gdac",
    ),
    "dac": ScientificConcept(
        "dac",
        "DAC",
        "Data Assembly Centre — a national/regional centre responsible for processing and distributing data from its floats (e.g. INCOIS for India).",
        ("data assembly centre",),
        None,
    ),
    "telemetry": ScientificConcept(
        "telemetry",
        "Telemetry",
        "Satellite communication system (Argos or Iridium) a float uses to transmit its measurements and GPS fixes at the surface.",
        ("data transmission", "satellite telemetry"),
        "telemetry",
    ),
}
