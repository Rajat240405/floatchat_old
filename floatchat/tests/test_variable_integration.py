"""Coverage for the application-facing Variable Integration milestone."""

import pandas as pd
import pytest

from floatchat.models import ParsedIntent
from floatchat.variable_registry import VariableRegistry
from floatchat.visualization_engine.profile import ProfileVisualizationEngine


SUPPORTED = [
    "PRES", "TEMP", "PSAL", "DOXY", "CHLA", "BBP700", "NITRATE",
    "PH_IN_SITU_TOTAL", "DOWNWELLING_PAR",
]


def test_registry_contains_all_phase2_query_variables():
    assert VariableRegistry.get_all_query_names() == set(SUPPORTED)
    for name in SUPPORTED:
        definition = VariableRegistry.get(name)
        assert definition is not None
        assert definition.display_label
        assert definition.units


def test_registry_resolves_aliases_and_adjusted_names_to_canonical_variables():
    assert VariableRegistry.normalize("dissolved oxygen") == "DOXY"
    assert VariableRegistry.normalize("photosynthetically active radiation") == "DOWNWELLING_PAR"
    assert VariableRegistry.normalize("DOXY_ADJUSTED") == "DOXY"
    assert VariableRegistry.normalize("PH_IN_SITU_TOTAL_ADJUSTED") == "PH_IN_SITU_TOTAL"


def test_parsed_intent_canonicalizes_adjusted_variable_requests():
    intent = ParsedIntent(
        intent="profile_plot",
        variables=["DOXY_ADJUSTED", "CHLA_ADJUSTED", "PAR"],
    )
    assert "CHLA" in intent.variables
    assert "DOWNWELLING_PAR" in intent.variables


@pytest.mark.parametrize("variable", SUPPORTED[1:])
def test_profile_plot_supports_each_scientific_variable(variable):
    values = {
        "TEMP": 20.0, "PSAL": 35.0, "DOXY": 210.0, "CHLA": 0.4,
        "BBP700": 0.001, "NITRATE": 5.0, "PH_IN_SITU_TOTAL": 8.0,
        "DOWNWELLING_PAR": 100.0,
    }
    df = pd.DataFrame({
        "float_id": ["7900000", "7900000"],
        "PRES": [5.0, 100.0],
        variable: [values[variable], values[variable] / 2],
    })
    figure = ProfileVisualizationEngine().render(
        ParsedIntent(intent="profile_plot", variables=[variable]), df
    )
    assert figure is not None
    assert figure["data"]
