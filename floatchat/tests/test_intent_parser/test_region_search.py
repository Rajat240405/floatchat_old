"""Tests for region_search intent detection (Phase 1)."""

import pytest

from floatchat.intent_parser.regex import RegexIntentParser


class TestRegionSearchIntentDetection:
    """Phase 1: Verify the regex parser correctly identifies region_search intent."""

    @pytest.fixture
    def parser(self) -> RegexIntentParser:
        return RegexIntentParser()

    def test_temperature_in_arabian_sea_is_region_search(self, parser: RegexIntentParser) -> None:
        """Query about conditions in a region without 'plot/profile' → region_search."""
        intent = parser.parse("temperature in Arabian Sea")
        assert intent.intent == "region_search"
        assert intent.variables == ["TEMP"]
        assert intent.region == "arabian_sea"

    def test_oxygen_conditions_bay_of_bengal(self, parser: RegexIntentParser) -> None:
        intent = parser.parse("oxygen conditions in Bay of Bengal")
        assert intent.intent == "region_search"
        assert intent.variables == ["DOXY"]

    def test_chlorophyll_bay_of_bengal_region_search(self, parser: RegexIntentParser) -> None:
        intent = parser.parse("chlorophyll in bay of bengal")
        assert intent.intent == "region_search"
        assert intent.variables == ["CHLA"]

    def test_plot_profile_goes_to_profile_plot(self, parser: RegexIntentParser) -> None:
        """Explicit 'plot' keyword → profile_plot even if region is present."""
        intent = parser.parse("plot temperature profile in Arabian Sea")
        assert intent.intent == "profile_plot"

    def test_indian_ocean_region_search(self, parser: RegexIntentParser) -> None:
        intent = parser.parse("temperature in Indian Ocean")
        assert intent.intent == "region_search"

    def test_no_variables_raises(self, parser: RegexIntentParser) -> None:
        """region_search without variables should still raise (needs at least a variable)."""
        from floatchat.exceptions import IntentParseError

        with pytest.raises(IntentParseError):
            parser.parse("conditions in Arabian Sea")

    def test_year_filter_preserved(self, parser: RegexIntentParser) -> None:
        intent = parser.parse("salinity conditions in Arabian Sea for 2023")
        assert intent.intent == "region_search"
        assert intent.year == 2023
        assert intent.variables == ["PSAL"]
