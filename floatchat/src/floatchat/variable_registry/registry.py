"""Centralized Variable Registry for FloatChat Phase 22.

Updated per INCOIS scientific guidance:
- Core variables → Core index
- BGC variables → Bio index
- Mixed queries → both indexes
- Synthetic is now optional fallback only
"""

from dataclasses import dataclass, field
from typing import List, Literal, Optional, Set


@dataclass(frozen=True)
class VariableDefinition:
    """Complete scientific definition of an Argo variable."""

    canonical: str
    category: Literal["core", "bgc_primary", "intermediate"]
    description: str
    units: str
    aliases: List[str] = field(default_factory=list)
    abbreviations: List[str] = field(default_factory=list)
    preferred_metadata_index: Literal["core", "bio", "synthetic"] = "core"
    preferred_profile_type: Literal["R", "B", "S"] = "R"
    adjusted_name: Optional[str] = None
    qc_name: Optional[str] = None
    error_name: Optional[str] = None
    is_intermediate: bool = False


class VariableRegistry:
    """Single source of truth for all supported Argo variables."""

    _REGISTRY: dict[str, VariableDefinition] = {
        # Core variables
        "TEMP": VariableDefinition(
            canonical="TEMP",
            category="core",
            description="Sea water temperature (ITS-90)",
            units="degree_Celsius",
            aliases=["temperature", "temp"],
            abbreviations=["temp"],
            preferred_metadata_index="core",
            preferred_profile_type="R",
            adjusted_name="TEMP_ADJUSTED",
            qc_name="TEMP_QC",
            error_name="TEMP_ADJUSTED_ERROR",
        ),
        "PSAL": VariableDefinition(
            canonical="PSAL",
            category="core",
            description="Practical salinity",
            units="psu",
            aliases=["salinity", "psal"],
            abbreviations=["psal"],
            preferred_metadata_index="core",
            preferred_profile_type="R",
            adjusted_name="PSAL_ADJUSTED",
            qc_name="PSAL_QC",
            error_name="PSAL_ADJUSTED_ERROR",
        ),
        "PRES": VariableDefinition(
            canonical="PRES",
            category="core",
            description="Sea water pressure",
            units="dbar",
            aliases=["pressure", "pres"],
            abbreviations=["pres"],
            preferred_metadata_index="core",
            preferred_profile_type="R",
            adjusted_name="PRES_ADJUSTED",
            qc_name="PRES_QC",
            error_name="PRES_ADJUSTED_ERROR",
        ),
        # BGC Primary variables
        "DOXY": VariableDefinition(
            canonical="DOXY",
            category="bgc_primary",
            description="Dissolved oxygen concentration",
            units="umol/kg",
            aliases=["oxygen", "dissolved oxygen", "doxy", "o2"],
            abbreviations=["dox", "o2"],
            preferred_metadata_index="bio",
            preferred_profile_type="B",
            adjusted_name="DOXY_ADJUSTED",
            qc_name="DOXY_QC",
            error_name="DOXY_ADJUSTED_ERROR",
        ),
        "CHLA": VariableDefinition(
            canonical="CHLA",
            category="bgc_primary",
            description="Chlorophyll-a concentration",
            units="mg/m^3",
            aliases=["chlorophyll", "chlorophyll-a", "chla"],
            abbreviations=["chl"],
            preferred_metadata_index="bio",
            preferred_profile_type="B",
            adjusted_name="CHLA_ADJUSTED",
            qc_name="CHLA_QC",
            error_name="CHLA_ADJUSTED_ERROR",
        ),
        "BBP700": VariableDefinition(
            canonical="BBP700",
            category="bgc_primary",
            description="Particle backscattering at 700nm",
            units="m^-1",
            aliases=["backscatter", "bbp700"],
            preferred_metadata_index="bio",
            preferred_profile_type="B",
            adjusted_name="BBP700_ADJUSTED",
            qc_name="BBP700_QC",
            error_name="BBP700_ADJUSTED_ERROR",
        ),
        "NITRATE": VariableDefinition(
            canonical="NITRATE",
            category="bgc_primary",
            description="Nitrate concentration",
            units="umol/kg",
            aliases=["nitrate", "no3"],
            preferred_metadata_index="bio",
            preferred_profile_type="B",
            adjusted_name="NITRATE_ADJUSTED",
            qc_name="NITRATE_QC",
            error_name="NITRATE_ADJUSTED_ERROR",
        ),
        "PH_IN_SITU_TOTAL": VariableDefinition(
            canonical="PH_IN_SITU_TOTAL",
            category="bgc_primary",
            description="pH (total scale)",
            units="dimensionless",
            aliases=["ph", "ph in situ total"],
            preferred_metadata_index="bio",
            preferred_profile_type="B",
            adjusted_name="PH_IN_SITU_TOTAL_ADJUSTED",
            qc_name="PH_IN_SITU_TOTAL_QC",
            error_name="PH_IN_SITU_TOTAL_ADJUSTED_ERROR",
        ),
        # Intermediate variables
        "TEMP_DOXY": VariableDefinition(
            canonical="TEMP_DOXY",
            category="intermediate",
            description="Optode thermistor temperature (diagnostic)",
            units="degree_Celsius",
            is_intermediate=True,
            preferred_metadata_index="bio",
            preferred_profile_type="B",
        ),
    }

    @classmethod
    def get(cls, name: str) -> Optional[VariableDefinition]:
        name = name.upper()
        if name in cls._REGISTRY:
            return cls._REGISTRY[name]
        for var in cls._REGISTRY.values():
            if name in [a.upper() for a in var.aliases + var.abbreviations]:
                return var
        return None

    @classmethod
    def classify_variables(cls, variables: List[str]) -> dict:
        core_vars = []
        bgc_vars = []
        intermediates = []

        for v in variables:
            definition = cls.get(v)
            if not definition:
                continue
            if definition.category == "core":
                core_vars.append(definition.canonical)
            elif definition.category == "bgc_primary":
                bgc_vars.append(definition.canonical)
            elif definition.is_intermediate:
                intermediates.append(definition.canonical)

        if core_vars and bgc_vars:
            strategy = "both"
            metadata_index = "both"
            profile_type = "both"
        elif core_vars:
            strategy = "core"
            metadata_index = "core"
            profile_type = "R"
        else:
            strategy = "bio"
            metadata_index = "bio"
            profile_type = "B"

        return {
            "core": core_vars,
            "bgc": bgc_vars,
            "intermediates": intermediates,
            "strategy": strategy,
            "metadata_index": metadata_index,
            "profile_type": profile_type,
        }

    @classmethod
    def get_preferred_index(cls, variables: List[str]) -> str:
        classification = cls.classify_variables(variables)
        return classification["metadata_index"]

    @classmethod
    def is_valid_variable(cls, name: str) -> bool:
        return cls.get(name) is not None

    @classmethod
    def get_all_canonical_names(cls) -> Set[str]:
        return set(cls._REGISTRY.keys())