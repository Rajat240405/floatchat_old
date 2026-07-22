"""Priority 3: Structured LLM Entity Extractor — Tests.

Tests cover:
  1. Temporal resolver (season → date range)
  2. QuerySpec validation and normalization
  3. LLM Entity Extractor (with mocked Ollama)
  4. Integration: _try_llm_extraction slot filling
"""

import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from floatchat.conversation.memory import InMemoryConversationManager
from floatchat.entity_extractor.extractor import (
    LLMEntityExtractor,
    build_clarification_message,
)
from floatchat.entity_extractor.query_spec import QuerySpec
from floatchat.entity_extractor.temporal_resolver import (
    DateRange,
    resolve_season_token,
    resolve_temporal_filter,
)
from floatchat.models import ChatResponse, ParsedIntent


# =========================================================================== #
# Temporal Resolver Tests
# =========================================================================== #


class TestResolveSeasonToken:
    def test_monsoon(self) -> None:
        dr = resolve_season_token("monsoon", reference_year=2024)
        assert dr is not None
        assert dr.start == date(2024, 6, 1)
        assert dr.end == date(2024, 9, 30)

    def test_winter_crosses_year(self) -> None:
        dr = resolve_season_token("winter", reference_year=2024)
        assert dr is not None
        assert dr.start == date(2024, 12, 1)
        assert dr.end == date(2025, 2, 28)

    def test_last_monsoon(self) -> None:
        dr = resolve_season_token("monsoon", relative="last", reference_year=2024)
        assert dr is not None
        assert dr.start == date(2023, 6, 1)
        assert dr.end == date(2023, 9, 30)

    def test_next_summer(self) -> None:
        dr = resolve_season_token("summer", relative="next", reference_year=2024)
        assert dr is not None
        assert dr.start == date(2025, 3, 1)
        assert dr.end == date(2025, 5, 31)

    def test_unknown_season_returns_none(self) -> None:
        assert resolve_season_token("tornado_season") is None

    def test_pre_monsoon(self) -> None:
        dr = resolve_season_token("pre_monsoon", reference_year=2024)
        assert dr is not None
        assert dr.start == date(2024, 3, 1)
        assert dr.end == date(2024, 5, 31)

    def test_northeast_monsoon(self) -> None:
        dr = resolve_season_token("northeast_monsoon", reference_year=2024)
        assert dr is not None
        assert dr.start == date(2024, 10, 1)
        assert dr.end == date(2024, 12, 31)


class TestResolveTemporalFilter:
    def test_bare_year(self) -> None:
        result = resolve_temporal_filter("2024")
        assert result is not None
        assert result["year"] == 2024

    def test_last_monsoon(self) -> None:
        result = resolve_temporal_filter("last monsoon", reference_year=2024)
        assert result is not None
        assert result["date_start"] == "2023-06-01"
        assert result["date_end"] == "2023-09-30"
        assert result["season"] == "monsoon"

    def test_bare_season(self) -> None:
        result = resolve_temporal_filter("monsoon", reference_year=2024)
        assert result is not None
        assert result["date_start"] == "2024-06-01"
        assert result["date_end"] == "2024-09-30"

    def test_month_name(self) -> None:
        result = resolve_temporal_filter("january", reference_year=2024)
        assert result is not None
        assert result["date_start"] == "2024-01-01"
        assert result["date_end"] == "2024-01-31"

    def test_date_range(self) -> None:
        result = resolve_temporal_filter("2023-06-01 to 2023-09-30")
        assert result is not None
        assert result["date_start"] == "2023-06-01"
        assert result["date_end"] == "2023-09-30"

    def test_year_month(self) -> None:
        result = resolve_temporal_filter("2024-07")
        assert result is not None
        assert result["year"] == 2024
        assert result["month"] == 7

    def test_none_returns_none(self) -> None:
        assert resolve_temporal_filter(None) is None

    def test_empty_returns_none(self) -> None:
        assert resolve_temporal_filter("") is None


