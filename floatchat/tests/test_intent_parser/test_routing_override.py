"""Regression tests: routing override — variables + spatial = profile_plot.

Verifies that when a scientific variable is present alongside a spatial
constraint (near/within), the intent routes to profile_plot (measurement
retrieval + visualization) instead of radius_search (float listing).

The override is applied in parse() AFTER _detect_intent() returns, keeping
_detect_intent() a pure linguistic classifier. _detect_intent() is unchanged.
"""
import pytest

from floatchat.intent_parser.regex import RegexIntentParser


@pytest.fixture(scope="module")
def parser():
    return RegexIntentParser()


# --------------------------------------------------------------------------- #
# Should STAY radius_search (no variable = float discovery)
# --------------------------------------------------------------------------- #
def test_floats_near_goa_stays_radius_search(parser):
    pi = parser.parse("floats near Goa")
    assert pi.intent == "radius_search"
    assert pi.variables == []


def test_floats_alive_near_goa_stays_radius_search(parser):
    pi = parser.parse("floats alive near Goa")
    assert pi.intent == "radius_search"
    assert pi.variables == []
    assert pi.operational_filter == "alive"


def test_floats_within_radius_during_season_stays_radius_search(parser):
    pi = parser.parse("floats within 1500km of Goa during summer")
    assert pi.intent == "radius_search"
    assert pi.variables == []


# --------------------------------------------------------------------------- #
# Should override to profile_plot (variable present = measurement query)
# --------------------------------------------------------------------------- #
def test_temperature_near_goa_routes_to_profile_plot(parser):
    pi = parser.parse("temperature near Goa")
    assert pi.intent == "profile_plot"
    assert pi.variables == ["TEMP"]


def test_temperature_near_goa_with_radius_routes_to_profile_plot(parser):
    pi = parser.parse("temperature near Goa within 1500km")
    assert pi.intent == "profile_plot"
    assert pi.variables == ["TEMP"]
    # radius_km preserved for future true-haversine filtering
    assert pi.radius_km == 1500.0
    # lat/lon preserved (from gazetteer)
    assert pi.lat is not None
    assert pi.lon is not None


def test_oxygen_within_radius_routes_to_profile_plot(parser):
    pi = parser.parse("oxygen within 500km of Goa")
    assert pi.intent == "profile_plot"
    assert pi.variables == ["DOXY"]
    assert pi.radius_km == 500.0


def test_temperature_within_radius_during_summer_routes_to_profile_plot(parser):
    pi = parser.parse("temperature within 1500km of Goa during summer")
    assert pi.intent == "profile_plot"
    assert pi.variables == ["TEMP"]
    assert pi.radius_km == 1500.0
    # Season resolution should still work
    assert pi.month_window is not None
    assert 3 in pi.month_window  # summer includes March


# --------------------------------------------------------------------------- #
# Verify lat/lon/radius_km are preserved on profile_plot for spatial filtering
# --------------------------------------------------------------------------- #
def test_profile_plot_preserves_spatial_attrs(parser):
    pi = parser.parse("temperature near Goa within 300km")
    assert pi.intent == "profile_plot"
    assert pi.lat is not None
    assert pi.lon is not None
    assert pi.radius_km == 300.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
