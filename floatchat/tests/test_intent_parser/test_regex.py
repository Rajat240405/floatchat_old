"""Tests for RegexIntentParser.

Covers the full matrix of supported query variations:
- variables (synonyms and canonical names)
- regions (with and without)
- years (with and without, ranges)
- float IDs (with and without)
- intent detection keywords
"""

import pytest

from floatchat.exceptions import IntentParseError
from floatchat.intent_parser.regex import RegexIntentParser


class TestRegexIntentParser:
    # ------------------------------------------------------------------ #
    # Basic variable recognition
    # ------------------------------------------------------------------ #

    def test_oxygen_profile_arabian_sea_year(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("Show oxygen profile in Arabian Sea for 2024")
        assert intent.intent == "profile_plot"
        assert intent.region == "arabian_sea"
        assert "DOXY" in intent.variables
        assert intent.year == 2024

    def test_oxygen_profile_no_region_no_year(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("oxygen profile")
        assert intent.intent == "profile_plot"
        assert intent.variables == ["DOXY"]
        assert intent.region is None
        assert intent.year is None

    def test_oxygen_data(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("oxygen data")
        assert "DOXY" in intent.variables

    def test_show_oxygen(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("show oxygen")
        assert "DOXY" in intent.variables

    def test_plot_oxygen(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("plot oxygen")
        assert "DOXY" in intent.variables

    def test_plot_doxy_canonical(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("plot doxy")
        assert "DOXY" in intent.variables

    def test_dissolved_oxygen_phrase(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("dissolved oxygen in north atlantic")
        assert "DOXY" in intent.variables
        assert intent.region == "north_atlantic"

    # ------------------------------------------------------------------ #
    # Other variables
    # ------------------------------------------------------------------ #

    def test_temperature_profile(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("temperature profile")
        assert "TEMP" in intent.variables

    def test_salinity_profile(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("salinity profile")
        assert "PSAL" in intent.variables

    def test_chlorophyll_profile(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("chlorophyll profile")
        assert "CHLA" in intent.variables

    def test_nitrate_profile(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("nitrate profile")
        assert "NITRATE" in intent.variables

    def test_ph_profile(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("ph profile")
        assert "PH_IN_SITU_TOTAL" in intent.variables

    def test_backscattering_profile(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("backscattering profile")
        assert "BBP700" in intent.variables

    # ------------------------------------------------------------------ #
    # Regions
    # ------------------------------------------------------------------ #

    def test_oxygen_in_arabian_sea(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("oxygen in arabian sea")
        assert "DOXY" in intent.variables
        assert intent.region == "arabian_sea"

    def test_oxygen_in_bay_of_bengal(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("oxygen in bay of bengal")
        assert "DOXY" in intent.variables
        assert intent.region == "bay_of_bengal"

    def test_oxygen_in_indian_ocean(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("oxygen in indian ocean")
        assert "DOXY" in intent.variables
        assert intent.region == "indian_ocean"

    def test_chlorophyll_backscattering_north_atlantic(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("Plot chlorophyll and backscattering in North Atlantic")
        assert intent.intent == "profile_plot"
        assert intent.region == "north_atlantic"
        assert "CHLA" in intent.variables
        assert "BBP700" in intent.variables

    def test_temperature_salinity_southern_ocean(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("Show temperature and salinity in Southern Ocean")
        assert "TEMP" in intent.variables
        assert "PSAL" in intent.variables
        assert intent.region == "southern_ocean"

    def test_mediterranean_alias(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("salinity in mediterranean")
        assert intent.region == "mediterranean_sea"

    # ------------------------------------------------------------------ #
    # Years
    # ------------------------------------------------------------------ #

    def test_oxygen_for_2024(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("oxygen for 2024")
        assert "DOXY" in intent.variables
        assert intent.year == 2024

    def test_oxygen_between_2022_and_2024(self) -> None:
        """Year ranges: extract the first year as the primary filter."""
        parser = RegexIntentParser()
        intent = parser.parse("oxygen between 2022 and 2024")
        assert "DOXY" in intent.variables
        assert intent.year == 2022

    def test_oxygen_from_2022_to_2024(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("oxygen from 2022 to 2024")
        assert "DOXY" in intent.variables
        assert intent.year == 2022

    def test_no_year(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("oxygen in arabian sea")
        assert intent.year is None

    # ------------------------------------------------------------------ #
    # Float IDs
    # ------------------------------------------------------------------ #

    def test_float_id_only(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("float 6903091")
        assert intent.float_id == "6903091"
        assert intent.variables == []

    def test_nitrate_float_6903091(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("nitrate float 6903091")
        assert intent.float_id == "6903091"
        assert "NITRATE" in intent.variables

    def test_wmo_id(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("WMO 6903091")
        assert intent.float_id == "6903091"

    # ------------------------------------------------------------------ #
    # Complex combinations
    # ------------------------------------------------------------------ #

    def test_multiple_variables_region_year_float(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse(
            "Show temperature, salinity and oxygen in Arabian Sea for 2023 for float 6903091"
        )
        assert intent.intent == "profile_plot"
        assert set(intent.variables) == {"TEMP", "PSAL", "DOXY"}
        assert intent.region == "arabian_sea"
        assert intent.year == 2023
        assert intent.float_id == "6903091"

    def test_get_nitrate_for_float(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("Get nitrate for float 6903091")
        assert intent.float_id == "6903091"
        assert "NITRATE" in intent.variables

    # ------------------------------------------------------------------ #
    # Conversational follow-ups
    # ------------------------------------------------------------------ #

    def test_conversational_actually_chlorophyll(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("Actually chlorophyll")
        assert "CHLA" in intent.variables

    def test_conversational_instead_oxygen(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("Instead oxygen")
        assert "DOXY" in intent.variables

    def test_conversational_now_temperature(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("Now temperature")
        assert "TEMP" in intent.variables

    def test_conversational_compare_with_year(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("Compare with 2023")
        assert intent.intent == "comparison_plot"
        assert intent.year == 2023

    def test_conversational_compare_against(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("Compare against 2022")
        assert intent.intent == "comparison_plot"
        assert intent.year == 2022

    def test_conversational_same_float(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("Same float")
        # Conversational flag prevents error even without vars/float
        assert intent.float_id is None
        assert intent.variables == []

    def test_conversational_same_region(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("Same region")
        assert intent.region is None
        assert intent.variables == []

    def test_conversational_same_variable(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("Same variable")
        assert intent.variables == []

    def test_conversational_latest_profile(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("Latest profile")
        assert intent.variables == []

    def test_conversational_that_float(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("That float")
        assert intent.variables == []
        assert intent.float_id is None

    def test_conversational_now_in_region(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("Now in Bay of Bengal")
        assert intent.region == "bay_of_bengal"

    def test_conversational_instead_in_region(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("Instead in Arabian Sea")
        assert intent.region == "arabian_sea"

    def test_conversational_for_year(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("For 2024")
        assert intent.year == 2024

    # ------------------------------------------------------------------ #
    # Profile / cycle number extraction
    # ------------------------------------------------------------------ #

    def test_profile_number_basic(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("Plot oxygen for float 3902490 profile 52")
        assert intent.float_id == "3902490"
        assert "DOXY" in intent.variables
        assert intent.profile_number == 52

    def test_profile_number_with_hash(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("Show profile #12 of float 7901136")
        assert intent.float_id == "7901136"
        assert intent.profile_number == 12

    def test_cycle_number(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("Temperature for float 6903091 cycle 88")
        assert intent.float_id == "6903091"
        assert "TEMP" in intent.variables
        assert intent.profile_number == 88

    def test_no_profile_number(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("oxygen in arabian sea")
        assert intent.profile_number is None

    # ------------------------------------------------------------------ #
    # Phase 3: Spatial and Metadata Lookups
    # ------------------------------------------------------------------ #

    def test_nearest_float_intent(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("nearest float to 15.5, 72.3")
        assert intent.intent == "nearest_float"
        assert intent.lat == 15.5
        assert intent.lon == 72.3

    def test_closest_float_directional(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("closest float to 12.3 N, 68.5 E")
        assert intent.intent == "nearest_float"
        assert intent.lat == 12.3
        assert intent.lon == 68.5

    def test_radius_search_intent(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("within 100km of 15.5, 72.3")
        assert intent.intent == "radius_search"
        assert intent.radius_km == 100.0
        assert intent.lat == 15.5
        assert intent.lon == 72.3

    def test_radius_search_default_radius(self) -> None:
        """Phase 5: Default radius is 500km when not specified."""
        parser = RegexIntentParser()
        intent = parser.parse("floats near 15.5, 72.3")
        assert intent.intent == "radius_search"
        assert intent.radius_km == 500.0
        assert intent.lat == 15.5
        assert intent.lon == 72.3

    def test_metadata_lookup_sensors(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("sensors on float 6903091")
        assert intent.intent == "metadata_lookup"
        assert intent.float_id == "6903091"

    def test_metadata_lookup_parking_depth(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("parking depth of float 6903091")
        assert intent.intent == "metadata_lookup"
        assert intent.float_id == "6903091"

    def test_metadata_lookup_status(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("status of float 6903091")
        assert intent.intent == "metadata_lookup"
        assert intent.float_id == "6903091"

    def test_count_aggregate_profiles(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("how many profiles in Bay of Bengal for 2023")
        assert intent.intent == "count_aggregate"
        assert intent.region == "bay_of_bengal"
        assert intent.year == 2023
        assert intent.existence_check is False

    def test_existence_check_data(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("is there oxygen data in Arabian Sea")
        assert intent.intent == "count_aggregate"
        assert intent.region == "arabian_sea"
        assert "DOXY" in intent.variables
        assert intent.existence_check is True

    # ------------------------------------------------------------------ #
    # Error cases
    # ------------------------------------------------------------------ #

    def test_no_variables_raises(self) -> None:
        parser = RegexIntentParser()
        with pytest.raises(IntentParseError):
            parser.parse("Hello world")

    def test_empty_string_raises(self) -> None:
        parser = RegexIntentParser()
        with pytest.raises(IntentParseError):
            parser.parse("")

    def test_only_region_raises(self) -> None:
        parser = RegexIntentParser()
        with pytest.raises(IntentParseError):
            parser.parse("arabian sea")

    def test_only_year_raises(self) -> None:
        parser = RegexIntentParser()
        with pytest.raises(IntentParseError):
            parser.parse("2024")

    # ------------------------------------------------------------------ #
    # Phase 4: Visualization Expansion Intents
    # ------------------------------------------------------------------ #

    def test_trajectory_intent(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("show trajectory of float 6903091")
        assert intent.intent == "trajectory"
        assert intent.float_id == "6903091"

    def test_time_series_intent(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("time series of temperature in arabian sea")
        assert intent.intent == "time_series"
        assert intent.region == "arabian_sea"
        assert "TEMP" in intent.variables

    def test_hovmoller_intent(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("hovmoller diagram of oxygen in bay of bengal")
        assert intent.intent == "hovmoller"
        assert intent.region == "bay_of_bengal"
        assert "DOXY" in intent.variables

    def test_ts_diagram_intent(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("t-s diagram for float 6903091")
        assert intent.intent == "ts_diagram"
        assert intent.float_id == "6903091"
        assert "TEMP" in intent.variables
        assert "PSAL" in intent.variables

    def test_comparison_intent(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("compare float 6903091 and 5906316 for oxygen")
        assert intent.intent in ("comparison_plot", "comparison")
        assert set(intent.comparison_float_ids) == {"6903091", "5906316"}
        assert "DOXY" in intent.variables
