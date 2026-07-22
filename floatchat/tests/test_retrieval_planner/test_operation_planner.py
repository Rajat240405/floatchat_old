"""Phase 2: Planner layer regression tests.

Validates that plan_from_intent() produces correct operations for every
intent type and entity combination. The planner is a pure function —
no side effects, no LLM, no I/O.
"""

import pytest

from floatchat.models import ParsedIntent
from floatchat.retrieval_planner.operation_planner import (
    Operation,
    Plan,
    plan_from_intent,
)


# --------------------------------------------------------------------------- #
# Basic intent → operation mapping
# --------------------------------------------------------------------------- #

class TestBasicIntentMapping:
    """Verify each legacy intent maps to the expected primary operation."""

    def test_profile_plot(self):
        pi = ParsedIntent(intent="profile_plot", variables=["TEMP"], region="arabian_sea")
        plan = plan_from_intent(pi)
        assert plan.legacy_intent == "profile_plot"
        assert plan.has("plot_profile")
        assert plan.has("filter_variable")
        assert plan.has("filter_region")
        assert plan.has("summarize")

    def test_region_search(self):
        pi = ParsedIntent(intent="region_search", variables=["DOXY"], region="bay_of_bengal")
        plan = plan_from_intent(pi)
        assert plan.has("plot_profile")
        assert plan.has("filter_variable")
        assert plan.has("filter_region")

    def test_trajectory(self):
        pi = ParsedIntent(intent="trajectory", float_id="2902403")
        plan = plan_from_intent(pi)
        assert plan.has("plot_trajectory")
        assert plan.has("filter_float")

    def test_metadata_lookup(self):
        pi = ParsedIntent(intent="metadata_lookup", float_id="2902403")
        plan = plan_from_intent(pi)
        assert plan.has("metadata_lookup")

    def test_nearest_float(self):
        pi = ParsedIntent(intent="nearest_float", lat=15.5, lon=72.3)
        plan = plan_from_intent(pi)
        assert plan.has("find_nearest")

    def test_radius_search(self):
        pi = ParsedIntent(intent="radius_search", lat=15.3, lon=73.9, radius_km=500.0)
        plan = plan_from_intent(pi)
        assert plan.has("find_floats")
        op = plan.get("find_floats")
        assert op.params["radius_km"] == 500.0

    def test_count_aggregate(self):
        pi = ParsedIntent(intent="count_aggregate", region="arabian_sea")
        plan = plan_from_intent(pi)
        assert plan.has("count_floats")
        assert plan.has("filter_region")

    def test_time_series(self):
        pi = ParsedIntent(intent="time_series", variables=["TEMP"], region="arabian_sea")
        plan = plan_from_intent(pi)
        assert plan.has("plot_timeseries")

    def test_hovmoller(self):
        pi = ParsedIntent(intent="hovmoller", variables=["TEMP"], region="arabian_sea")
        plan = plan_from_intent(pi)
        assert plan.has("plot_hovmoller")

    def test_ts_diagram(self):
        pi = ParsedIntent(intent="ts_diagram", float_id="2902403")
        plan = plan_from_intent(pi)
        assert plan.has("plot_ts_diagram")

    def test_comparison(self):
        pi = ParsedIntent(
            intent="comparison_plot",
            comparison_float_ids=["2902403", "2902174"],
        )
        plan = plan_from_intent(pi)
        assert plan.has("plot_comparison")


# --------------------------------------------------------------------------- #
# Filter operations
# --------------------------------------------------------------------------- #

class TestFilterOperations:
    """Verify that extracted entities generate the correct filter operations."""

    def test_year_filter(self):
        pi = ParsedIntent(intent="profile_plot", variables=["TEMP"], region="arabian_sea", year=2024)
        plan = plan_from_intent(pi)
        op = plan.get("filter_year")
        assert op is not None
        assert op.params["year"] == 2024

    def test_month_window_filter(self):
        pi = ParsedIntent(
            intent="profile_plot", variables=["TEMP"], region="arabian_sea",
            year=2024, month=6, month_window=[6, 7, 8, 9],
        )
        plan = plan_from_intent(pi)
        op = plan.get("filter_year")
        assert op.params["month_window"] == [6, 7, 8, 9]

    def test_depth_filter(self):
        pi = ParsedIntent(
            intent="profile_plot", variables=["DOXY"], region="bay_of_bengal",
            depth_min=1000.0,
        )
        plan = plan_from_intent(pi)
        op = plan.get("filter_depth")
        assert op is not None
        assert op.params["depth_min"] == 1000.0

    def test_alive_filter(self):
        pi = ParsedIntent(
            intent="radius_search", lat=15.3, lon=73.9, radius_km=500.0,
            operational_filter="alive",
        )
        plan = plan_from_intent(pi)
        assert plan.has("filter_active")

    def test_location_filter(self):
        pi = ParsedIntent(
            intent="radius_search", lat=15.3, lon=73.9, radius_km=300.0,
        )
        plan = plan_from_intent(pi)
        op = plan.get("filter_location")
        assert op is not None
        assert op.params["lat"] == 15.3
        assert op.params["lon"] == 73.9

    def test_no_filters_when_empty(self):
        pi = ParsedIntent(intent="profile_plot")
        plan = plan_from_intent(pi)
        assert not plan.has("filter_region")
        assert not plan.has("filter_variable")
        assert not plan.has("filter_year")
        assert not plan.has("filter_depth")
        assert not plan.has("filter_active")


