"""Milestone 4: dispatch-layer contract tests.

Locks the intent→executor routing semantics that were previously the
if-chain inside the engine monolith, and the data-intent vocabulary that
QueryEngine.execute() validates against.
"""

from floatchat.query_engine import dispatch
from floatchat.query_engine.executors import metadata as metadata_executors
from floatchat.query_engine.executors import profile, spatial, trajectory


class TestDataIntentVocabulary:
    def test_data_intents_contents(self) -> None:
        assert dispatch._DATA_INTENTS == frozenset({
            "region_search",
            "profile_plot",
            "time_series",
            "trajectory",
            "hovmoller",
            "ts_diagram",
            "comparison",
            "comparison_plot",
            "nearest_float",
            "radius_search",
            "count_aggregate",
            "metadata_lookup",
        })


class TestRouteTable:
    def test_named_intent_routes(self) -> None:
        assert dispatch.route("nearest_float") is spatial.execute_nearest_float
        assert dispatch.route("radius_search") is spatial.execute_radius_search
        assert dispatch.route("metadata_lookup") is metadata_executors.execute_metadata_lookup
        assert dispatch.route("count_aggregate") is metadata_executors.execute_count_aggregate
        assert dispatch.route("trajectory") is trajectory.execute_trajectory

    def test_remaining_data_intents_default_to_data_query_executor(self) -> None:
        for name in (
            "region_search",
            "profile_plot",
            "time_series",
            "hovmoller",
            "ts_diagram",
            "comparison",
            "comparison_plot",
        ):
            assert dispatch.route(name) is profile.execute_data_query_via_lake, name

    def test_execution_deps_fields(self) -> None:
        deps = dispatch.ExecutionDeps(
            lake=None, metadata=None, repository=None,
            reader=None, viz=None, explanation_engine=None, planner=None,
        )
        assert deps.lake is None and deps.planner is None
