"""Tests for Phase 5: Metadata Expansion & Language/Location Intelligence.

Covers:
- Part A: Manufacturer and Battery metadata
- Part B: Expanded fuzzy typo matching
- Part C: Place-name gazetteer
- Part D: Geocoding integration into regex parser
"""

import pytest

from floatchat.intent_parser.fuzzy import correct_variables_with_fuzzy
from floatchat.intent_parser.gazetteer import resolve_place_name, get_gazetteer_entries
from floatchat.intent_parser.regex import RegexIntentParser


# ======================================================================== #
# Part B: Expanded Fuzzy Typo Tolerance
# ======================================================================== #

class TestExpandedFuzzyMatching:
    """Test the expanded _TYPO_MAP and fuzzy matching."""

    def test_tembaratre_corrects_to_temp(self) -> None:
        """'tembaratre' (severe typo) should resolve to TEMP."""
        result = correct_variables_with_fuzzy(["tembaratre"])
        assert result == ["TEMP"]

    def test_temparature_corrects_to_temp(self) -> None:
        result = correct_variables_with_fuzzy(["temparature"])
        assert result == ["TEMP"]

    def test_salt_corrects_to_psal(self) -> None:
        result = correct_variables_with_fuzzy(["salt"])
        assert result == ["PSAL"]

    def test_salinty_corrects_to_psal(self) -> None:
        result = correct_variables_with_fuzzy(["salinty"])
        assert result == ["PSAL"]

    def test_salinity_corrects_to_psal(self) -> None:
        result = correct_variables_with_fuzzy(["salinity"])
        assert result == ["PSAL"]

    def test_doxy_corrects_to_doxy(self) -> None:
        result = correct_variables_with_fuzzy(["doxy"])
        assert result == ["DOXY"]

    def test_o2_corrects_to_doxy(self) -> None:
        result = correct_variables_with_fuzzy(["o2"])
        assert result == ["DOXY"]

    def test_chl_corrects_to_chla(self) -> None:
        result = correct_variables_with_fuzzy(["chl"])
        assert result == ["CHLA"]

    def test_chlorophyl_corrects_to_chla(self) -> None:
        result = correct_variables_with_fuzzy(["chlorophyl"])
        assert result == ["CHLA"]

    def test_chlorphyll_corrects_to_chla(self) -> None:
        result = correct_variables_with_fuzzy(["chlorphyll"])
        assert result == ["CHLA"]

    def test_no3_corrects_to_nitrate(self) -> None:
        result = correct_variables_with_fuzzy(["no3"])
        assert result == ["NITRATE"]

    def test_ph_corrects_to_ph(self) -> None:
        result = correct_variables_with_fuzzy(["ph"])
        assert result == ["PH_IN_SITU_TOTAL"]

    def test_canonical_passthrough(self) -> None:
        """Canonical variable names should pass through unchanged."""
        result = correct_variables_with_fuzzy(["TEMP", "PSAL", "DOXY", "CHLA"])
        assert result == ["TEMP", "PSAL", "DOXY", "CHLA"]

    def test_multiple_typos(self) -> None:
        """Multiple typos in one list should all be corrected."""
        result = correct_variables_with_fuzzy(["tembaratre", "salinty", "chlorphyll"])
        assert result == ["TEMP", "PSAL", "CHLA"]

    def test_sst_corrects_to_temp(self) -> None:
        result = correct_variables_with_fuzzy(["sst"])
        assert result == ["TEMP"]

    def test_phytoplankton_corrects_to_chla(self) -> None:
        result = correct_variables_with_fuzzy(["phytoplankton"])
        assert result == ["CHLA"]


# ======================================================================== #
# Part C: Place-Name Gazetteer
# ======================================================================== #

