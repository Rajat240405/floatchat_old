"""Tests for ``_check_critical_fields`` (chat_service).

Milestone 5 restores the coverage that was intentionally deferred in M2,
against the function's current, audited contract:

- radius_search / nearest_float : need a location (coords or region); context exempts
- metadata_lookup / trajectory  : need a float_id; context exempts
- count_aggregate               : need a region or location; context exempts
- data queries                  : need variables AND spatial scope; context exempts
"""

from floatchat.api.services.chat_service import _check_critical_fields
from floatchat.models import ParsedIntent


class TestSpatialDiscoveryIntents:
    def test_radius_search_no_location_no_context_asks(self) -> None:
        intent = ParsedIntent(intent="radius_search")
        msg = _check_critical_fields(intent, has_context=False)
        assert msg is not None and "Which location" in msg

    def test_radius_search_no_location_with_context_passes(self) -> None:
        intent = ParsedIntent(intent="radius_search")
        assert _check_critical_fields(intent, has_context=True) is None

    def test_radius_search_with_coordinates_passes(self) -> None:
        intent = ParsedIntent(intent="radius_search", lat=15.0, lon=65.0)
        assert _check_critical_fields(intent, has_context=False) is None

    def test_nearest_float_with_region_passes(self) -> None:
        intent = ParsedIntent(intent="nearest_float", region="arabian_sea")
        assert _check_critical_fields(intent, has_context=False) is None


class TestFloatScopedIntents:
    def test_metadata_lookup_without_float_asks(self) -> None:
        intent = ParsedIntent(intent="metadata_lookup")
        msg = _check_critical_fields(intent, has_context=False)
        assert msg is not None and "Which float" in msg

    def test_metadata_lookup_with_float_passes(self) -> None:
        intent = ParsedIntent(intent="metadata_lookup", float_id="2902403")
        assert _check_critical_fields(intent, has_context=False) is None

    def test_trajectory_without_float_with_context_passes(self) -> None:
        intent = ParsedIntent(intent="trajectory")
        assert _check_critical_fields(intent, has_context=True) is None

    def test_trajectory_without_float_no_context_asks(self) -> None:
        intent = ParsedIntent(intent="trajectory")
        msg = _check_critical_fields(intent, has_context=False)
        assert msg is not None and "Which float" in msg


class TestCountAggregate:
    def test_count_without_region_or_context_asks(self) -> None:
        intent = ParsedIntent(intent="count_aggregate")
        msg = _check_critical_fields(intent, has_context=False)
        assert msg is not None and "Which region" in msg

    def test_count_with_region_passes(self) -> None:
        intent = ParsedIntent(intent="count_aggregate", region="bay_of_bengal")
        assert _check_critical_fields(intent, has_context=False) is None

    def test_count_with_location_passes(self) -> None:
        intent = ParsedIntent(intent="count_aggregate", lat=18.9, lon=72.8)
        assert _check_critical_fields(intent, has_context=False) is None


class TestDataQueries:
    def test_no_variables_no_scope_asks_generic_help(self) -> None:
        intent = ParsedIntent(intent="region_search")
        msg = _check_critical_fields(intent, has_context=False)
        assert msg is not None and "I can help with Argo ocean data" in msg

    def test_scope_without_variables_asks_for_variable(self) -> None:
        intent = ParsedIntent(intent="region_search", region="arabian_sea")
        msg = _check_critical_fields(intent, has_context=False)
        assert msg is not None and "Which variable" in msg

    def test_variables_without_scope_asks_for_region(self) -> None:
        intent = ParsedIntent(intent="profile_plot", variables=["TEMP"])
        msg = _check_critical_fields(intent, has_context=False)
        assert msg is not None and "Which region or location" in msg

    def test_variables_and_scope_pass(self) -> None:
        intent = ParsedIntent(
            intent="profile_plot", variables=["TEMP"], region="arabian_sea"
        )
        assert _check_critical_fields(intent, has_context=False) is None

    def test_float_scoped_data_query_passes(self) -> None:
        intent = ParsedIntent(intent="time_series", float_id="2902403")
        assert _check_critical_fields(intent, has_context=False) is None

    def test_missing_fields_exempted_by_context(self) -> None:
        intent = ParsedIntent(intent="region_search")
        assert _check_critical_fields(intent, has_context=True) is None
