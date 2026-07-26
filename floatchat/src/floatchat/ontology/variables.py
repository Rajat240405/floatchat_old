"""Canonical Argo variable vocabulary (Domain Ontology, Phase 1).

Single source of truth for everything the application knows about Argo
variables. The contents of this module were relocated *verbatim* from their
previous fragmented homes (behaviour-neutral move):

============================  ==================================================
Ontology field / constant     Previous home(s)
============================  ==================================================
``VariableDefinition`` core   ``variable_registry.registry.VariableRegistry``
fields (canonical … is_       (the application variable registry)
intermediate)
``parser_synonyms``           ``intent_parser.regex._VARIABLE_SYNONYMS``
``plot_title``                ``visualization_engine.profile._VAR_TITLES``
``card_title``                ``api.services.floats_service._VAR_TITLES``
``prompt_units``              ``scientific_explanation.features._UNITS``
``sensor_keywords``           ``query_engine.helpers._filter_floats_by_variable``
                              ``._VAR_SENSOR_MAP``
``PARSER_VARIABLE_ORDER``     ``intent_parser.fuzzy._VARIABLE_CANONICAL``
``LEVELS_VARIABLE_ORDER``     ``query_engine.executors.profile`` column-alias
                              map order, ``visualization_engine.profile``
                              fallback candidate lists and comparison priority,
                              ``intent_parser.regex`` comparison defaults
``CATALOGUE_VARIABLE_ORDER``  ``api.services.floats_service._CORE_PLOT_VARS``
``TYPO_CORRECTIONS``          ``intent_parser.fuzzy._TYPO_MAP``
``NORMALIZER_CANONICAL_TERMS``    ``query_normalizer.fallback._CANONICAL_TERMS``
``NORMALIZER_ABBREVIATIONS``      ``query_normalizer.fallback._ABBREV_MAP``
============================  ==================================================

Two presentation surfaces intentionally remain distinct (they contained
*different* strings before this refactor and unifying them would change
user-visible output):

* ``display_label`` / ``units`` — registry presentation + plot titles
  (``plot_title``), and
* ``prompt_units`` — the unit strings fed to the scientific-explanation
  prompt/feature pipeline (e.g. ``m^-1`` vs ``m⁻¹``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Optional, Tuple


@dataclass(frozen=True)
class VariableDefinition:
    """Scientific and presentation metadata for one canonical variable.

    The first twelve fields are the pre-ontology registry contract (kept in
    the same positional order for backward compatibility). The remaining
    fields were consolidated from consumer-local copies during Phase 1.
    """

    canonical: str
    category: Literal["core", "bgc_primary", "intermediate"]
    description: str
    units: str
    display_label: str
    aliases: List[str] = field(default_factory=list)
    abbreviations: List[str] = field(default_factory=list)
    preferred_metadata_index: Literal["core", "bio", "synthetic"] = "core"
    preferred_profile_type: Literal["R", "B", "S"] = "R"
    adjusted_name: Optional[str] = None
    qc_name: Optional[str] = None
    error_name: Optional[str] = None
    is_intermediate: bool = False
    # --- Phase 1 consolidation fields (verbatim relocations) --------------- #
    #: Natural-language synonyms used by the deterministic regex parser
    #: (formerly ``intent_parser.regex._VARIABLE_SYNONYMS``).
    parser_synonyms: Tuple[str, ...] = ()
    #: Subplot/axis title used by the visualization engine.
    plot_title: Optional[str] = None
    #: Short title used by the deterministic floats API (plot catalogue).
    card_title: Optional[str] = None
    #: Unit spelling used by the scientific-explanation feature pipeline.
    prompt_units: Optional[str] = None
    #: Sensor-name tokens that imply this variable (registry ``sensors`` column).
    sensor_keywords: Tuple[str, ...] = ()
    #: Whether the variable is part of the application variable registry
    #: (``VariableRegistry``). Known-but-not-queryable variables (e.g. the
    #: downwelling irradiances) are registered=False.
    registered: bool = True
    #: Whether the levels parquet stores a {raw, qc, adjusted} column triple
    #: for this variable (lowercased canonical name + suffixes).
    stored_in_levels: bool = False


# --------------------------------------------------------------------------- #
# Canonical variables. Insertion order preserves the legacy registry order for
# registered variables (PRES … TEMP_DOXY) so derived dicts keep their previous
# iteration order; unregistered variables follow.
# --------------------------------------------------------------------------- #

VARIABLES: dict[str, VariableDefinition] = {
    "PRES": VariableDefinition(
        "PRES", "core", "Sea water pressure", "dbar", "Pressure (dbar)",
        ["pressure", "depth", "pres"], ["p"], "core", "R",
        "PRES_ADJUSTED", "PRES_QC", "PRES_ADJUSTED_ERROR",
        card_title="Pressure",
    ),
    "TEMP": VariableDefinition(
        "TEMP", "core", "Sea water temperature (ITS-90)", "°C", "Temperature (°C)",
        ["temperature", "temp", "water temperature", "water temp", "sea temperature"],
        ["sst"], "core", "R", "TEMP_ADJUSTED", "TEMP_QC", "TEMP_ADJUSTED_ERROR",
        parser_synonyms=("temperature", "temp", "sst", "water temp"),
        plot_title="Temperature (°C)",
        card_title="Temperature",
        prompt_units="°C",
        sensor_keywords=("CTD", "TEMP", "SST"),
        stored_in_levels=True,
    ),
    "PSAL": VariableDefinition(
        "PSAL", "core", "Practical salinity", "PSU", "Practical Salinity (PSU)",
        ["salinity", "psal", "salt", "water salinity"], [], "core", "R",
        "PSAL_ADJUSTED", "PSAL_QC", "PSAL_ADJUSTED_ERROR",
        parser_synonyms=("salinity", "psal", "salt"),
        plot_title="Practical Salinity",
        card_title="Salinity",
        prompt_units="PSU",
        sensor_keywords=("CTD", "PSAL", "SALINITY"),
        stored_in_levels=True,
    ),
    "DOXY": VariableDefinition(
        "DOXY", "bgc_primary", "Dissolved oxygen concentration", "µmol/kg", "Dissolved Oxygen (µmol kg⁻¹)",
        ["oxygen", "dissolved oxygen", "doxy", "dissolved o2", "oxygen concentration"],
        ["o2", "dox"], "bio", "B", "DOXY_ADJUSTED", "DOXY_QC", "DOXY_ADJUSTED_ERROR",
        parser_synonyms=("oxygen", "dissolved oxygen", "doxy", "o2", "dox", "oxy", "dissolved o2"),
        plot_title="Dissolved Oxygen (µmol kg⁻¹)",
        card_title="Oxygen",
        prompt_units="µmol/kg",
        sensor_keywords=("OPTODE", "DOXY", "OXYGEN", "AANDERAA"),
        stored_in_levels=True,
    ),
    "CHLA": VariableDefinition(
        "CHLA", "bgc_primary", "Chlorophyll-a concentration", "mg/m³", "Chlorophyll-a (mg m⁻³)",
        ["chlorophyll", "chlorophyll-a", "chlorophyll a", "chla", "phytoplankton"],
        ["chl", "chl-a"], "bio", "B", "CHLA_ADJUSTED", "CHLA_QC", "CHLA_ADJUSTED_ERROR",
        parser_synonyms=("chlorophyll", "chlorophyll-a", "chla", "chlorophyll a", "chl", "chl-a", "phytoplankton"),
        plot_title="Chlorophyll-A (mg m⁻³)",
        card_title="Chlorophyll",
        prompt_units="mg/m³",
        sensor_keywords=("FLUOROMETER", "CHLA", "CHLOROPHYLL", "ECO"),
        stored_in_levels=True,
    ),
    "BBP700": VariableDefinition(
        "BBP700", "bgc_primary", "Particle backscattering at 700 nm", "m⁻¹", "Particle Backscattering 700 nm (m⁻¹)",
        ["backscatter", "backscattering", "particle backscatter", "particle backscattering", "particulate backscatter", "bbp700"],
        ["bbp"], "bio", "B", "BBP700_ADJUSTED", "BBP700_QC", "BBP700_ADJUSTED_ERROR",
        parser_synonyms=("backscattering", "bbp700", "particle backscattering", "backscatter", "bbp", "particulate backscatter"),
        plot_title="Particle Backscattering 700 nm (m⁻¹)",
        card_title="Particle Backscattering 700 nm (m⁻¹)",
        prompt_units="m^-1",
        sensor_keywords=("BACKSCATTER", "BBP", "ECO", "FLBBCD"),
        stored_in_levels=True,
    ),
    "NITRATE": VariableDefinition(
        "NITRATE", "bgc_primary", "Nitrate concentration", "µmol/kg", "Nitrate (µmol kg⁻¹)",
        ["nitrate", "nitrate concentration", "no3", "nitrogen"], [], "bio", "B",
        "NITRATE_ADJUSTED", "NITRATE_QC", "NITRATE_ADJUSTED_ERROR",
        parser_synonyms=("nitrate", "no3", "nitrogen"),
        plot_title="Nitrate (µmol kg⁻¹)",
        card_title="Nitrate (µmol kg⁻¹)",
        prompt_units="µmol/kg",
        sensor_keywords=("NITRATE", "SUNA", "ISUS", "ISUS_NITRATE"),
        stored_in_levels=True,
    ),
    "PH_IN_SITU_TOTAL": VariableDefinition(
        "PH_IN_SITU_TOTAL", "bgc_primary", "In-situ pH on the total scale", "total scale", "In-situ pH (total scale)",
        ["ph", "pH", "ph level", "acidity", "in situ ph", "ph in situ total"], [], "bio", "B",
        "PH_IN_SITU_TOTAL_ADJUSTED", "PH_IN_SITU_TOTAL_QC", "PH_IN_SITU_TOTAL_ADJUSTED_ERROR",
        parser_synonyms=("ph", "acidity", "ph in situ total", "ph level"),
        plot_title="pH (total scale)",
        card_title="In-situ pH (total scale)",
        prompt_units="total scale",
        sensor_keywords=("PH", "SBE_PH"),
        stored_in_levels=True,
    ),
    "DOWNWELLING_PAR": VariableDefinition(
        "DOWNWELLING_PAR", "bgc_primary", "Downwelling photosynthetically active radiation", "µmol photons m⁻² s⁻¹", "Downwelling PAR (µmol photons m⁻² s⁻¹)",
        ["par", "downwelling par", "photosynthetically active radiation", "photosynthetic radiation", "underwater sunlight"], [], "bio", "B",
        "DOWNWELLING_PAR_ADJUSTED", "DOWNWELLING_PAR_QC", "DOWNWELLING_PAR_ADJUSTED_ERROR",
        parser_synonyms=("par", "photosynthetically active radiation", "downwelling par", "sunlight"),
        plot_title="Downwelling PAR (µmol photons m⁻² s⁻¹)",
        card_title="Downwelling PAR (µmol photons m⁻² s⁻¹)",
        prompt_units="µmol quanta/m²/s",
        sensor_keywords=("PAR", "RADIOMETER", "OCR"),
        stored_in_levels=True,
    ),
    # --- Known but not queryable through the application registry ---------- #
    # The downwelling irradiances are recognized by the deterministic parser,
    # fuzzy matcher and visualization engine but are NOT part of the
    # application variable registry (registered=False preserves the legacy
    # behaviour of VariableRegistry.is_valid_variable / get_all_query_names).
    "DOWN_IRRADIANCE380": VariableDefinition(
        "DOWN_IRRADIANCE380", "bgc_primary", "Downwelling irradiance at 380 nm", "W m⁻² nm⁻¹", "Downwelling Irradiance 380 nm",
        [], [], "bio", "B",
        "DOWN_IRRADIANCE380_ADJUSTED", "DOWN_IRRADIANCE380_QC", "DOWN_IRRADIANCE380_ADJUSTED_ERROR",
        parser_synonyms=("irradiance 380", "down irradiance 380", "ir380"),
        plot_title="Irradiance 380 nm",
        registered=False,
    ),
    "DOWN_IRRADIANCE412": VariableDefinition(
        "DOWN_IRRADIANCE412", "bgc_primary", "Downwelling irradiance at 412 nm", "W m⁻² nm⁻¹", "Downwelling Irradiance 412 nm",
        [], [], "bio", "B",
        "DOWN_IRRADIANCE412_ADJUSTED", "DOWN_IRRADIANCE412_QC", "DOWN_IRRADIANCE412_ADJUSTED_ERROR",
        parser_synonyms=("irradiance 412", "down irradiance 412", "ir412"),
        plot_title="Irradiance 412 nm",
        registered=False,
    ),
    "DOWN_IRRADIANCE490": VariableDefinition(
        "DOWN_IRRADIANCE490", "bgc_primary", "Downwelling irradiance at 490 nm", "W m⁻² nm⁻¹", "Downwelling Irradiance 490 nm",
        [], [], "bio", "B",
        "DOWN_IRRADIANCE490_ADJUSTED", "DOWN_IRRADIANCE490_QC", "DOWN_IRRADIANCE490_ADJUSTED_ERROR",
        parser_synonyms=("irradiance 490", "down irradiance 490", "ir490"),
        plot_title="Irradiance 490 nm",
        registered=False,
    ),
    "TEMP_DOXY": VariableDefinition(
        "TEMP_DOXY", "intermediate", "Optode thermistor temperature (diagnostic)", "°C", "Optode Temperature (°C)",
        ["optode temperature"], [], "bio", "B", is_intermediate=True,
    ),
}


# --------------------------------------------------------------------------- #
# Ordered variable tuples (order is behavioural — preserved verbatim).
# --------------------------------------------------------------------------- #

#: Canonical variables known to the fuzzy/typo matcher, in the legacy match
#: order (difflib tie-breaking makes this order observable). Formerly
#: ``intent_parser.fuzzy._VARIABLE_CANONICAL``.
PARSER_VARIABLE_ORDER: tuple[str, ...] = (
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
)

#: Depth-level variables stored in the lake, in profile pipeline order. Used
#: by the executor column-alias map, the visualization fallback candidates and
#: comparison priority, and the parser's comparison defaults.
LEVELS_VARIABLE_ORDER: tuple[str, ...] = (
    "TEMP",
    "PSAL",
    "DOXY",
    "CHLA",
    "BBP700",
    "NITRATE",
    "PH_IN_SITU_TOTAL",
    "DOWNWELLING_PAR",
)

#: Plot catalogue order used by the deterministic floats API
#: (``_CORE_PLOT_VARS``). Note: NITRATE precedes BBP700 here — the two legacy
#: orderings were genuinely different and are both preserved.
CATALOGUE_VARIABLE_ORDER: tuple[str, ...] = (
    "TEMP",
    "PSAL",
    "DOXY",
    "CHLA",
    "NITRATE",
    "BBP700",
    "PH_IN_SITU_TOTAL",
    "DOWNWELLING_PAR",
)


def levels_storage_names(canonical: str) -> tuple[str, str, str]:
    """Return the (raw, qc, adjusted) levels-parquet column names for a variable.

    The lake stores lowercased canonical names with ``_qc`` / ``_adjusted``
    suffixes (e.g. ``doxy``, ``doxy_qc``, ``doxy_adjusted``).
    """
    base = canonical.strip().lower()
    return base, f"{base}_qc", f"{base}_adjusted"


# --------------------------------------------------------------------------- #
# Typo corrections (formerly intent_parser.fuzzy._TYPO_MAP — verbatim).
# High-confidence typo corrections — always applied regardless of similarity
# score. Covers common misspellings and shorthand forms.
# --------------------------------------------------------------------------- #

TYPO_CORRECTIONS: dict[str, str] = {
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


# --------------------------------------------------------------------------- #
# Query-normalizer vocabulary (formerly query_normalizer.fallback — verbatim).
# --------------------------------------------------------------------------- #

#: High-confidence canonical targets (used by both LLM and fallback).
NORMALIZER_CANONICAL_TERMS: list[str] = [
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

#: Lightweight abbreviation expansion (deterministic).
NORMALIZER_ABBREVIATIONS: dict[str, str] = {
    "chl": "chlorophyll",
    "temp": "temperature",
    "dox": "dissolved oxygen",
    "o2": "oxygen",
    "psal": "salinity",
}