# =========================================================================== #
# QuerySpec Validation Tests
# =========================================================================== #


class TestQuerySpec:
    def test_valid_spec(self) -> None:
        spec = QuerySpec(
            action="region_search",
            variables=["TEMP"],
            spatial_filter="arabian_sea",
            time_filter="2024",
            confidence=0.9,
        )
        assert spec.action == "region_search"
        assert spec.variables == ["TEMP"]
        assert spec.spatial_filter == "arabian_sea"
        assert spec.confidence == 0.9

    def test_variable_normalization(self) -> None:
        spec = QuerySpec(
            action="profile_plot",
            variables=["oxygen", "chlorophyll", "temperature"],
            confidence=0.8,
        )
        assert spec.variables == ["DOXY", "CHLA", "TEMP"]

    def test_action_alias_normalization(self) -> None:
        spec = QuerySpec(action="compare", variables=["TEMP"], confidence=0.7)
        assert spec.action == "comparison_plot"

    def test_region_normalization(self) -> None:
        spec = QuerySpec(
            action="region_search",
            variables=["TEMP"],
            spatial_filter="Arabian Sea",
            confidence=0.9,
        )
        assert spec.spatial_filter == "arabian_sea"

    def test_region_alias_bob(self) -> None:
        spec = QuerySpec(
            action="region_search",
            variables=["PSAL"],
            spatial_filter="bob",
            confidence=0.8,
        )
        assert spec.spatial_filter == "bay_of_bengal"

    def test_confidence_bounds(self) -> None:
        with pytest.raises(Exception):
            QuerySpec(action="region_search", confidence=1.5)

    def test_empty_variables_ok(self) -> None:
        spec = QuerySpec(action="trajectory", variables=[], confidence=0.9)
        assert spec.variables == []

    def test_metadata_lookup_action(self) -> None:
        spec = QuerySpec(action="sensor_info", confidence=0.9)
        assert spec.action == "metadata_lookup"


# =========================================================================== #
# LLM Entity Extractor Tests (with mocked Ollama)
# =========================================================================== #


class TestLLMEntityExtractor:
    def _make_extractor(self) -> LLMEntityExtractor:
        """Create extractor with default settings."""
        return LLMEntityExtractor()

    def test_extract_success(self) -> None:
        extractor = self._make_extractor()
        mock_response = json.dumps({
            "action": "region_search",
            "variables": ["DOXY"],
            "spatial_filter": "arabian_sea",
            "time_filter": "2024",
            "float_id": None,
            "depth_filter": None,
            "operational_filter": None,
            "confidence": 0.9,
        })

        with patch.object(extractor, "_call_ollama", return_value=mock_response):
            spec = extractor.extract("oxygen in Arabian Sea 2024")

        assert spec is not None
        assert spec.action == "region_search"
        assert spec.variables == ["DOXY"]
        assert spec.spatial_filter == "arabian_sea"
        assert spec.confidence == 0.9

    def test_extract_low_confidence_returns_none(self) -> None:
        extractor = self._make_extractor()
        mock_response = json.dumps({
            "action": "region_search",
            "variables": [],
            "spatial_filter": None,
            "time_filter": None,
            "float_id": None,
            "depth_filter": None,
            "operational_filter": None,
            "confidence": 0.2,
        })

        with patch.object(extractor, "_call_ollama", return_value=mock_response):
            spec = extractor.extract("something vague")

        assert spec is None

    def test_extract_invalid_json_returns_none(self) -> None:
        extractor = self._make_extractor()

        with patch.object(extractor, "_call_ollama", return_value="not json"):
            spec = extractor.extract("broken query")

        assert spec is None

    def test_extract_ollama_failure_returns_none(self) -> None:
        extractor = self._make_extractor()

        with patch.object(extractor, "_call_ollama", side_effect=Exception("Ollama down")):
            spec = extractor.extract("oxygen in Arabian Sea")

        assert spec is None

    def test_extract_season_token(self) -> None:
        extractor = self._make_extractor()
        mock_response = json.dumps({
            "action": "region_search",
            "variables": ["TEMP"],
            "spatial_filter": "arabian_sea",
            "time_filter": "last monsoon",
            "float_id": None,
            "depth_filter": None,
            "operational_filter": None,
            "confidence": 0.85,
        })

        with patch.object(extractor, "_call_ollama", return_value=mock_response):
            spec = extractor.extract("temperature in Arabian Sea last monsoon")

        assert spec is not None
        assert spec.time_filter == "last monsoon"

        # Verify temporal resolution
        resolved = resolve_temporal_filter(spec.time_filter, reference_year=2024)
        assert resolved is not None
        assert resolved["date_start"] == "2023-06-01"
        assert resolved["date_end"] == "2023-09-30"

    def test_extract_operational_filter_alive(self) -> None:
        extractor = self._make_extractor()
        mock_response = json.dumps({
            "action": "radius_search",
            "variables": [],
            "spatial_filter": "goa",
            "time_filter": "last monsoon",
            "float_id": None,
            "depth_filter": None,
            "operational_filter": "alive",
            "confidence": 0.8,
        })

        with patch.object(extractor, "_call_ollama", return_value=mock_response):
            spec = extractor.extract("alive floats near Goa during last monsoon")

        assert spec is not None
        assert spec.operational_filter == "alive"


