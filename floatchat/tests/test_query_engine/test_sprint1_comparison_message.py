"""Bug Fix Sprint 1 (Bug 7) — comparison message must name all floats.

The deterministic comparison pipeline (parser -> planner -> executor -> viz)
already preserves and plots both floats; the defect was the response message
naming only the primary float_id, so a comparison read as a single-float
profile — especially when one requested float returned no data.
"""

from datetime import datetime
from unittest.mock import MagicMock

import pandas as pd

from floatchat.data_lake.base import LakeQueryResult
from floatchat.models import ParsedIntent
from floatchat.query_engine.engine import QueryEngine


def _df_for_fid(fid: str) -> pd.DataFrame:
    return pd.DataFrame({
        "float_id": [fid] * 3,
        "cycle_number": [1] * 3,
        "date": [datetime(2024, 3, 15)] * 3,
        "year": [2024] * 3,
        "month": [3] * 3,
        "lat": [15.0] * 3,
        "lon": [65.0] * 3,
        "data_mode": ["D"] * 3,
        "pressure": [0.0, 100.0, 200.0],
        "temp": [28.0, 20.0, 12.0],
        "region_tag": ["arabian_sea"] * 3,
        "dac": ["incois"] * 3,
    })


def _make_engine(with_data: dict[str, bool]):
    def _query_side_effect(criteria):
        fid = str(criteria.float_id)
        if with_data.get(fid, True):
            df = _df_for_fid(fid)
            return LakeQueryResult(
                df=df, stats={}, unique_floats=1, unique_profiles=1,
                total_measurements=len(df), has_data=True, source="test",
            )
        return LakeQueryResult(
            df=pd.DataFrame(), stats={}, unique_floats=0, unique_profiles=0,
            total_measurements=0, has_data=False, source="test",
        )

    lake = MagicMock()
    lake.is_available = MagicMock(return_value=True)
    lake.is_phase2_available = MagicMock(return_value=False)
    lake.query = MagicMock(side_effect=_query_side_effect)
    lake.get_float_registry = MagicMock(return_value=pd.DataFrame())
    lake.get_map_markers = MagicMock(return_value=[])
    # LakeQueryResult.source must be a string for the executor's logging
    lake._lake_root = MagicMock()
    lake._lake_root.as_posix = MagicMock(return_value="test")

    viz = MagicMock()
    viz.render = MagicMock(return_value={"data": [], "layout": {}})
    engine = QueryEngine(MagicMock(), MagicMock(), MagicMock(), viz)
    engine._data_lake = lake
    return engine, lake


class TestComparisonMessage:
    def test_two_floats_both_named(self) -> None:
        engine, _ = _make_engine({"1111111": True, "2222222": True})
        intent = ParsedIntent(
            intent="comparison_plot",
            variables=["TEMP"],
            float_id="1111111",
            comparison_float_ids=["1111111", "2222222"],
        )
        response = engine.execute(intent)

        assert "Floats 1111111, 2222222" in response.message
        assert "No matching data was found for" not in response.message

    def test_missing_float_disclosed(self) -> None:
        engine, _ = _make_engine({"3902490": True, "2903885": False})
        intent = ParsedIntent(
            intent="comparison_plot",
            variables=["TEMP"],
            float_id="2903885",
            comparison_float_ids=["2903885", "3902490"],
        )
        response = engine.execute(intent)

        assert "Floats 3902490" in response.message
        assert "No matching TEMP data was found for: 2903885." in response.message

    def test_engine_receives_both_float_queries(self) -> None:
        engine, lake = _make_engine({"1111111": True, "2222222": True})
        intent = ParsedIntent(
            intent="comparison_plot",
            variables=["TEMP"],
            float_id="1111111",
            comparison_float_ids=["1111111", "2222222"],
        )
        engine.execute(intent)

        queried_fids = sorted(str(c.kwargs.get("float_id") or (c.args[0].float_id if c.args else ""))
                              for c in lake.query.call_args_list)
        assert queried_fids == ["1111111", "2222222"]
