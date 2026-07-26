"""Centralized Variable Registry for FloatChat.

This registry is the application-facing vocabulary for variables present in the
Phase 2 data lake.  Adjusted variables are represented as a preferred storage
variant of their canonical variable: query execution automatically prefers the
adjusted column when it contains valid data.

Ontology 2.0 (Phase 1): the registry *data* now lives in the domain ontology
(:mod:`floatchat.ontology.variables`) — the single source of truth for Argo
variable knowledge. This module keeps the registry API (and the
``floatchat.variable_registry`` import path) as a stable façade over the
ontology; only registered variables are exposed, exactly as before.
"""

from typing import List, Optional, Set

from floatchat.ontology.variables import (
    VARIABLES as _ONTOLOGY_VARIABLES,
    VariableDefinition,
)

__all__ = ["VariableDefinition", "VariableRegistry"]


class VariableRegistry:
    """Single source of truth for supported application variables."""

    # Registered (application-queryable) subset of the ontology. Membership is
    # identical to the pre-ontology hand-maintained table (verified by
    # tests/test_ontology).
    _REGISTRY: dict[str, VariableDefinition] = {
        name: definition
        for name, definition in _ONTOLOGY_VARIABLES.items()
        if definition.registered
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