class TestBuildClarificationMessage:
    def test_with_spec(self) -> None:
        spec = QuerySpec(
            action="region_search",
            variables=["TEMP"],
            spatial_filter="arabian_sea",
            confidence=0.3,
        )
        msg = build_clarification_message(spec, "temperature there")
        assert "TEMP" in msg
        assert "Arabian Sea" in msg
        assert "30%" in msg

    def test_without_spec(self) -> None:
        msg = build_clarification_message(None, "huh?")
        assert "not sure" in msg.lower()


# =========================================================================== #
# Integration: Slot Filling from LLM Extraction
# =========================================================================== #


class TestLLMExtractionIntegration:
    """Test the _try_llm_extraction slot-filling logic."""

    def test_no_extraction_when_slots_filled(self) -> None:
        """When all critical slots are filled, NO LLM call is made."""
        from floatchat.api.routes import _try_llm_extraction

        mgr = InMemoryConversationManager()
        parsed = ParsedIntent(
            intent="region_search",
            variables=["TEMP"],
            region="arabian_sea",
            year=2024,
        )
        # All slots filled → should return unchanged
        result = _try_llm_extraction("temperature in Arabian Sea 2024", parsed, None, mgr)
        assert result.variables == ["TEMP"]
        assert result.region == "arabian_sea"

    def test_extraction_fills_missing_vars(self) -> None:
        """Phase 1/2: LLM variables are now IGNORED (restricted field).

        The LLM is restricted to temporal + action only. Variables must come
        from the regex parser or conversation context, never from the LLM.
        """
        from floatchat.api.routes import _try_llm_extraction

        mgr = InMemoryConversationManager()
        parsed = ParsedIntent(
            intent="profile_plot",
            variables=[],  # Missing!
            region="arabian_sea",
        )

        mock_spec = QuerySpec(
            action="region_search",
            variables=["DOXY"],  # LLM tries to fill — should be IGNORED
            spatial_filter="arabian_sea",
            confidence=0.85,
        )

        with patch("floatchat.api.routes.LLMEntityExtractor") as MockExtractor:
            instance = MockExtractor.return_value
            instance.extract.return_value = mock_spec
            result = _try_llm_extraction("oxygen there", parsed, None, mgr)

        # Variables must NOT be filled from LLM
        assert result.variables == [], f"LLM variables leaked: {result.variables}"

    def test_extraction_fills_missing_region(self) -> None:
        """When region is missing, LLM extraction fills it."""
        from floatchat.api.routes import _try_llm_extraction

        mgr = InMemoryConversationManager()
        parsed = ParsedIntent(
            intent="profile_plot",
            variables=["TEMP"],
            region=None,  # Missing!
        )

        mock_spec = QuerySpec(
            action="region_search",
            variables=["TEMP"],
            spatial_filter="bay_of_bengal",
            confidence=0.9,
        )

        with patch("floatchat.api.routes.LLMEntityExtractor") as MockExtractor:
            instance = MockExtractor.return_value
            instance.extract.return_value = mock_spec
            result = _try_llm_extraction("temperature in Bay of Bengal", parsed, None, mgr)

        assert result.region == "bay_of_bengal"

    def test_extraction_resolves_temporal_filter(self) -> None:
        """When LLM returns a season token, it gets resolved to a year."""
        from floatchat.api.routes import _try_llm_extraction

        mgr = InMemoryConversationManager()
        # Seed context with year=2024 so temporal resolver uses it
        mgr.update_context(
            "s1",
            ParsedIntent(intent="region_search", variables=["TEMP"], region="arabian_sea", year=2024),
            ChatResponse(intent="region_search", message="ok"),
        )
        parsed = ParsedIntent(
            intent="region_search",
            variables=["TEMP"],
            region="arabian_sea",
            year=None,  # Missing!
        )

        mock_spec = QuerySpec(
            action="region_search",
            variables=["TEMP"],
            spatial_filter="arabian_sea",
            time_filter="last monsoon",
            confidence=0.85,
        )

        with patch("floatchat.api.routes.LLMEntityExtractor") as MockExtractor:
            instance = MockExtractor.return_value
            instance.extract.return_value = mock_spec
            result = _try_llm_extraction(
                "temperature in Arabian Sea during last monsoon", parsed, "s1", mgr
            )

        # "last monsoon" with reference_year=2024 → 2023
        assert result.year == 2023

    def test_extraction_failure_keeps_original(self) -> None:
        """If LLM extraction fails, the original parsed intent is kept."""
        from floatchat.api.routes import _try_llm_extraction

        mgr = InMemoryConversationManager()
        parsed = ParsedIntent(
            intent="profile_plot",
            variables=[],
            region=None,
        )

        with patch("floatchat.api.routes.LLMEntityExtractor") as MockExtractor:
            instance = MockExtractor.return_value
            instance.extract.return_value = None  # Extraction failed
            result = _try_llm_extraction("something vague", parsed, None, mgr)

        # Original intent preserved
        assert result.intent == "profile_plot"
        assert result.variables == []

    def test_metadata_lookup_does_not_need_vars(self) -> None:
        """metadata_lookup with float_id has all critical slots — no LLM call."""
        from floatchat.api.routes import _try_llm_extraction

        mgr = InMemoryConversationManager()
        parsed = ParsedIntent(
            intent="metadata_lookup",
            float_id="2902403",
        )

        with patch("floatchat.api.routes.LLMEntityExtractor") as MockExtractor:
            result = _try_llm_extraction("battery status?", parsed, None, mgr)
            MockExtractor.assert_not_called()  # No LLM call needed

        assert result.float_id == "2902403"

    def test_trajectory_with_float_id_no_llm_needed(self) -> None:
        """trajectory with float_id has all critical slots — no LLM call."""
        from floatchat.api.routes import _try_llm_extraction

        mgr = InMemoryConversationManager()
        parsed = ParsedIntent(
            intent="trajectory",
            float_id="7901128",
        )

        with patch("floatchat.api.routes.LLMEntityExtractor") as MockExtractor:
            result = _try_llm_extraction("trajectory of float 7901128", parsed, None, mgr)
            MockExtractor.assert_not_called()

        assert result.float_id == "7901128"


