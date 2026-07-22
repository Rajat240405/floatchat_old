"""P3 #3 regression tests — season month-window resolution.

Verifies that "during monsoon" resolves to the full JJAS window [6,7,8,9]
(not just month=6), and that the window flows from the parser through to the
DuckDB lake SQL as ``month IN (...)`` instead of ``month = ?``.

These definitions are PROVISIONAL — pending scientist confirmation (see
intent_parser/seasons.py). The tests assert the current provisional values; if
a scientist adjusts SEASON_MONTH_WINDOWS, update these expectations to match.
"""
from unittest.mock import MagicMock

import pytest

from floatchat.data_lake.base import LakeQueryCriteria
from floatchat.data_lake.duckdb_lake import DuckDBDataLake, _month_filter
from floatchat.intent_parser.regex import RegexIntentParser
from floatchat.intent_parser.seasons import (
    SEASON_MONTH_WINDOWS,
    detect_season_window,
    season_start_month,
)


# --------------------------------------------------------------------------- #
# Season window definitions (provisional)
# --------------------------------------------------------------------------- #
def test_monsoon_is_jjas():
    """SW monsoon = June–September (JJAS), the headline P3 #3 fix."""
    assert SEASON_MONTH_WINDOWS["monsoon"] == [6, 7, 8, 9]


def test_detect_season_window_monsoon():
    assert detect_season_window("temperature during monsoon") == [6, 7, 8, 9]


def test_detect_season_window_last_monsoon():
    assert detect_season_window("oxygen last monsoon") == [6, 7, 8, 9]


def test_detect_season_window_winter_crosses_year():
    assert detect_season_window("during winter") == [12, 1, 2]


def test_detect_season_window_none_when_no_season():
    assert detect_season_window("temperature 2024") is None


def test_season_start_month():
    assert season_start_month([6, 7, 8, 9]) == 6
    assert season_start_month([12, 1, 2]) == 12
    assert season_start_month(None) is None


# --------------------------------------------------------------------------- #
# Parser end-to-end: month_window is populated
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def parser():
    return RegexIntentParser()


def test_parser_sets_monsoon_window(parser):
    pi = parser.parse("temperature in arabian sea during monsoon")
    assert pi.month_window == [6, 7, 8, 9]
    assert pi.month == 6  # representative start month (backward compat)


def test_parser_sets_last_monsoon_window(parser):
    pi = parser.parse("oxygen in bay of bengal last monsoon")
    assert pi.month_window == [6, 7, 8, 9]


def test_parser_no_window_for_bare_year(parser):
    pi = parser.parse("temperature 2024")
    assert pi.month_window is None


# --------------------------------------------------------------------------- #
# Lake SQL: window → month IN (...), single month → month = ?
# --------------------------------------------------------------------------- #
def test_month_filter_single():
    assert _month_filter(6, None) == ("month = ?", [6])


def test_month_filter_window_takes_precedence():
    cond, params = _month_filter(6, [6, 7, 8, 9])
    assert cond == "month IN (?, ?, ?, ?)"
    assert params == [6, 7, 8, 9]


def test_month_filter_window_only():
    cond, params = _month_filter(None, [12, 1, 2])
    assert cond == "month IN (?, ?, ?)"
    assert params == [12, 1, 2]


def test_month_filter_none():
    assert _month_filter(None, None) is None


def test_month_filter_dedupes_and_clamps():
    cond, params = _month_filter(None, [6, 6, 7, 99, 0, 8, 9])
    assert params == [6, 7, 8, 9]


# --------------------------------------------------------------------------- #
# Lake query: criteria.months is honored in the generated SQL
# --------------------------------------------------------------------------- #
def test_lake_query_uses_month_in_for_window():
    """The generated DuckDB SQL must contain 'month IN' when months is set."""
    from pathlib import Path
    lake = DuckDBDataLake.__new__(DuckDBDataLake)  # bypass __init__ (no FS)
    lake._conn = None
    lake._lake_root = Path("/tmp/fake_lake")
    lake._availability_cache = None
    captured = {}

    class FakeConn:
        def execute(self, sql, params):
            captured["sql"] = sql
            captured["params"] = params
            import pandas as pd
            return MagicMock(fetchdf=MagicMock(return_value=pd.DataFrame()))

    criteria = LakeQueryCriteria(
        region="arabian_sea", year=2024, variables=["TEMP"],
        month=6, months=[6, 7, 8, 9],
    )
    lake._execute_query(criteria, FakeConn())
    assert "month IN" in captured["sql"], "window must produce month IN (...) SQL"
    assert captured["params"][
        captured["params"].index(6): captured["params"].index(9) + 1
    ] == [6, 7, 8, 9]


def test_lake_query_uses_single_month_without_window():
    """Without a window, the SQL must use 'month = ?' (backward compat)."""
    from pathlib import Path
    lake = DuckDBDataLake.__new__(DuckDBDataLake)
    lake._conn = None
    lake._lake_root = Path("/tmp/fake_lake")
    lake._availability_cache = None
    captured = {}

    class FakeConn:
        def execute(self, sql, params):
            captured["sql"] = sql
            captured["params"] = params
            import pandas as pd
            return MagicMock(fetchdf=MagicMock(return_value=pd.DataFrame()))

    criteria = LakeQueryCriteria(
        region="arabian_sea", year=2024, variables=["TEMP"], month=6,
    )
    lake._execute_query(criteria, FakeConn())
    assert "month = ?" in captured["sql"]
    assert "month IN" not in captured["sql"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
