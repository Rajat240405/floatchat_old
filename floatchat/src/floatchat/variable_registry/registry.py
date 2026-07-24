"""Centralized Variable Registry for FloatChat.

This registry is the application-facing vocabulary for variables present in the
Phase 2 data lake.  Adjusted variables are represented as a preferred storage
variant of their canonical variable: query execution automatically prefers the
adjusted column when it contains valid data.
"""

from dataclasses import dataclass, field
from typing import List, Literal, Optional, Set


@dataclass(frozen=True)
class VariableDefinition:
    """Scientific and presentation metadata for one canonical variable."""

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


class VariableRegistry:
    """Single source of truth for supported application variables."""

    _REGISTRY: dict[str, VariableDefinition] = {
        "PRES": VariableDefinition(
            "PRES", "core", "Sea water pressure", "dbar", "Pressure (dbar)",
            ["pressure", "depth", "pres"], ["p"], "core", "R",
            "PRES_ADJUSTED", "PRES_QC", "PRES_ADJUSTED_ERROR",
        ),
        "TEMP": VariableDefinition(
            "TEMP", "core", "Sea water temperature (ITS-90)", "°C", "Temperature (°C)",
            ["temperature", "temp", "water temperature", "water temp", "sea temperature"],
            ["sst"], "core", "R", "TEMP_ADJUSTED", "TEMP_QC", "TEMP_ADJUSTED_ERROR",
        ),
        "PSAL": VariableDefinition(
            "PSAL", "core", "Practical salinity", "PSU", "Practical Salinity (PSU)",
            ["salinity", "psal", "salt", "water salinity"], [], "core", "R",
            "PSAL_ADJUSTED", "PSAL_QC", "PSAL_ADJUSTED_ERROR",
        ),
        "DOXY": VariableDefinition(
            "DOXY", "bgc_primary", "Dissolved oxygen concentration", "µmol/kg", "Dissolved Oxygen (µmol kg⁻¹)",
            ["oxygen", "dissolved oxygen", "doxy", "dissolved o2", "oxygen concentration"],
            ["o2", "dox"], "bio", "B", "DOXY_ADJUSTED", "DOXY_QC", "DOXY_ADJUSTED_ERROR",
        ),
        "CHLA": VariableDefinition(
            "CHLA", "bgc_primary", "Chlorophyll-a concentration", "mg/m³", "Chlorophyll-a (mg m⁻³)",
            ["chlorophyll", "chlorophyll-a", "chlorophyll a", "chla", "phytoplankton"],
            ["chl", "chl-a"], "bio", "B", "CHLA_ADJUSTED", "CHLA_QC", "CHLA_ADJUSTED_ERROR",
        ),
        "BBP700": VariableDefinition(
            "BBP700", "bgc_primary", "Particle backscattering at 700 nm", "m⁻¹", "Particle Backscattering 700 nm (m⁻¹)",
            ["backscatter", "backscattering", "particle backscatter", "particle backscattering", "particulate backscatter", "bbp700"],
            ["bbp"], "bio", "B", "BBP700_ADJUSTED", "BBP700_QC", "BBP700_ADJUSTED_ERROR",
        ),
        "NITRATE": VariableDefinition(
            "NITRATE", "bgc_primary", "Nitrate concentration", "µmol/kg", "Nitrate (µmol kg⁻¹)",
            ["nitrate", "nitrate concentration", "no3", "nitrogen"], [], "bio", "B",
            "NITRATE_ADJUSTED", "NITRATE_QC", "NITRATE_ADJUSTED_ERROR",
        ),
        "PH_IN_SITU_TOTAL": VariableDefinition(
            "PH_IN_SITU_TOTAL", "bgc_primary", "In-situ pH on the total scale", "total scale", "In-situ pH (total scale)",
            ["ph", "pH", "ph level", "acidity", "in situ ph", "ph in situ total"], [], "bio", "B",
            "PH_IN_SITU_TOTAL_ADJUSTED", "PH_IN_SITU_TOTAL_QC", "PH_IN_SITU_TOTAL_ADJUSTED_ERROR",
        ),
        "DOWNWELLING_PAR": VariableDefinition(
            "DOWNWELLING_PAR", "bgc_primary", "Downwelling photosynthetically active radiation", "µmol photons m⁻² s⁻¹", "Downwelling PAR (µmol photons m⁻² s⁻¹)",
            ["par", "downwelling par", "photosynthetically active radiation", "photosynthetic radiation", "underwater sunlight"], [], "bio", "B",
            "DOWNWELLING_PAR_ADJUSTED", "DOWNWELLING_PAR_QC", "DOWNWELLING_PAR_ADJUSTED_ERROR",
        ),
        "TEMP_DOXY": VariableDefinition(
            "TEMP_DOXY", "intermediate", "Optode thermistor temperature (diagnostic)", "°C", "Optode Temperature (°C)",
            ["optode temperature"], [], "bio", "B", is_intermediate=True,
        ),
    }

    @classmethod
    def get(cls, name: str | None) -> Optional[VariableDefinition]:
        if not name:
            return None
        normalized = str(name).strip().upper()
        if normalized.endswith("_ADJUSTED"):
            normalized = normalized.removesuffix("_ADJUSTED")
        if normalized in cls._REGISTRY:
            return cls._REGISTRY[normalized]
        for definition in cls._REGISTRY.values():
            if normalized in {a.upper() for a in definition.aliases + definition.abbreviations}:
                return definition
        return None

    @classmethod
    def normalize(cls, name: str) -> str:
        """Return the canonical query name; adjusted requests map to their base."""
        definition = cls.get(name)
        return definition.canonical if definition else str(name).strip().upper()

    @classmethod
    def classify_variables(cls, variables: List[str]) -> dict:
        core_vars: list[str] = []
        bgc_vars: list[str] = []
        intermediates: list[str] = []
        for value in variables:
            definition = cls.get(value)
            if not definition:
                continue
            if definition.category == "core":
                core_vars.append(definition.canonical)
            elif definition.category == "bgc_primary":
                bgc_vars.append(definition.canonical)
            elif definition.is_intermediate:
                intermediates.append(definition.canonical)
        if core_vars and bgc_vars:
            strategy, index, profile = "both", "both", "both"
        elif core_vars:
            strategy, index, profile = "core", "core", "R"
        else:
            strategy, index, profile = "bio", "bio", "B"
        return {"core": core_vars, "bgc": bgc_vars, "intermediates": intermediates,
                "strategy": strategy, "metadata_index": index, "profile_type": profile}

    @classmethod
    def get_preferred_index(cls, variables: List[str]) -> str:
        return cls.classify_variables(variables)["metadata_index"]

    @classmethod
    def is_valid_variable(cls, name: str) -> bool:
        return cls.get(name) is not None

    @classmethod
    def get_all_canonical_names(cls) -> Set[str]:
        return set(cls._REGISTRY.keys())

    @classmethod
    def get_all_query_names(cls) -> Set[str]:
        return {d.canonical for d in cls._REGISTRY.values() if not d.is_intermediate}
