"""P2 regression tests — LLM extractor reliability + provider toggle.

Covers the code-DESIGN fixes (model-independent, asserted with mocked
extractors) that close the gaps the qwen2.5:0.5b model exposed in production:

  1. Region is never injected from the LLM when coordinates are already set
     (the "bay_of_bengal" pollution on "floats near Sri Lanka").
  2. Placeholder time_filter values ("year", "time", ">=") are ignored at the
     merge step (hard filter, not just a warning).
  3. Structural-confidence override is tightened: a lone operational_filter or
     a placeholder time_filter is NOT meaningful → extraction discarded even at
     high self-reported confidence.
  4. Dedupe: an intent produced by the recovery LLM call is not re-sent to the
     LLM by _try_llm_extraction (the duplicate ~4s call from query #7).

The MODEL-quality question (would a stronger model avoid these?) is answered
by the real-machine A/B harness (compare_providers.py), not here.
"""
import json
from unittest.mock import MagicMock, patch

import pytest

from floatchat.api.routes import (
    _try_llm_extraction,
    _try_llm_extraction_as_recovery,
)
from floatchat.conversation.memory import InMemoryConversationManager
from floatchat.entity_extractor.extractor import (
    LLMEntityExtractor,
    _is_placeholder_time_filter,
)
from floatchat.entity_extractor.query_spec import QuerySpec
from floatchat.models import ParsedIntent


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
def _patch_extractor_with(specs):
    """Patch routes-level LLMEntityExtractor to return *specs* in order."""
    iterator = iter(specs)

    def _factory():
        inst = MagicMock()
        inst.extract.side_effect = lambda **kw: next(iterator, None)
        return inst

    return patch("floatchat.api.routes.LLMEntityExtractor", side_effect=_factory)


def _patch_no_extractor_call():
    """Patch LLMEntityExtractor but assert extract() is NEVER called."""
    def _factory():
        inst = MagicMock()
        inst.extract.side_effect = AssertionError(
            "LLM extract() should NOT have been called (dedupe failed)"
        )
        return inst

    return patch("floatchat.api.routes.LLMEntityExtractor", side_effect=_factory)


# --------------------------------------------------------------------------- #
# P2 #2 — region guard
# --------------------------------------------------------------------------- #
def test_region_not_injected_when_coords_present():
    """Lat/lon already resolved (gazetteer) → LLM's hallucinated region is ignored."""
    cm = InMemoryConversationManager()
    # Coordinates already present (as if gazetteer resolved "Sri Lanka").
    parsed = ParsedIntent(
        intent="radius_search",
        lat=7.87, lon=80.77, radius_km=500.0,
        region=None,
    )
    spec = QuerySpec(
        action="radius_search", spatial_filter="bay_of_bengal",
        confidence=1.0,  # the model is "sure" — must still be ignored
    )
    with _patch_extractor_with([spec]):
        result = _try_llm_extraction("show floats near Sri Lanka", parsed, None, cm)
    assert result.lat == 7.87 and result.lon == 80.77
    assert result.region is None, "LLM region must not override resolved coords"


def test_region_injected_when_no_coords():
    """Without coordinates, a region from the LLM is still accepted."""
    cm = InMemoryConversationManager()
    parsed = ParsedIntent(intent="region_search")
    spec = QuerySpec(action="region_search", spatial_filter="arabian_sea", confidence=0.9)
    with _patch_extractor_with([spec]):
        result = _try_llm_extraction("conditions in arabian", parsed, None, cm)
    assert result.region == "arabian_sea"


# --------------------------------------------------------------------------- #
# P2 #3 — placeholder time_filter ignored
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("placeholder", ["year", "time", ">=", "current", "now"])
def test_placeholder_time_filter_not_merged(placeholder):
    """Placeholder time_filters never fill the year slot."""
    cm = InMemoryConversationManager()
    parsed = ParsedIntent(intent="region_search", region="arabian_sea", variables=["TEMP"])
    spec = QuerySpec(
        action="region_search", variables=["TEMP"], spatial_filter="arabian_sea",
        time_filter=placeholder, confidence=1.0,
    )
    with _patch_extractor_with([spec]):
        result = _try_llm_extraction("temp in arabian", parsed, None, cm)
    assert result.year is None, f"placeholder {placeholder!r} must not set year"


