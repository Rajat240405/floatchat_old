"""Bug Fix Sprint 1 (Bug 4b) — region_search map marker union.

The DataFrame for a region query is profile-capped (data_lake_max_profiles)
so the figure stays plottable, but the map must show EVERY matching float.
The executor unions the uncapped ``lake.get_map_markers(criteria)`` result
with the df-derived markers.
"""

from datetime import datetime
from unittest.mock import MagicMock

import pandas as pd

from floatchat.data_lake.base import LakeQueryResult
from floatchat.models import ChatResponse, ParsedIntent
from floatchat.query_engine.engine import QueryEngine


def _levels_df(float_ids: list[str]) -> pd.DataFrame:
    rows = []
    for i, fid in enumerate(float_ids):
        for level in range(3):
            rows.append({
                "float_id": fid,
                "cycle_number": 1,
                "date": datetime(2024, 3, 15),
                "year": 2024,
                "month": 3,
                "lat": 15.0 + i,
                "lon": 65.0 + i,
                "data_mode": "D",
                "pressure": float(level * 100),
                "temp": 28.0 - level,
                "region_tag": "arabian_sea",
                "dac": "incois",
            })
    return pd.DataFrame(rows)


def _make_engine_and_lake(df_floats: list[str], marker_floats: list[str]):
    df = _levels_df(df_floats)
    lake_result = LakeQueryResult(
        df=df,
        stats={},
        unique_floats=len(df_floats),
        unique_profiles=len(df_floats),
        total_measurements=len(df),
        has_data=True,
        source="test",
    )
    lake = MagicMock()
    lake.is_available = MagicMock(return_value=True)
    lake.is_phase2_available = MagicMock(return_value=False)
    lake.query = MagicMock(return_value=lake_result)
    lake.get_float_registry = MagicMock(return_value=pd.DataFrame())
    lake.get_map_markers = MagicMock(return_value=[
        {
            "float_id": fid,
            "lat": 15.0 + i,
            "lon": 65.0 + i,
            "profile_date": "2024-03-15",
            "dac": "incois",
        }
        for i, fid in enumerate(marker_floats)
    ])

    viz = MagicMock()
    viz.render = MagicMock(return_value={"data": [], "layout": {}})
    engine = QueryEngine(MagicMock(), MagicMock(), MagicMock(), viz)
    engine._data_lake = lake
    return engine, lake


class TestRegionSearchMarkerUnion:
    def test_uncapped_markers_unioned_into_map(self) -> None:
        # df carries 3 floats; the lake reports 5 matching floats overall.
        engine, lake = _make_engine_and_lake(
            df_floats=["6900001", "6900002", "6900003"],
            marker_floats=["6900001", "6900002", "6900003", "6900004", "6900005"],
        )
        intent = ParsedIntent(
            intent="region_search", region="arabian_sea", variables=["TEMP"], year=2024
        )
        response = engine.execute(intent)

        assert isinstance(response, ChatResponse)
        lake.get_map_markers.assert_called_once()
        fids = sorted(m.float_id for m in response.map_data)
        assert fids == ["6900001", "6900002", "6900003", "6900004", "6900005"]

        # union-added markers carry the requested region tag + wmo id
        added = {m.float_id: m for m in response.map_data if m.float_id in {"6900004", "6900005"}}
        assert all(m.region_tag == "arabian_sea" for m in added.values())
        assert all(m.wmo_id == fid for fid, m in added.items())

        # the message must describe the whole match set, not one float
        assert "3 floats" in response.message or "floats in Arabian Sea" in response.message

    def test_profile_plot_does_not_query_uncapped_markers(self) -> None:
        engine, lake = _make_engine_and_lake(
            df_floats=["6900001"], marker_floats=["6900001", "6900004"],
        )
        intent = ParsedIntent(intent="profile_plot", variables=["TEMP"], float_id="6900001")
        response = engine.execute(intent)

        lake.get_map_markers.assert_not_called()
        assert [m.float_id for m in response.map_data] == ["6900001"]

    def test_broken_marker_query_does_not_fail_region_search(self) -> None:
        engine, lake = _make_engine_and_lake(
            df_floats=["6900001"], marker_floats=["6900001"],
        )
        lake.get_map_markers = MagicMock(side_effect=RuntimeError("duckdb exploded"))
        intent = ParsedIntent(
            intent="region_search", region="arabian_sea", variables=["TEMP"], year=2024
        )
        response = engine.execute(intent)

        assert isinstance(response, ChatResponse)
        assert [m.float_id for m in response.map_data] == ["6900001"]