# =========================================================================== #
# Bug Fix Tests: Priority 3 live verification issues
# =========================================================================== #


class TestStructuralConfidenceOverride:
    """Bug 1 fix: qwen2.5:3b returns confidence=0.0 but extraction is correct.

    The extractor should apply a structural confidence override when the
    extraction has meaningful content (variables, time_filter, spatial_filter,
    or float_id) even if the model reports confidence=0.0.
    """

    def test_confidence_zero_with_variables_overridden(self) -> None:
        """confidence=0.0 + non-empty variables → override to min_confidence."""
        extractor = LLMEntityExtractor()
        mock_response = json.dumps({
            "action": "region_search",
            "variables": ["TEMP"],
            "spatial_filter": "arabian_sea",
            "time_filter": "monsoon",
            "float_id": None,
            "depth_filter": None,
            "operational_filter": None,
            "confidence": 0.0,
        })

        with patch.object(extractor, "_call_ollama", return_value=mock_response):
            spec = extractor.extract("temperature in Arabian Sea during monsoon")

        assert spec is not None
        assert spec.variables == ["TEMP"]
        assert spec.time_filter == "monsoon"
        assert spec.confidence >= 0.5  # Overridden to min_confidence

    def test_confidence_zero_with_time_filter_overridden(self) -> None:
        """confidence=0.0 + time_filter (but no vars) → override."""
        extractor = LLMEntityExtractor()
        mock_response = json.dumps({
            "action": "region_search",
            "variables": [],
            "spatial_filter": None,
            "time_filter": "last monsoon",
            "float_id": None,
            "depth_filter": None,
            "operational_filter": None,
            "confidence": 0.0,
        })

        with patch.object(extractor, "_call_ollama", return_value=mock_response):
            spec = extractor.extract("during last monsoon")

        assert spec is not None
        assert spec.time_filter == "last monsoon"
        assert spec.confidence >= 0.5

    def test_confidence_zero_with_no_content_returns_none(self) -> None:
        """confidence=0.0 + no meaningful content → still returns None."""
        extractor = LLMEntityExtractor()
        mock_response = json.dumps({
            "action": "region_search",
            "variables": [],
            "spatial_filter": None,
            "time_filter": None,
            "float_id": None,
            "depth_filter": None,
            "operational_filter": None,
            "confidence": 0.0,
        })

        with patch.object(extractor, "_call_ollama", return_value=mock_response):
            spec = extractor.extract("something vague")

        assert spec is None

    def test_confidence_zero_with_spatial_filter_overridden(self) -> None:
        """confidence=0.0 + spatial_filter → override."""
        extractor = LLMEntityExtractor()
        mock_response = json.dumps({
            "action": "region_search",
            "variables": [],
            "spatial_filter": "bay_of_bengal",
            "time_filter": None,
            "float_id": None,
            "depth_filter": None,
            "operational_filter": None,
            "confidence": 0.0,
        })

        with patch.object(extractor, "_call_ollama", return_value=mock_response):
            spec = extractor.extract("something in Bay of Bengal")

        assert spec is not None
        assert spec.spatial_filter == "bay_of_bengal"
        assert spec.confidence >= 0.5

    def test_confidence_zero_with_float_id_overridden(self) -> None:
        """confidence=0.0 + float_id → override."""
        extractor = LLMEntityExtractor()
        mock_response = json.dumps({
            "action": "metadata_lookup",
            "variables": [],
            "spatial_filter": None,
            "time_filter": None,
            "float_id": "2902403",
            "depth_filter": None,
            "operational_filter": None,
            "confidence": 0.0,
        })

        with patch.object(extractor, "_call_ollama", return_value=mock_response):
            spec = extractor.extract("status of float 2902403")

        assert spec is not None
        assert spec.float_id == "2902403"
        assert spec.confidence >= 0.5


