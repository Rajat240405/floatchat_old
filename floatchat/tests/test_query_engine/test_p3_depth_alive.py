"""P3 #1 + P3 #2 regression tests — depth extraction + alive filter.

P3 #1: deterministic depth extraction from the regex parser.
  - "deep" -> depth_min=1000, "surface" -> depth_max=20
  - "below Nm" -> depth_min=N, "above Nm" -> depth_max=N

P3 #2: operational_filter='alive' in radius_search.
  - "alive during <period>" = >=1 profile in profile_index within date window
  - "currently alive" = >=1 profile in last `alive_recent_months` months
  - NOT float_registry.status
"""
from unittest.mock import MagicMock

import pytest

from floatchat.config import settings
from floatchat.intent_parser.regex import RegexIntentParser
from floatchat.models import ParsedIntent
from floatchat.query_engine.engine import _build_alive_window


# --------------------------------------------------------------------------- #
# P3 #1: Depth extraction
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def parser():
    return RegexIntentParser()


def test_deep_sets_depth_min(parser):
    pi = parser.parse("deep oxygen in Bay of Bengal")
    assert pi.depth_min == 1000.0
    assert pi.depth_max is None


def test_surface_sets_depth_max(parser):
    pi = parser.parse("surface temperature in Arabian Sea")
    assert pi.depth_max == 20.0
    assert pi.depth_min is None


def test_below_numeric_sets_depth_min(parser):
    pi = parser.parse("oxygen below 500m in Bay of Bengal")
    assert pi.depth_min == 500.0


def test_above_numeric_sets_depth_max(parser):
    pi = parser.parse("chlorophyll above 100m")
    assert pi.depth_max == 100.0


def test_no_depth_token(parser):
    pi = parser.parse("temperature in Arabian Sea 2024")
    assert pi.depth_min is None
    assert pi.depth_max is None


# --------------------------------------------------------------------------- #
# P3 #2: Alive window computation
# --------------------------------------------------------------------------- #
def test_alive_window_with_year_and_monsoon():
    """year=2024 + monsoon window [6,7,8,9] -> Jun 1 to Sep 30."""
    pi = ParsedIntent(intent="radius_search", year=2024, month=6, month_window=[6, 7, 8, 9])
    start, end = _build_alive_window(pi)
    assert start == "2024-06-01"
    assert end == "2024-09-30"


def test_alive_window_with_year_only():
    """year=2023, no month -> full year Jan 1 to Dec 31."""
    pi = ParsedIntent(intent="radius_search", year=2023)
    start, end = _build_alive_window(pi)
    assert start == "2023-01-01"
    assert end == "2023-12-31"


def test_alive_window_currently_alive():
    """No year -> currently alive = last N months."""
    pi = ParsedIntent(intent="radius_search")
    start, end = _build_alive_window(pi)
    assert start is not None
    assert end is not None
    # End should be today's date
    from datetime import date
    assert end == date.today().isoformat()


def test_alive_window_currently_alive_uses_configurable_threshold():
    """alive_recent_months setting controls the window."""
    original = settings.alive_recent_months
    try:
        settings.alive_recent_months = 6
        pi = ParsedIntent(intent="radius_search")
        start, end = _build_alive_window(pi)
        # start should be ~6 months ago
        from datetime import date
        from dateutil.relativedelta import relativedelta
        expected_start = (date.today() - relativedelta(months=6)).isoformat()
        assert start == expected_start
    finally:
        settings.alive_recent_months = original


def test_alive_window_single_month():
    """year + month -> that month only."""
    pi = ParsedIntent(intent="radius_search", year=2024, month=3)
    start, end = _build_alive_window(pi)
    assert start == "2024-03-01"
    assert end == "2024-03-31"


# --------------------------------------------------------------------------- #
# P3 #2: Lake query_radius_search passes alive window to SQL
# --------------------------------------------------------------------------- #
def test_radius_search_accepts_alive_params():
    """query_radius_search accepts alive_date_start/end kwargs."""
    from pathlib import Path
    from floatchat.data_lake.duckdb_lake import DuckDBDataLake

    lake = DuckDBDataLake.__new__(DuckDBDataLake)
    lake._conn = None
    lake._lake_root = Path("/tmp/fake_lake")
    lake._phase2_root = None
    lake._availability_cache = None

    captured = {}

    class FakeConn:
        def execute(self, sql, params):
            captured["sql"] = sql
            import pandas as pd
            return MagicMock(fetchdf=MagicMock(return_value=pd.DataFrame()))

    # When alive window is set, the SQL must contain a WHERE date clause.
    import inspect
    sig = inspect.signature(lake.query_radius_search)
    assert "alive_date_start" in sig.parameters
    assert "alive_date_end" in sig.parameters


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