class TestPlaceNameGazetteer:
    """Test the 3-layer gazetteer fallback chain."""

    def test_gazetteer_has_entries(self) -> None:
        """Gazetteer should have a reasonable number of entries."""
        entries = get_gazetteer_entries()
        assert len(entries) >= 30

    def test_exact_match_mumbai(self) -> None:
        result = resolve_place_name("Mumbai")
        assert result is not None
        assert result["source"] == "local_gazetteer"
        assert abs(result["lat"] - 19.07) < 0.1
        assert abs(result["lon"] - 72.87) < 0.1

    def test_exact_match_chennai(self) -> None:
        result = resolve_place_name("chennai")
        assert result is not None
        assert result["lat"] == 13.08
        assert result["lon"] == 80.27

    def test_exact_match_kerala_coast(self) -> None:
        result = resolve_place_name("Kerala coast")
        assert result is not None
        assert result["source"] == "local_gazetteer"
        assert abs(result["lat"] - 9.9) < 0.5
        assert abs(result["lon"] - 76.3) < 0.5
        assert result["radius_km"] == 150

    def test_alias_match_bombay(self) -> None:
        """'Bombay' should resolve to same coords as Mumbai."""
        result = resolve_place_name("Bombay")
        assert result is not None
        assert abs(result["lat"] - 19.07) < 0.1

    def test_alias_match_cochin(self) -> None:
        """'Cochin' should resolve to Kochi coordinates."""
        result = resolve_place_name("Cochin")
        assert result is not None
        assert abs(result["lat"] - 9.93) < 0.1

    def test_fuzzy_match_keral_coast(self) -> None:
        """'Keral coast' (typo) should fuzzy-match to 'kerala coast'."""
        result = resolve_place_name("Keral coast")
        assert result is not None
        assert "kerala" in result.get("place_name", "").lower() or result.get("source") == "local_gazetteer_fuzzy"

    def test_fuzzy_match_mumbi(self) -> None:
        """'Mumbi' should fuzzy-match to 'mumbai'."""
        result = resolve_place_name("Mumbi")
        assert result is not None
        # Should resolve to something close to Mumbai
        assert result.get("source") in ("local_gazetteer_fuzzy", "local_gazetteer")

    def test_default_radius(self) -> None:
        """Gazetteer entries should have default radius values."""
        result = resolve_place_name("goa")
        assert result is not None
        assert result["radius_km"] == 100

    def test_empty_string_returns_none(self) -> None:
        result = resolve_place_name("")
        assert result is None

    def test_nonsense_returns_none_or_nominatim(self) -> None:
        """A completely nonsensical place name should return None (Nominatim will fail)."""
        result = resolve_place_name("xyzzyqplf_no_such_place")
        # Nominatim won't find this, so should be None
        assert result is None

    def test_offshore_feature_lakshadweep(self) -> None:
        result = resolve_place_name("Lakshadweep")
        assert result is not None
        assert abs(result["lat"] - 10.55) < 1.0

    def test_coromandel_coast(self) -> None:
        result = resolve_place_name("Coromandel coast")
        assert result is not None


# ======================================================================== #
# Part D: Geocoding Integration into RegexIntentParser
# ======================================================================== #