def test_is_placeholder_time_filter_helper():
    assert _is_placeholder_time_filter("year") is True
    assert _is_placeholder_time_filter(">=") is True
    assert _is_placeholder_time_filter("Time") is True
    assert _is_placeholder_time_filter(None) is True
    assert _is_placeholder_time_filter("2024") is False
    assert _is_placeholder_time_filter("last monsoon") is False
    assert _is_placeholder_time_filter("monsoon") is False


# --------------------------------------------------------------------------- #
# P2 #4 — structural confidence override tightened
# --------------------------------------------------------------------------- #
def test_lone_operational_filter_discarded_even_at_high_confidence():
    """A spec with only operational_filter='active' is meaningless → None."""
    extractor = LLMEntityExtractor()
    mock_response = json.dumps({
        "action": "region_search", "variables": [], "spatial_filter": None,
        "time_filter": None, "float_id": None, "depth_filter": None,
        "operational_filter": "active", "confidence": 1.0,
    })
    with patch.object(extractor, "_call_ollama", return_value=mock_response):
        spec = extractor.extract("chlorophyll in Bay of Bengal")
    assert spec is None, "lone operational_filter must be discarded"


def test_lone_placeholder_time_discarded():
    """A spec with only a placeholder time_filter is meaningless → None."""
    extractor = LLMEntityExtractor()
    mock_response = json.dumps({
        "action": "time_series", "variables": [], "spatial_filter": None,
        "time_filter": "year", "float_id": None, "depth_filter": None,
        "operational_filter": None, "confidence": 1.0,
    })
    with patch.object(extractor, "_call_ollama", return_value=mock_response):
        spec = extractor.extract("salinity trend")
    assert spec is None


def test_operational_filter_kept_when_accompanied_by_meaningful_slot():
    """operational_filter survives when there is also a real place/time."""
    extractor = LLMEntityExtractor()
    mock_response = json.dumps({
        "action": "radius_search", "variables": [], "spatial_filter": "goa",
        "time_filter": "last monsoon", "float_id": None, "depth_filter": None,
        "operational_filter": "alive", "confidence": 0.8,
    })
    with patch.object(extractor, "_call_ollama", return_value=mock_response):
        spec = extractor.extract("alive floats near Goa during last monsoon")
    assert spec is not None
    assert spec.operational_filter == "alive"


# --------------------------------------------------------------------------- #
# P2 dedupe — recovery result skips the second LLM call
# --------------------------------------------------------------------------- #
def test_dedupe_recovery_skips_second_extraction():
    """An intent marked _llm_extracted must not trigger _try_llm_extraction."""
    cm = InMemoryConversationManager()
    # Simulate a ParsedIntent returned by _try_llm_extraction_as_recovery:
    # it already has meaningful content and is marked as LLM-extracted.
    parsed = ParsedIntent(
        intent="radius_search", variables=["DOXY"], region="arabian_sea",
    )
    parsed.__dict__["_llm_extracted"] = True
    parsed.__dict__["operational_filter"] = "alive"

    with _patch_no_extractor_call():
        result = _try_llm_extraction("anything", parsed, "s1", cm)

    assert result is parsed  # returned unchanged


def test_recovery_path_marks_llm_extracted():
    """_try_llm_extraction_as_recovery stamps _llm_extracted=True on its result."""
    cm = InMemoryConversationManager()
    spec = QuerySpec(
        action="radius_search", variables=["DOXY"], spatial_filter="goa",
        operational_filter="alive", confidence=0.9,
    )
    # Force gazetteer to resolve "goa" so the recovery returns a ParsedIntent.
    with patch("floatchat.api.routes.LLMEntityExtractor") as mock_ext, \
         patch("floatchat.intent_parser.gazetteer.resolve_place_name") as mock_gaz:
        mock_ext.return_value.extract.return_value = spec
        mock_gaz.return_value = {"lat": 15.3, "lon": 73.9, "source": "local_gazetteer"}
        result = _try_llm_extraction_as_recovery("alive floats near Goa", None, cm)
    assert result is not None
    assert getattr(result, "_llm_extracted", False) is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