class TestPlaceNameTemporalStripping:
    """Bug 2 fix: Gazetteer should not receive temporal tokens as part of place name.

    "goa during last monsoon" → place="goa", temporal tokens stripped.
    """

    def test_place_name_strips_during(self) -> None:
        """'floats near Goa during last monsoon' → place='Goa'."""
        from floatchat.intent_parser.regex import RegexIntentParser
        parser = RegexIntentParser()
        place = parser._extract_place_name("alive floats near Goa during last monsoon")
        assert place is not None
        assert "during" not in place.lower()
        assert place.lower().strip() == "goa"

    def test_place_name_strips_last_monsoon(self) -> None:
        """'floats near Mumbai last monsoon' → place='Mumbai'."""
        from floatchat.intent_parser.regex import RegexIntentParser
        parser = RegexIntentParser()
        place = parser._extract_place_name("floats near Mumbai last monsoon")
        assert place is not None
        assert "monsoon" not in place.lower()
        assert place.lower().strip() == "mumbai"

    def test_place_name_strips_during_winter(self) -> None:
        """'floats near Chennai during winter' → place='Chennai'."""
        from floatchat.intent_parser.regex import RegexIntentParser
        parser = RegexIntentParser()
        place = parser._extract_place_name("floats near Chennai during winter")
        assert place is not None
        assert "winter" not in place.lower()
        assert place.lower().strip() == "chennai"

    def test_place_name_without_temporal(self) -> None:
        """'floats near Mumbai' → place='Mumbai' (no regression)."""
        from floatchat.intent_parser.regex import RegexIntentParser
        parser = RegexIntentParser()
        place = parser._extract_place_name("floats near Mumbai")
        assert place is not None
        assert place.lower().strip() == "mumbai"


