"""Bug Fix Sprint 1 — parser routing tests (Bugs 1, 2, 3, 4a).

Covers:
  Bug 1: "Tell me about float <id>" / "Show float <id>" -> metadata_lookup
  Bug 2: "What plots are available for float <id>?"    -> metadata_lookup
  Bug 3: bare 7-digit float ids with profile/plot phrasing populate float_id
  Bug 4a: plural "profiles" over a region -> region_search (discovery)

Every fix also pins the guard rails so the legacy routings that must NOT
change (measurement queries, viz-keyword queries, singular "profile", ...)
keep their pre-sprint behavior.
"""

import pytest

from floatchat.intent_parser.regex import RegexIntentParser, is_available_plots_query


@pytest.fixture
def parser() -> RegexIntentParser:
    return RegexIntentParser()


# --------------------------------------------------------------------------- #
# Bug 1: float-information phrasing routes to metadata_lookup
# --------------------------------------------------------------------------- #
class TestBug1MetadataRouting:
    def test_tell_me_about_float_is_metadata_lookup(self, parser: RegexIntentParser) -> None:
        intent = parser.parse("Tell me about float 1902190")
        assert intent.intent == "metadata_lookup"
        assert intent.float_id == "1902190"
        assert intent.variables == []

    def test_show_float_is_metadata_lookup(self, parser: RegexIntentParser) -> None:
        intent = parser.parse("Show float 999999999")
        assert intent.intent == "metadata_lookup"
        assert intent.float_id == "999999999"

    def test_describe_float_is_metadata_lookup(self, parser: RegexIntentParser) -> None:
        intent = parser.parse("describe float 1902190")
        assert intent.intent == "metadata_lookup"

    # --- guards: requests that must stay on the profile/plot pipeline ------ #
    def test_tell_me_about_variable_of_float_stays_profile(self, parser: RegexIntentParser) -> None:
        # variables extracted -> measurement request, not a float-info request
        intent = parser.parse("tell me about the oxygen of float 1902190")
        assert intent.intent == "profile_plot"
        assert intent.variables == ["DOXY"]

    def test_tell_me_about_float_profile_stays_profile(self, parser: RegexIntentParser) -> None:
        # explicit visualization keyword -> keep default routing
        intent = parser.parse("tell me about the profile of float 1902190")
        assert intent.intent == "profile_plot"

    def test_tell_me_about_region_variable_not_metadata(self, parser: RegexIntentParser) -> None:
        # no float_id -> float-info rule must not fire
        intent = parser.parse("Tell me about oxygen in Arabian Sea")
        assert intent.intent == "region_search"

    def test_show_float_trajectory_stays_trajectory(self, parser: RegexIntentParser) -> None:
        intent = parser.parse("show trajectory of float 6903091")
        assert intent.intent == "trajectory"

    def test_show_profile_number_stays_profile(self, parser: RegexIntentParser) -> None:
        intent = parser.parse("Show profile #12 of float 7901136")
        assert intent.intent == "profile_plot"
        assert intent.profile_number == 12


# --------------------------------------------------------------------------- #
# Bug 2: available-plots capability questions route to metadata_lookup
# --------------------------------------------------------------------------- #
class TestBug2AvailablePlotsRouting:
    def test_what_plots_available_is_metadata_lookup(self, parser: RegexIntentParser) -> None:
        intent = parser.parse("What plots are available for float 2903467?")
        assert intent.intent == "metadata_lookup"
        assert intent.float_id == "2903467"

    def test_available_plots_variant(self, parser: RegexIntentParser) -> None:
        intent = parser.parse("Show available plots for float 2903467")
        assert intent.intent == "metadata_lookup"

    def test_bare_show_plot_not_captured(self) -> None:
        assert is_available_plots_query("show plot of temperature in arabian sea") is False

    def test_capability_phrase_detection(self) -> None:
        assert is_available_plots_query("what plots are available for float 2903467?") is True
        assert is_available_plots_query("available plot for this float") is True


# --------------------------------------------------------------------------- #
# Bug 3: explicit float ids always populate float_id (profile phrasing)
# --------------------------------------------------------------------------- #
class TestBug3BareFloatIdParsing:
    def test_oxygen_profile_for_bare_id(self, parser: RegexIntentParser) -> None:
        intent = parser.parse("Show oxygen profile for 4902623")
        assert intent.intent == "profile_plot"
        assert intent.float_id == "4902623"
        assert intent.variables == ["DOXY"]

    def test_bare_id_with_plot_keyword(self, parser: RegexIntentParser) -> None:
        intent = parser.parse("plot temperature for 4902623")
        assert intent.float_id == "4902623"

    def test_year_not_captured_as_float(self, parser: RegexIntentParser) -> None:
        # 4-digit years must never be mistaken for a float id
        intent = parser.parse("Show oxygen profile in 2024")
        assert intent.float_id is None
        assert intent.year == 2024

    def test_explicit_float_prefix_unchanged(self, parser: RegexIntentParser) -> None:
        intent = parser.parse("Show oxygen profile for float 4902623")
        assert intent.float_id == "4902623"

    def test_bare_id_regional_query_scoped(self, parser: RegexIntentParser) -> None:
        intent = parser.parse("Show temperature profiles in Arabian Sea for float 6903091")
        assert intent.intent == "profile_plot"
        assert intent.float_id == "6903091"


# --------------------------------------------------------------------------- #
# Bug 4a: plural "profiles" over a region routes to region_search
# --------------------------------------------------------------------------- #
class TestBug4aPluralProfilesRegionRouting:
    def test_temperature_profiles_in_region_is_region_search(self, parser: RegexIntentParser) -> None:
        intent = parser.parse("Show temperature profiles in Arabian Sea")
        assert intent.intent == "region_search"
        assert intent.variables == ["TEMP"]
        assert intent.region == "arabian_sea"

    def test_oxygen_profiles_in_region_is_region_search(self, parser: RegexIntentParser) -> None:
        intent = parser.parse("oxygen profiles in Bay of Bengal")
        assert intent.intent == "region_search"
        assert intent.region == "bay_of_bengal"

    # --- guards ----------------------------------------------------------- #
    def test_singular_profile_stays_profile_plot(self, parser: RegexIntentParser) -> None:
        intent = parser.parse("Show oxygen profile in Arabian Sea for 2024")
        assert intent.intent == "profile_plot"

    def test_plot_keyword_stays_profile_plot(self, parser: RegexIntentParser) -> None:
        intent = parser.parse("plot temperature profile in Arabian Sea")
        assert intent.intent == "profile_plot"

    def test_plain_region_variable_stays_region_search(self, parser: RegexIntentParser) -> None:
        intent = parser.parse("temperature in Arabian Sea")
        assert intent.intent == "region_search"

    def test_float_scoped_plural_stays_profile_plot(self, parser: RegexIntentParser) -> None:
        intent = parser.parse("Show temperature profiles in Arabian Sea for float 6903091")
        assert intent.intent == "profile_plot"
