"""Tests for ProfileVisualizationEngine."""

import numpy as np
import pandas as pd
import pytest

from floatchat.exceptions import VisualizationError
from floatchat.models import ParsedIntent
from floatchat.visualization_engine.profile import ProfileVisualizationEngine


class TestProfileVisualizationEngine:
    def _make_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "profile_idx": [0, 0, 0, 1, 1, 1],
                "level_idx": [0, 1, 2, 0, 1, 2],
                "PRES": [2.0, 10.0, 50.0, 2.0, 10.0, 50.0],
                "DOXY": [210.0, 205.0, 190.0, 212.0, 207.0, 192.0],
                "DOXY_QC": ["1", "1", "2", "1", "1", "1"],
            }
        )

    def test_render_profile_plot(self) -> None:
        engine = ProfileVisualizationEngine()
        intent = ParsedIntent(
            intent="profile_plot",
            region="arabian_sea",
            variables=["DOXY"],
            year=2024,
        )
        df = self._make_df()
        fig = engine.render(intent, df)

        assert "data" in fig
        assert "layout" in fig
        assert fig["layout"]["title"]["text"] == "DOXY Profile — Arabian Sea 2024"

    def test_one_trace_per_profile_not_per_point(self) -> None:
        """Regression: QC-aware plots must use one trace per profile,
        not one trace per data point."""
        engine = ProfileVisualizationEngine()
        intent = ParsedIntent(
            intent="profile_plot",
            variables=["DOXY"],
        )
        df = self._make_df()
        fig = engine.render(intent, df)

        # Two profiles → one trace per profile in the first subplot
        traces = [t for t in fig["data"] if t.get("xaxis") == "x"]
        assert len(traces) == 2, f"Expected 2 traces, got {len(traces)}"

        # Each trace should have an array of marker colors, not a single color
        for trace in traces:
            marker = trace.get("marker", {})
            assert isinstance(marker.get("color"), list), (
                "marker.color should be a list (array of rgba strings)"
            )

    def test_empty_dataframe_raises(self) -> None:
        engine = ProfileVisualizationEngine()
        intent = ParsedIntent(intent="profile_plot", variables=["DOXY"])
        with pytest.raises(VisualizationError):
            engine.render(intent, pd.DataFrame())

    def test_missing_pres_raises(self) -> None:
        engine = ProfileVisualizationEngine()
        intent = ParsedIntent(intent="profile_plot", variables=["DOXY"])
        df = pd.DataFrame({"DOXY": [1, 2, 3]})
        with pytest.raises(VisualizationError):
            engine.render(intent, df)

    def test_trajectory_returns_none(self) -> None:
        engine = ProfileVisualizationEngine()
        intent = ParsedIntent(intent="trajectory", float_id="6903091")
        df = self._make_df()
        assert engine.render(intent, df) is None

    def test_time_series_render(self) -> None:
        engine = ProfileVisualizationEngine()
        intent = ParsedIntent(intent="time_series", variables=["DOXY"])
        df = self._make_df()
        df["profile_date"] = ["2024-01-01", "2024-01-01", "2024-01-01", "2024-01-02", "2024-01-02", "2024-01-02"]
        fig = engine.render(intent, df)
        assert fig is not None
        assert "data" in fig
        assert fig["layout"]["xaxis"]["title"]["text"] == "Date"

    def test_hovmoller_render(self) -> None:
        engine = ProfileVisualizationEngine()
        intent = ParsedIntent(intent="hovmoller", variables=["DOXY"])
        df = self._make_df()
        df["profile_date"] = ["2024-01-01", "2024-01-01", "2024-01-01", "2024-01-02", "2024-01-02", "2024-01-02"]
        fig = engine.render(intent, df)
        assert fig is not None
        assert fig["data"][0]["type"] == "heatmap"

    def test_ts_diagram_render(self) -> None:
        engine = ProfileVisualizationEngine()
        intent = ParsedIntent(intent="ts_diagram", variables=["TEMP", "PSAL"])
        df = self._make_df()
        df["TEMP"] = [25.0, 24.0, 20.0, 25.1, 24.1, 20.1]
        df["PSAL"] = [35.0, 35.1, 35.2, 35.0, 35.1, 35.2]
        fig = engine.render(intent, df)
        assert fig is not None
        assert fig["layout"]["xaxis"]["title"]["text"] == "Practical Salinity (PSU)"
        assert fig["layout"]["yaxis"]["title"]["text"] == "Temperature (°C)"

    def test_comparison_render(self) -> None:
        engine = ProfileVisualizationEngine()
        intent = ParsedIntent(intent="comparison", variables=["DOXY"], comparison_float_ids=["101", "102"])
        df = self._make_df()
        df["float_id"] = ["101", "101", "101", "102", "102", "102"]
        fig = engine.render(intent, df)
        assert fig is not None
        assert len(fig["data"]) == 2