class TestLLMRecoveryOnParseFailure:
    """Bug 3 fix: LLM extraction should be tried when regex parsing fails.

    When the regex parser raises IntentParseError and conversational recovery
    also fails, the LLM entity extractor should be tried as a last resort.
    """

    def test_llm_recovery_fills_slots(self) -> None:
        """When parse fails, LLM recovery can fill critical slots."""
        from floatchat.api.routes import _try_llm_extraction_as_recovery

        mgr = InMemoryConversationManager()

        mock_spec = QuerySpec(
            action="radius_search",
            variables=[],
            spatial_filter="goa",
            time_filter="last monsoon",
            operational_filter="alive",
            confidence=0.8,
        )

        with patch("floatchat.api.routes.LLMEntityExtractor") as MockExtractor:
            instance = MockExtractor.return_value
            instance.extract.return_value = mock_spec
            # resolve_place_name is imported locally inside the function
            with patch("floatchat.intent_parser.gazetteer.resolve_place_name") as mock_geo:
                mock_geo.return_value = {"lat": 15.49, "lon": 73.83, "source": "nominatim"}
                result = _try_llm_extraction_as_recovery(
                    "alive floats near Goa during last monsoon", None, mgr,
                )

        assert result is not None
        assert result.intent == "radius_search"
        assert result.lat == 15.49
        assert result.lon == 73.83

    def test_llm_recovery_returns_none_on_failure(self) -> None:
        """When LLM extraction also fails, return None."""
        from floatchat.api.routes import _try_llm_extraction_as_recovery

        mgr = InMemoryConversationManager()

        with patch("floatchat.api.routes.LLMEntityExtractor") as MockExtractor:
            instance = MockExtractor.return_value
            instance.extract.return_value = None
            result = _try_llm_extraction_as_recovery(
                "something completely unparseable", None, mgr,
            )

        assert result is None

    def test_llm_recovery_fills_year_from_season(self) -> None:
        """LLM recovery resolves season tokens to years.

        Phase 1/2: variables from LLM are IGNORED — only temporal + spatial
        are accepted from the recovery path.
        """
        from floatchat.api.routes import _try_llm_extraction_as_recovery

        mgr = InMemoryConversationManager()

        mock_spec = QuerySpec(
            action="region_search",
            variables=["TEMP"],  # IGNORED — variables restricted from LLM
            spatial_filter="arabian_sea",
            time_filter="monsoon",
            confidence=0.7,
        )

        with patch("floatchat.api.routes.LLMEntityExtractor") as MockExtractor:
            instance = MockExtractor.return_value
            instance.extract.return_value = mock_spec
            result = _try_llm_extraction_as_recovery(
                "temperature in Arabian Sea during monsoon", None, mgr,
            )

        assert result is not None
        # Variables must NOT come from LLM
        assert result.variables == []
        # But region and temporal ARE accepted
        assert result.region == "arabian_sea"
        assert result.year is not None