# --------------------------------------------------------------------------- #
# Complex queries (matching benchmark)
# --------------------------------------------------------------------------- #

class TestComplexQueries:
    """Verify the planner produces sensible operations for benchmark queries."""

    def test_temperature_in_arabian_sea_2024(self):
        pi = ParsedIntent(
            intent="region_search", variables=["TEMP"], region="arabian_sea", year=2024,
        )
        plan = plan_from_intent(pi)
        assert plan.has("filter_region")
        assert plan.has("filter_variable")
        assert plan.has("filter_year")
        assert plan.has("plot_profile")

    def test_floats_near_goa(self):
        pi = ParsedIntent(
            intent="radius_search", lat=15.3, lon=73.9, radius_km=500.0,
        )
        plan = plan_from_intent(pi)
        assert plan.has("find_floats")
        assert plan.has("filter_location")
        assert not plan.has("plot_profile")  # discovery, not plotting

    def test_deep_oxygen_in_bob(self):
        pi = ParsedIntent(
            intent="region_search", variables=["DOXY"], region="bay_of_bengal",
            depth_min=1000.0,
        )
        plan = plan_from_intent(pi)
        assert plan.has("filter_depth")
        assert plan.has("filter_variable")

    def test_alive_floats_near_goa_monsoon(self):
        pi = ParsedIntent(
            intent="radius_search", lat=15.3, lon=73.9, radius_km=500.0,
            operational_filter="alive", year=2025, month=6, month_window=[6, 7, 8, 9],
        )
        plan = plan_from_intent(pi)
        assert plan.has("find_floats")
        assert plan.has("filter_active")
        assert plan.has("filter_year")

    def test_trajectory_of_float(self):
        pi = ParsedIntent(intent="trajectory", float_id="2902403")
        plan = plan_from_intent(pi)
        assert plan.has("plot_trajectory")
        assert plan.has("filter_float")
        # Trajectory should NOT have summarize (it's a map, not a profile)
        assert not plan.has("summarize")


# --------------------------------------------------------------------------- #
# Plan properties
# --------------------------------------------------------------------------- #

class TestPlanProperties:
    """Verify Plan data structure behaves correctly."""

    def test_has_method(self):
        plan = Plan(operations=[Operation("find_floats")])
        assert plan.has("find_floats")
        assert not plan.has("plot_profile")

    def test_get_method(self):
        op = Operation("filter_region", {"region": "arabian_sea"})
        plan = Plan(operations=[op])
        found = plan.get("filter_region")
        assert found is op
        assert plan.get("nonexistent") is None

    def test_repr(self):
        plan = plan_from_intent(ParsedIntent(
            intent="profile_plot", variables=["TEMP"], region="arabian_sea",
        ))
        s = repr(plan)
        assert "filter_region" in s
        assert "filter_variable" in s
        assert "plot_profile" in s


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# --------------------------------------------------------------------------- #
# Phase 5: Mixed query detection
# --------------------------------------------------------------------------- #

class TestMixedQueryDetection:
    """Verify the planner detects mixed knowledge+data queries."""

    def test_mixed_chlorophyll(self):
        pi = ParsedIntent(intent="profile_plot", variables=["CHLA"], region="arabian_sea")
        plan = plan_from_intent(pi, message="What is chlorophyll? Show chlorophyll profiles in Arabian Sea.")
        assert plan.is_mixed is True
        assert plan.has("explain_topic")
        assert plan.has("plot_profile")

    def test_mixed_thermocline(self):
        pi = ParsedIntent(intent="profile_plot", variables=["TEMP"], region="bay_of_bengal")
        plan = plan_from_intent(pi, message="Explain thermocline and plot temperature in Bay of Bengal.")
        assert plan.is_mixed is True
        assert plan.has("explain_topic")
        assert plan.has("plot_profile")

    def test_not_mixed_pure_data(self):
        pi = ParsedIntent(intent="region_search", variables=["TEMP"], region="arabian_sea", year=2024)
        plan = plan_from_intent(pi, message="temperature in Arabian Sea 2024")
        assert plan.is_mixed is False
        assert not plan.has("explain_topic")

    def test_not_mixed_pure_knowledge(self):
        pi = ParsedIntent(intent="knowledge_base")
        plan = plan_from_intent(pi, message="What is Argo?")
        assert plan.is_mixed is False

    def test_mixed_extracts_topic(self):
        pi = ParsedIntent(intent="profile_plot", variables=["DOXY"], region="arabian_sea")
        plan = plan_from_intent(pi, message="What is dissolved oxygen? Show oxygen in Arabian Sea.")
        assert plan.is_mixed is True
        explain = plan.get("explain_topic")
        assert explain is not None
        assert len(explain.params["topic"]) > 0

    def test_terminal_operations_property(self):
        pi = ParsedIntent(intent="profile_plot", variables=["TEMP"], region="arabian_sea")
        plan = plan_from_intent(pi, message="temperature in Arabian Sea")
        terminals = plan.terminal_operations
        assert len(terminals) >= 1
        assert all(t.name in ("plot_profile", "summarize", "explain_topic",
                              "find_floats", "metadata_lookup", "count_floats",
                              "plot_trajectory", "plot_timeseries", "plot_hovmoller",
                              "plot_ts_diagram", "plot_comparison", "find_nearest")
                      for t in terminals)
