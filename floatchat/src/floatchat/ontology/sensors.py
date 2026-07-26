"""Canonical sensor / platform vocabulary (Domain Ontology, Phase 1).

Single source of truth for Argo sensor and platform knowledge. Contents
relocated *verbatim* from their previous fragmented homes (behaviour-neutral
move):

================================  ==============================================
Ontology member                   Previous home(s)
================================  ==============================================
``SensorDefinition`` tokens       ``query_engine.helpers`` (``_VAR_SENSOR_MAP``)
                                  and ``floatchat.ontology.variables``
                                  (``sensor_keywords``)
``PLATFORM_MODELS``               ``data_lake.duckdb_lake._PROFILER_MANUFACTURER_MAP``
                                  (29 codes → platform + manufacturer)
``PlatformModel.shortlist``       the 10-code legacy ``PROFILER_MAP`` copies in
                                  ``data_lake.duckdb_lake.query_metadata_lookup``
                                  and ``query_engine.executors.metadata``
``manufacturer_short_lookup``     ``query_engine.helpers._PROFILER_MFR_MAP``
                                  (manufacturer names without country suffix)
``BGC_VARIABLE_MARKER_TOKENS``    identical tuple in ``query_engine.helpers``,
                                  ``query_engine.executors.trajectory`` and
                                  ``query_engine.response_builder``
``NETWORK_CORE`` / ``NETWORK_BGC``  the ``"Core Argo"`` / ``"BGC Argo"`` string
                                  literals duplicated across the engine, the
                                  floats service and the data lake
``DAC_NAMES``                     identical ``DAC_MAP`` copies in
                                  ``data_lake.duckdb_lake`` and
                                  ``query_engine.executors.metadata``
================================  ==============================================
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Tuple

from floatchat.ontology.variables import VARIABLES


# --------------------------------------------------------------------------- #
# Argo network vocabulary
# --------------------------------------------------------------------------- #

#: Network label for floats carrying only core CTD sensors.
NETWORK_CORE = "Core Argo"

#: Network label for floats carrying any biogeochemical sensor.
NETWORK_BGC = "BGC Argo"


# --------------------------------------------------------------------------- #
# Canonical sensors
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class SensorDefinition:
    """Canonical sensor knowledge: aliases and measured variables."""

    canonical: str
    display_name: str
    description: str
    tokens: Tuple[str, ...]
    """Uppercase tokens used to detect this sensor in metadata/registry text."""
    variables: Tuple[str, ...]
    """Canonical variables this sensor measures."""


SENSORS: dict[str, SensorDefinition] = {
    "CTD": SensorDefinition(
        canonical="CTD",
        display_name="CTD (Conductivity-Temperature-Depth)",
        description="Core Argo sensor package measuring pressure, temperature and conductivity (salinity).",
        tokens=("CTD",),
        variables=("PRES", "TEMP", "PSAL"),
    ),
    "OPTODE": SensorDefinition(
        canonical="OPTODE",
        display_name="Oxygen optode (Aanderaa)",
        description="Optical dissolved-oxygen sensor carried by BGC floats.",
        tokens=("OPTODE", "DOXY", "OXYGEN", "AANDERAA"),
        variables=("DOXY",),
    ),
    "FLUOROMETER": SensorDefinition(
        canonical="FLUOROMETER",
        display_name="Chlorophyll fluorometer (ECO)",
        description="Fluorometer estimating chlorophyll-a concentration (often part of an ECO optical puck).",
        tokens=("FLUOROMETER", "CHLA", "CHLOROPHYLL", "ECO"),
        variables=("CHLA",),
    ),
    "BACKSCATTER_SENSOR": SensorDefinition(
        canonical="BACKSCATTER_SENSOR",
        display_name="Backscattering sensor (ECO FLBB)",
        description="Optical backscattering sensor measuring particle load (bbp700).",
        tokens=("BACKSCATTER", "BBP", "ECO", "FLBBCD"),
        variables=("BBP700",),
    ),
    "NITRATE_SENSOR": SensorDefinition(
        canonical="NITRATE_SENSOR",
        display_name="Nitrate sensor (SUNA / ISUS)",
        description="UV spectrophotometer measuring nitrate concentration.",
        tokens=("NITRATE", "SUNA", "ISUS", "ISUS_NITRATE"),
        variables=("NITRATE",),
    ),
    "PH_SENSOR": SensorDefinition(
        canonical="PH_SENSOR",
        display_name="pH sensor (SBE)",
        description="Ion-selective field-effect pH sensor reporting in-situ pH on the total scale.",
        tokens=("PH", "SBE_PH"),
        variables=("PH_IN_SITU_TOTAL",),
    ),
    "PAR_RADIOMETER": SensorDefinition(
        canonical="PAR_RADIOMETER",
        display_name="PAR radiometer (OCR)",
        description="Radiometer measuring downwelling photosynthetically active radiation.",
        tokens=("PAR", "RADIOMETER", "OCR"),
        variables=("DOWNWELLING_PAR",),
    ),
}


#: Variable tokens whose presence marks a float/profile as BGC. Used by the
#: marker-network derivation in the query-engine helpers/trajectory/response
#: builder (the three copies were byte-identical before consolidation).
BGC_VARIABLE_MARKER_TOKENS: tuple[str, ...] = (
    "DOXY", "CHLA", "NITRATE", "BBP", "PH_IN_SITU", "DOWNWELLING", "DOWN_IRR",
)


def sensor_keywords_map() -> dict[str, list[str]]:
    """Return ``{canonical_variable: [sensor tokens]}`` (variable → sensors).

    Derived from :data:`floatchat.ontology.variables.VARIABLES`; identical to
    the legacy ``_VAR_SENSOR_MAP`` inside
    ``query_engine.helpers._filter_floats_by_variable``.
    """
    return {
        name: list(definition.sensor_keywords)
        for name, definition in VARIABLES.items()
        if definition.sensor_keywords
    }


# --------------------------------------------------------------------------- #
# Profiler platform models (WMO profiler-type codes)
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class PlatformModel:
    """Float platform model for a WMO profiler-type code."""

    code: str
    """WMO profiler-type code (e.g. ``"836"``), as stored in metadata."""
    platform_type: str
    """Platform model name (e.g. ``PROVOR CTS4``)."""
    manufacturer: str
    """Manufacturer display name including country (e.g. ``Teledyne Webb (USA)``)."""
    shortlist: bool = False
    """True when the code belonged to the legacy 10-code display shortlist
    (``PROFILER_MAP``) used by metadata-lookup display paths."""


_PLATFORM_ROWS: tuple[tuple[str, str, str, bool], ...] = (
    # code, platform_type, manufacturer, shortlist
    ("831", "APEX", "Teledyne Webb (USA)", True),
    ("832", "APEX", "Teledyne Webb (USA)", True),
    ("833", "APEX", "Teledyne Webb (USA)", False),
    ("834", "APEX", "Teledyne Webb (USA)", False),
    ("835", "APEX", "Teledyne Webb (USA)", False),
    ("836", "PROVOR CTS4", "Teledyne CARAIBE (France)", True),
    ("837", "PROVOR CTS5", "Teledyne CARAIBE (France)", True),
    ("838", "PROVOR", "Teledyne CARAIBE (France)", False),
    ("839", "PROVOR", "Teledyne CARAIBE (France)", False),
    ("840", "PROVOR", "Teledyne CARAIBE (France)", False),
    ("841", "PROVOR", "Teledyne CARAIBE (France)", True),
    ("842", "PROVOR", "Teledyne CARAIBE (France)", True),
    ("843", "PROVOR", "Teledyne CARAIBE (France)", False),
    ("844", "PROVOR", "Teledyne CARAIBE (France)", False),
    ("845", "NAVIS", "Teledyne Webb (USA)", True),
    ("846", "NINJA", "Tsurumi Seiki (Japan)", False),
    ("847", "NINJA", "Tsurumi Seiki (Japan)", False),
    ("848", "NEMO", "Nortek (Norway)", False),
    ("849", "NEMO", "Nortek (Norway)", False),
    ("850", "SOLO", "Scripps/Floats Inc. (USA)", False),
    ("851", "SOLO", "Scripps/Floats Inc. (USA)", True),
    ("852", "SOLO", "Scripps/Floats Inc. (USA)", False),
    ("853", "SOLO", "Scripps/Floats Inc. (USA)", False),
    ("854", "SOLO", "Scripps/Floats Inc. (USA)", False),
    ("860", "ARVOR", "Teledyne CARAIBE (France)", False),
    ("861", "ARVOR", "Teledyne CARAIBE (France)", True),
    ("862", "ARVOR", "Teledyne CARAIBE (France)", True),
    ("863", "ARVOR", "Teledyne CARAIBE (France)", False),
    ("864", "ARVOR", "Teledyne CARAIBE (France)", False),
)

PLATFORM_MODELS: dict[str, PlatformModel] = {
    code: PlatformModel(code=code, platform_type=platform, manufacturer=manufacturer, shortlist=shortlist)
    for code, platform, manufacturer, shortlist in _PLATFORM_ROWS
}


def platform_lookup() -> dict[str, tuple[str, str]]:
    """Return ``{code: (platform_type, manufacturer)}`` — the full 29-code GDAC
    reference table (former ``DuckDBDataLake._PROFILER_MANUFACTURER_MAP``)."""
    return {
        code: (model.platform_type, model.manufacturer)
        for code, model in PLATFORM_MODELS.items()
    }


def platform_shortlist() -> dict[str, str]:
    """Return ``{code: platform_type}`` restricted to the legacy 10-code
    display shortlist (former inline ``PROFILER_MAP`` copies)."""
    return {
        code: model.platform_type
        for code, model in PLATFORM_MODELS.items()
        if model.shortlist
    }


_COUNTRY_SUFFIX_RE = re.compile(r"\s+\([^)]*\)$")


def manufacturer_short_lookup() -> dict[str, str]:
    """Return ``{code: manufacturer}`` with the country suffix stripped —
    identical to the legacy ``query_engine.helpers._PROFILER_MFR_MAP``
    (``"Teledyne Webb (USA)"`` → ``"Teledyne Webb"``)."""
    return {
        code: _COUNTRY_SUFFIX_RE.sub("", model.manufacturer)
        for code, model in PLATFORM_MODELS.items()
    }


# --------------------------------------------------------------------------- #
# Data Assembly Centre (DAC) vocabulary (former duplicated DAC_MAP copies)
# --------------------------------------------------------------------------- #

DAC_NAMES: dict[str, str] = {
    "IF": "IFREMER (Coriolis)",
    "IN": "INCOIS (India)",
    "AO": "AOML (NOAA)",
    "JM": "JMA (Japan)",
    "CS": "CSIRO (Australia)",
    "KM": "KORDI / KMA (Korea)",
    "BO": "BODC (UK)",
    "HZ": "CSIO (China)",
}
