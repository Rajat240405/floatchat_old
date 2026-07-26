"""Bug Fix Sprint 1 (Bug 6) — region_month_stats schema guard + pytz dependency.

The count fast path blind-referenced ``profile_count``/``float_count`` in the
region_month_stats aggregate table. Lakes built by older ETL versions store
different column names, so DuckDB raised a binder error ("Referenced column
profile_count not found") which was swallowed, and — with pytz missing in the
deployment environment (needed by duckdb-python for TIMESTAMPTZ conversion) —
the profile_index fallback failed too, surfacing as a zero count. The fast
path is now schema-verified before use, and pytz is a declared dependency.
"""

import logging
from pathlib import Path

import pandas as pd
import pytest

from floatchat.data_lake.duckdb_lake import DuckDBDataLake


def _write_phase2_lake(root: Path, rms_columns: dict) -> Path:
    rms_dir = root / "parquet" / "region_month_stats"
    pi_dir = root / "parquet" / "profile_index"
    (root / "parquet" / "levels").mkdir(parents=True)
    rms_dir.mkdir(parents=True)
    pi_dir.mkdir(parents=True)

    pd.DataFrame(rms_columns).to_parquet(rms_dir / "rms.parquet", index=False)

    profile_index = pd.DataFrame({
        "float_id": [2902403, 2902403, 2902404],
        "cycle_number": [1, 2, 1],
        "latitude": [15.0, 15.1, 16.0],
        "longitude": [65.0, 65.1, 66.0],
        "date": pd.to_datetime(["2023-01-01", "2023-02-01", "2023-03-01"], utc=True),
        "region_tag": ["arabian_sea"] * 3,
        "year": [2023] * 3,
        "month": [1, 2, 3],
        "dac": ["incois"] * 3,
    })
    profile_index.to_parquet(pi_dir / "pi.parquet", index=False)
    return root


class TestRegionMonthStatsSchemaGuard:
    def test_wrong_schema_falls_back_to_profile_index(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        # user's lake shape: region_month_stats without profile_count/float_count
        _write_phase2_lake(tmp_path, {
            "region_tag": ["arabian_sea"] * 3,
            "year": [2023] * 3,
            "month": [1, 2, 3],
            "profiles": [10, 20, 30],
            "floats": [5, 6, 7],
        })
        lake = DuckDBDataLake(phase2_root=tmp_path, use_phase2=True)
        with caplog.at_level(logging.INFO):
            out = lake.query_count_aggregate(region="arabian_sea")

        assert out["total_profiles"] == 3
        assert out["total_floats"] == 2
        assert out["has_data"] is True
        assert "fast path skipped" in caplog.text

    def test_correct_schema_uses_fast_path(self, tmp_path: Path) -> None:
        _write_phase2_lake(tmp_path, {
            "region_tag": ["arabian_sea"] * 2,
            "year": [2023] * 2,
            "month": [1, 2],
            "profile_count": [10, 20],
            "float_count": [5, 6],
        })
        lake = DuckDBDataLake(phase2_root=tmp_path, use_phase2=True)
        out = lake.query_count_aggregate(region="arabian_sea")

        # values come from region_month_stats (30/6), NOT profile_index (3/2)
        assert out["total_profiles"] == 30
        assert out["total_floats"] == 6

    def test_empty_region_month_stats_dir_falls_back(self, tmp_path: Path) -> None:
        _write_phase2_lake(tmp_path, {
            "region_tag": ["arabian_sea"],
            "year": [2023],
            "month": [1],
            "profile_count": [10],
            "float_count": [5],
        })
        (tmp_path / "parquet" / "region_month_stats" / "rms.parquet").unlink()
        lake = DuckDBDataLake(phase2_root=tmp_path, use_phase2=True)
        out = lake.query_count_aggregate(region="arabian_sea")

        assert out["total_profiles"] == 3
        assert out["total_floats"] == 2


class TestDeclaredDependencies:
    def test_pytz_is_a_declared_dependency(self) -> None:
        pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
        content = pyproject.read_text(encoding="utf-8")
        assert any(
            line.strip().startswith('"pytz') for line in content.splitlines()
        ), "pytz must be declared in pyproject dependencies (duckdb TIMESTAMPTZ)"
