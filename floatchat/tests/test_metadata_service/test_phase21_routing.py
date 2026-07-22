"""Phase 22 regression tests for Variable Registry + Retrieval Planner.

Updated to reflect the official INCOIS scientific requirement:
- Core variables → Core index
- BGC variables → Bio index
- Mixed queries → Both indexes
"""

import pytest

from floatchat.variable_registry.registry import VariableRegistry
from floatchat.retrieval_planner.planner import RetrievalPlanner


def test_variable_registry_classifies_temp_as_core():
    classification = VariableRegistry.classify_variables(["TEMP"])
    assert classification["metadata_index"] == "core"
    assert classification["profile_type"] == "R"


def test_variable_registry_classifies_psal_as_core():
    classification = VariableRegistry.classify_variables(["PSAL"])
    assert classification["metadata_index"] == "core"
    assert classification["profile_type"] == "R"


def test_variable_registry_classifies_doxy_as_bgc():
    classification = VariableRegistry.classify_variables(["DOXY"])
    assert classification["metadata_index"] == "bio"
    assert classification["profile_type"] == "B"


def test_variable_registry_classifies_chla_as_bgc():
    classification = VariableRegistry.classify_variables(["CHLA"])
    assert classification["metadata_index"] == "bio"
    assert classification["profile_type"] == "B"


def test_variable_registry_mixed_core_bgc_routes_to_both():
    classification = VariableRegistry.classify_variables(["TEMP", "DOXY"])
    assert classification["metadata_index"] == "both"


def test_retrieval_planner_produces_reasoning():
    planner = RetrievalPlanner()
    plan = planner.plan(["TEMP"])
    assert "core" in plan.reasoning.lower()