class TestGeocodingIntegration:
    """Test that place names are resolved to coordinates in the parser."""

    def test_floats_near_chennai(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("floats near Chennai")
        assert intent.intent == "radius_search"
        assert intent.lat is not None
        assert intent.lon is not None
        # Chennai coords: 13.08, 80.27
        assert abs(intent.lat - 13.08) < 0.5
        assert abs(intent.lon - 80.27) < 0.5

    def test_floats_within_100km_of_mumbai(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("floats within 100km of Mumbai")
        assert intent.intent == "radius_search"
        assert intent.radius_km == 100.0
        assert intent.lat is not None
        assert abs(intent.lat - 19.07) < 0.5

    def test_nearest_float_to_kerala_coast(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("nearest float to Kerala coast")
        assert intent.intent == "nearest_float"
        assert intent.lat is not None
        assert intent.lon is not None

    def test_floats_near_goa_with_radius(self) -> None:
        parser = RegexIntentParser()
        intent = parser.parse("floats within 50km of Goa")
        assert intent.intent == "radius_search"
        assert intent.radius_km == 50.0
        assert intent.lat is not None
        assert abs(intent.lat - 15.30) < 0.5

    def test_explicit_coordinates_still_work(self) -> None:
        """Explicit lat/lon should take precedence over gazetteer."""
        parser = RegexIntentParser()
        intent = parser.parse("nearest float to 15.5, 72.3")
        assert intent.intent == "nearest_float"
        assert intent.lat == 15.5
        assert intent.lon == 72.3

    def test_bengal_resolves_to_bay_of_bengal_area(self) -> None:
        """'Bengal' should resolve to Bay of Bengal coastal area, not Kerala."""
        result = resolve_place_name("bengal")
        assert result is not None
        # Bengal should be around lat 21-22, lon 87-89 (West Bengal)
        assert result["lat"] > 20.0
        assert result["lon"] > 85.0

    def test_default_radius_is_500km(self) -> None:
        """Phase 5: When no distance specified, default radius is 500km."""
        parser = RegexIntentParser()
        intent = parser.parse("floats near Chennai")
        assert intent.intent == "radius_search"
        assert intent.radius_km == 500.0

    def test_geocoding_failure_raises_error(self) -> None:
        """If place name can't be resolved, parser should raise helpful error."""
        from floatchat.exceptions import IntentParseError
        parser = RegexIntentParser()
        with pytest.raises(IntentParseError, match="Could not resolve location"):
            parser.parse("floats near Zzyzxville")


# ======================================================================== #
# Part A: Battery Estimation (Unit Tests)
# ======================================================================== #

class TestBatteryEstimation:
    """Test the battery estimation logic."""

    def test_fresh_float_good_battery(self) -> None:
        from floatchat.data_lake.duckdb_lake import DuckDBDataLake
        result = DuckDBDataLake._estimate_battery_status(
            profile_count=10,
            first_profile_date="2025-01-01",
            last_report_date="2025-03-01",
            status="active",
            profiler_type="836",  # PROVOR CTS4 — 500 profile lifetime
        )
        assert result["battery_status"] == "Good"
        assert result["battery_percentage"] is not None
        assert result["battery_percentage"] >= 90
        assert result["battery_voltage"] is not None
        assert result["battery_voltage"] >= 14.0

    def test_midlife_float_fair_battery(self) -> None:
        from floatchat.data_lake.duckdb_lake import DuckDBDataLake
        result = DuckDBDataLake._estimate_battery_status(
            profile_count=300,
            first_profile_date="2022-01-01",
            last_report_date="2025-06-01",
            status="active",
            profiler_type="836",  # PROVOR CTS4 — 500 profile lifetime
        )
        assert result["battery_status"] == "Fair"
        assert result["battery_percentage"] is not None
        assert 30 <= result["battery_percentage"] <= 50

    def test_high_profile_active_float_not_critical(self) -> None:
        """Phase 5 fix: Active float with 430 profiles should NOT show Critical/0%."""
        from floatchat.data_lake.duckdb_lake import DuckDBDataLake
        result = DuckDBDataLake._estimate_battery_status(
            profile_count=430,
            first_profile_date="2021-03-06",
            last_report_date="2026-07-07",  # reported 10 days ago
            status="active",
            profiler_type="836",  # PROVOR CTS4 — 500 profile lifetime
        )
        # Active float reported recently — should NOT be Critical or 0%
        assert result["battery_status"] != "Critical"
        assert result["battery_percentage"] > 0
        # With 500-profile lifetime and 430 profiles: raw = 14%, floor applied to 25% (Fair)
        assert result["battery_percentage"] >= 14
        assert result["battery_status"] in ("Fair", "Low")

    def test_old_float_low_battery(self) -> None:
        from floatchat.data_lake.duckdb_lake import DuckDBDataLake
        result = DuckDBDataLake._estimate_battery_status(
            profile_count=250,
            first_profile_date="2020-01-01",
            last_report_date="2025-06-01",
            status="active",
            profiler_type="831",  # APEX — 280 profile lifetime (alkaline)
        )
        # 250/280 = 89% used, but active so gets floor adjustment
        assert result["battery_status"] in ("Low", "Critical", "Fair")

    def test_inactive_float_depleted(self) -> None:
        from floatchat.data_lake.duckdb_lake import DuckDBDataLake
        result = DuckDBDataLake._estimate_battery_status(
            profile_count=300,
            first_profile_date="2018-01-01",
            last_report_date="2022-01-01",
            status="inactive",
            profiler_type="831",
        )
        assert result["battery_status"] == "Depleted"
        assert result["battery_percentage"] == 0

    def test_zero_profiles_unknown(self) -> None:
        from floatchat.data_lake.duckdb_lake import DuckDBDataLake
        result = DuckDBDataLake._estimate_battery_status(
            profile_count=0,
            first_profile_date=None,
            last_report_date=None,
            status="unknown",
        )
        assert result["battery_status"] == "Unknown"

    def test_apex_shorter_lifetime(self) -> None:
        """APEX floats have shorter battery life (alkaline)."""
        from floatchat.data_lake.duckdb_lake import DuckDBDataLake
        result = DuckDBDataLake._estimate_battery_status(
            profile_count=200,
            first_profile_date="2022-01-01",
            last_report_date="2024-12-01",
            status="active",
            profiler_type="831",  # APEX — 280 profile lifetime
        )
        # 200/280 = 71% used → ~29% remaining, but active floor may apply
        assert result["battery_percentage"] >= 15

    def test_provor_longer_lifetime(self) -> None:
        """PROVOR CTS5 floats have longer battery life (lithium)."""
        from floatchat.data_lake.duckdb_lake import DuckDBDataLake
        result = DuckDBDataLake._estimate_battery_status(
            profile_count=200,
            first_profile_date="2022-01-01",
            last_report_date="2025-12-01",
            status="active",
            profiler_type="837",  # PROVOR CTS5 — 550 profile lifetime
        )
        # 200/550 = 36% used → ~64% remaining
        assert result["battery_percentage"] >= 50
        assert result["battery_status"] in ("Good", "Fair")


# ======================================================================== #
# Part A: Manufacturer Resolution
# ======================================================================== #

class TestManufacturerResolution:
    """Test the profiler type to manufacturer mapping."""

    def test_apex_manufacturer(self) -> None:
        from floatchat.query_engine.engine import _resolve_manufacturer
        assert _resolve_manufacturer("831") == "Teledyne Webb"
        assert _resolve_manufacturer("832") == "Teledyne Webb"

    def test_provor_manufacturer(self) -> None:
        from floatchat.query_engine.engine import _resolve_manufacturer
        assert _resolve_manufacturer("836") == "Teledyne CARAIBE"
        assert _resolve_manufacturer("837") == "Teledyne CARAIBE"

    def test_navis_manufacturer(self) -> None:
        from floatchat.query_engine.engine import _resolve_manufacturer
        assert _resolve_manufacturer("845") == "Teledyne Webb"

    def test_solo_manufacturer(self) -> None:
        from floatchat.query_engine.engine import _resolve_manufacturer
        assert _resolve_manufacturer("851") == "Scripps/Floats Inc."

    def test_arvor_manufacturer(self) -> None:
        from floatchat.query_engine.engine import _resolve_manufacturer
        assert _resolve_manufacturer("861") == "Teledyne CARAIBE"
        assert _resolve_manufacturer("862") == "Teledyne CARAIBE"

    def test_ninja_manufacturer(self) -> None:
        from floatchat.query_engine.engine import _resolve_manufacturer
        assert _resolve_manufacturer("846") == "Tsurumi Seiki"

    def test_unknown_profiler_returns_none(self) -> None:
        from floatchat.query_engine.engine import _resolve_manufacturer
        assert _resolve_manufacturer("999") is None
        assert _resolve_manufacturer("") is None
        assert _resolve_manufacturer(None) is None
