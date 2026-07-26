"""Bug Fix Sprint 1 (Bug 8) — Plotly subplot grid must render at any var count.

Plotly requires ``vertical_spacing <= 1/(rows - 1)``. With a fixed 0.18
spacing, grids beyond 6 rows (~20 plottable variables) raised
"Vertical spacing cannot be greater than ...". The nominal spacing is now
clamped per grid size, and the empty-variables column fallback excludes
identifier/coordinate/time columns so they are never plotted as variables.
"""

import numpy as np
import pandas as pd

from floatchat.models import ParsedIntent
from floatchat.visualization_engine.profile import ProfileVisualizationEngine


def _base_df(n: int = 50) -> pd.DataFrame:
    return pd.DataFrame({
        "PRES": np.linspace(0, 2000, n),
        "TEMP": np.linspace(28, 2, n),
        "PSAL": np.linspace(35.5, 34.0, n),
        "float_id": [1901897] * n,
        "cycle_number": [205] * n,
        "year": [2023] * n,
        "month": [5] * n,
        "lat": [15.0] * n,
        "lon": [65.0] * n,
    })


class TestSubplotSpacingClamp:
    def test_many_variables_render(self) -> None:
        # 22 plottable variables -> 8 rows; pre-fix this raised ValueError.
        df = _base_df()
        variables = []
        for i in range(20):
            col = f"VAR{i}"
            df[col] = np.linspace(1.0, 100.0, len(df))
            variables.append(col)
        variables += ["TEMP", "PSAL"]

        viz = ProfileVisualizationEngine()
        fig = viz.render(ParsedIntent(intent="profile_plot", variables=variables), df)

        assert fig is not None
        assert len(fig["layout"]["annotations"]) == 22

    def test_seven_row_grid_boundary(self) -> None:
        # 19 variables -> 7 rows: the exact boundary that first exceeded 0.18.
        df = _base_df()
        variables = []
        for i in range(17):
            col = f"VAR{i}"
            df[col] = np.linspace(1.0, 100.0, len(df))
            variables.append(col)
        variables += ["TEMP", "PSAL"]

        viz = ProfileVisualizationEngine()
        fig = viz.render(ParsedIntent(intent="profile_plot", variables=variables), df)
        assert fig is not None


class TestEmptyVariablesColumnFallback:
    def test_identifier_columns_not_plotted(self) -> None:
        df = _base_df()
        viz = ProfileVisualizationEngine()
        fig = viz.render(ParsedIntent(intent="profile_plot", variables=[]), df)

        titles = [a["text"] for a in fig["layout"]["annotations"]]
        # only the two measurement variables may appear —
        # float_id / cycle_number / year / month / lat / lon must be excluded
        assert len(titles) == 2
        for junk in ("float_id", "cycle_number", "year", "month", "lat", "lon"):
            assert not any(junk in t for t in titles)