class TestDeterministicSeasonDetection:
    """Priority 3 fix: The regex parser now detects season tokens deterministically.

    This avoids the need for LLM extraction entirely for common patterns like
    "during monsoon", "last monsoon", "next winter", etc.
    """

    def test_during_monsoon_sets_year(self) -> None:
        """'temperature in Arabian Sea during monsoon' → year=current year."""
        from floatchat.intent_parser.regex import RegexIntentParser
        parser = RegexIntentParser()
        parsed = parser.parse("temperature in Arabian Sea during monsoon")
        assert parsed.year is not None
        assert parsed.year == date.today().year
        assert parsed.variables == ["TEMP"]
        assert parsed.region == "arabian_sea"

    def test_last_monsoon_sets_year(self) -> None:
        """'oxygen in Bay of Bengal last monsoon' → year=current year - 1."""
        from floatchat.intent_parser.regex import RegexIntentParser
        parser = RegexIntentParser()
        parsed = parser.parse("oxygen in Bay of Bengal last monsoon")
        assert parsed.year == date.today().year - 1
        assert parsed.variables == ["DOXY"]
        assert parsed.region == "bay_of_bengal"

    def test_next_winter_sets_year(self) -> None:
        """'salinity in Arabian Sea next winter' → year=current year + 1."""
        from floatchat.intent_parser.regex import RegexIntentParser
        parser = RegexIntentParser()
        parsed = parser.parse("salinity in Arabian Sea next winter")
        assert parsed.year == date.today().year + 1

    def test_during_pre_monsoon_sets_year(self) -> None:
        """'chlorophyll in Bay of Bengal during pre-monsoon' → year=current year."""
        from floatchat.intent_parser.regex import RegexIntentParser
        parser = RegexIntentParser()
        parsed = parser.parse("chlorophyll in Bay of Bengal during pre-monsoon")
        assert parsed.year == date.today().year
        assert parsed.variables == ["CHLA"]

    def test_bare_year_takes_precedence_over_season(self) -> None:
        """'temperature during monsoon 2024' → year=2024 (explicit year wins)."""
        from floatchat.intent_parser.regex import RegexIntentParser
        parser = RegexIntentParser()
        parsed = parser.parse("temperature during monsoon 2024")
        assert parsed.year == 2024

    def test_past_monsoon_sets_year(self) -> None:
        """'oxygen past monsoon' → year=current year - 1."""
        from floatchat.intent_parser.regex import RegexIntentParser
        parser = RegexIntentParser()
        parsed = parser.parse("oxygen in Arabian Sea past monsoon")
        assert parsed.year == date.today().year - 1

    def test_this_monsoon_sets_year(self) -> None:
        """'temperature this monsoon' → year=current year."""
        from floatchat.intent_parser.regex import RegexIntentParser
        parser = RegexIntentParser()
        parsed = parser.parse("temperature in Bay of Bengal this monsoon")
        assert parsed.year == date.today().year

    def test_season_month_extraction_monsoon(self) -> None:
        """'during monsoon' → month=6 (June)."""
        from floatchat.intent_parser.regex import RegexIntentParser
        parser = RegexIntentParser()
        parsed = parser.parse("temperature in Arabian Sea during monsoon")
        assert parsed.month == 6

    def test_season_month_extraction_winter(self) -> None:
        """'during winter' → month=12 (December)."""
        from floatchat.intent_parser.regex import RegexIntentParser
        parser = RegexIntentParser()
        parsed = parser.parse("temperature in Arabian Sea during winter")
        assert parsed.month == 12

    def test_no_season_month_when_explicit_year(self) -> None:
        """'temperature in Arabian Sea 2024' → month=None (no season)."""
        from floatchat.intent_parser.regex import RegexIntentParser
        parser = RegexIntentParser()
        parsed = parser.parse("temperature in Arabian Sea 2024")
        assert parsed.month is None
