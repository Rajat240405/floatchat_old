"""Tests for DuckDBDataLake (Phase 1 walking skeleton)."""

from __future__ import annotations

import pathlib

import tempfile
from datetime import date

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from floatchat.data_lake.base import LakeQueryCriteria
from floatchat.data_lake.duckdb_lake import DuckDBDataLake, build_region_tag


class TestBuildRegionTag:
    """Unit tests for region tag classification."""

    def test_arabian_sea_inside(self) -> None:
        # Typical Arabian Sea location
        assert build_region_tag(15.0, 65.0) == "arabian_sea"

    def test_bay_of_bengal_inside(self) -> None:
        # Typical Bay of Bengal location
        assert build_region_tag(15.0, 88.0) == "bay_of_bengal"

    def test_outside_india(self) -> None:
        # Mid-Atlantic
        assert build_region_tag(30.0, -40.0) is None
        # North Pacific
        assert build_region_tag(50.0, -150.0) is None


class TestDuckDBDataLake:
    """Integration tests for DuckDBDataLake with synthetic Parquet data."""

    @pytest.fixture
    def lake_root(self, tmp_path: pathlib.Path) -> pathlib.Path:
        """Create a temporary Parquet lake with synthetic India Ocean data."""
        root = tmp_path / "parquet_lake"
        root.mkdir()

        # Create synthetic Argo-level data covering both regions
        rows = [
            # Arabian Sea float
            {"float_id": "6900001", "cycle_number": 1, "date": date(2024, 3, 15),
             "year": 2024, "month": 3, "lat": 15.0, "lon": 65.0,
             "data_mode": "D", "pressure": 10.0,
             "temp": 28.0, "temp_qc": "1", "temp_adjusted": 28.1,
             "psal": 35.5, "psal_qc": "1", "psal_adjusted": 35.5,
             "doxy": 200.0, "doxy_qc": "1", "doxy_adjusted": 201.0,
             "chla": 0.5, "chla_qc": "1", "chla_adjusted": 0.5,
             "region_tag": "arabian_sea", "source_file": "coriolis/6900001/profiles/BR6900001_001.nc",
             "dac": "coriolis"},
            {"float_id": "6900001", "cycle_number": 1, "date": date(2024, 3, 15),
             "year": 2024, "month": 3, "lat": 15.0, "lon": 65.0,
             "data_mode": "D", "pressure": 100.0,
             "temp": 20.0, "temp_qc": "1", "temp_adjusted": 20.1,
             "psal": 35.8, "psal_qc": "1", "psal_adjusted": 35.8,
             "doxy": 150.0, "doxy_qc": "1", "doxy_adjusted": 151.0,
             "chla": 0.1, "chla_qc": "1", "chla_adjusted": 0.1,
             "region_tag": "arabian_sea", "source_file": "coriolis/6900001/profiles/BR6900001_001.nc",
             "dac": "coriolis"},
            # Bay of Bengal float
            {"float_id": "2900001", "cycle_number": 2, "date": date(2024, 3, 20),
             "year": 2024, "month": 3, "lat": 12.0, "lon": 87.0,
             "data_mode": "R", "pressure": 10.0,
             "temp": 29.0, "temp_qc": "1", "temp_adjusted": None,
             "psal": 33.0, "psal_qc": "1", "psal_adjusted": None,
             "doxy": 210.0, "doxy_qc": "2", "doxy_adjusted": None,
             "chla": 0.8, "chla_qc": "1", "chla_adjusted": 0.8,
             "region_tag": "bay_of_bengal", "source_file": "incois/2900001/profiles/BR2900001_002.nc",
             "dac": "incois"},
            # Outside region (should be filtered by query)
            {"float_id": "7900001", "cycle_number": 3, "date": date(2024, 4, 1),
             "year": 2024, "month": 4, "lat": 50.0, "lon": -30.0,
             "data_mode": "D", "pressure": 10.0,
             "temp": 10.0, "temp_qc": "1", "temp_adjusted": 10.1,
             "psal": 35.0, "psal_qc": "1", "psal_adjusted": 35.0,
             "doxy": 300.0, "doxy_qc": "1", "doxy_adjusted": 301.0,
             "chla": 0.2, "chla_qc": "1", "chla_adjusted": 0.2,
             "region_tag": None, "source_file": "coriolis/7900001/profiles/BR7900001_003.nc",
             "dac": "coriolis"},
        ]

        df = pd.DataFrame(rows)

        # Write partitioned Parquet
        table = pa.Table.from_pandas(df, preserve_index=False)
        pq.write_to_dataset(
            table,
            root_path=str(root),
            partition_cols=["year", "month"],
            compression="snappy",
        )

        return root

    def test_is_available_with_valid_lake(self, lake_root: pathlib.Path) -> None:
        lake = DuckDBDataLake(lake_root=lake_root)
        assert lake.is_available() is True

    def test_is_available_with_empty_dir(self, tmp_path: pytest.TempPathFactory) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        lake = DuckDBDataLake(lake_root=empty)
        assert lake.is_available() is False

    def test_list_available_years(self, lake_root: pytest.TempPathFactory) -> None:
        lake = DuckDBDataLake(lake_root=lake_root)
        years = lake.list_available_years()
        assert 2024 in years

    def test_query_returns_data_for_arabian_sea(
        self, lake_root: pytest.TempPathFactory
    ) -> None:
        lake = DuckDBDataLake(lake_root=lake_root)
        criteria = LakeQueryCriteria(region="arabian_sea", variables=["TEMP"])
        result = lake.query(criteria)

        assert result.has_data is True
        assert result.total_measurements >= 2
        assert result.unique_floats >= 1
        assert "TEMP" in result.stats

    def test_query_filters_by_region(
        self, lake_root: pytest.TempPathFactory
    ) -> None:
        lake = DuckDBDataLake(lake_root=lake_root)

        # Arabian Sea only
        result_as = lake.query(LakeQueryCriteria(region="arabian_sea"))
        assert all(
            lat >= 0 and lon >= 45 and lon <= 80
            for lat, lon in zip(result_as.df["lat"], result_as.df["lon"])
        )

        # Bay of Bengal only
        result_bob = lake.query(LakeQueryCriteria(region="bay_of_bengal"))
        assert all(
            lat >= 0 and lon >= 78 and lon <= 100
            for lat, lon in zip(result_bob.df["lat"], result_bob.df["lon"])
        )

    def test_query_filters_by_year_month(
        self, lake_root: pytest.TempPathFactory
    ) -> None:
        lake = DuckDBDataLake(lake_root=lake_root)
        result = lake.query(LakeQueryCriteria(year=2024, month=3))
        assert result.has_data is True
        assert result.total_measurements >= 3

        # April should only have 1 record (the outside region one)
        result_apr = lake.query(LakeQueryCriteria(year=2024, month=4))
        # April is filtered out because it's outside India region
        assert result_apr.total_measurements <= 1

    def test_query_filters_by_variable(
        self, lake_root: pytest.TempPathFactory
    ) -> None:
        lake = DuckDBDataLake(lake_root=lake_root)
        result = lake.query(LakeQueryCriteria(variables=["DOXY"]))
        assert result.has_data is True
        assert "DOXY" in result.stats

    def test_query_returns_empty_for_no_match(
        self, lake_root: pytest.TempPathFactory
    ) -> None:
        lake = DuckDBDataLake(lake_root=lake_root)
        result = lake.query(LakeQueryCriteria(year=1990))
        assert result.has_data is False
        assert result.df.empty

    def test_stats_computed_correctly(
        self, lake_root: pytest.TempPathFactory
    ) -> None:
        lake = DuckDBDataLake(lake_root=lake_root)
        criteria = LakeQueryCriteria(region="arabian_sea", variables=["TEMP"])
        result = lake.query(criteria)

        assert "TEMP" in result.stats
        stats = result.stats["TEMP"]
        assert "n_obs" in stats
        assert stats["n_obs"] >= 2
        assert "units" in stats
        assert stats["units"] == "degree_Celsius"

    def test_get_region_tag(self, lake_root: pytest.TempPathFactory) -> None:
        lake = DuckDBDataLake(lake_root=lake_root)
        assert lake.get_region_tag(15.0, 65.0) == "arabian_sea"
        assert lake.get_region_tag(15.0, 88.0) == "bay_of_bengal"
        assert lake.get_region_tag(50.0, -30.0) is None

    def test_query_nearest_float(self, lake_root: pathlib.Path) -> None:
        lake = DuckDBDataLake(lake_root=lake_root)
        # Search near (15.1, 65.1) — Arabian sea float 6900001 is at (15.0, 65.0)
        df = lake.query_nearest_float(lat=15.1, lon=65.1, limit=2)
        assert not df.empty
        top = df.iloc[0]
        assert str(top["float_id"]) == "6900001"
        assert "distance_km" in df.columns
        assert top["distance_km"] < 50.0

    def test_query_radius_search(self, lake_root: pathlib.Path) -> None:
        lake = DuckDBDataLake(lake_root=lake_root)
        # Search within 200 km of (15.0, 65.0)
        df = lake.query_radius_search(lat=15.0, lon=65.0, radius_km=200.0)
        assert not df.empty
        fids = [str(fid) for fid in df["float_id"]]
        assert "6900001" in fids
        assert "2900001" not in fids  # 2900001 is far in Bay of Bengal

    def test_query_metadata_lookup(self, lake_root: pathlib.Path) -> None:
        lake = DuckDBDataLake(lake_root=lake_root)
        info = lake.query_metadata_lookup("6900001")
        assert info["float_id"] == "6900001"
        assert info["found"] is True

    def test_query_count_aggregate(self, lake_root: pathlib.Path) -> None:
        lake = DuckDBDataLake(lake_root=lake_root)
        res = lake.query_count_aggregate(region="arabian_sea", year=2024)
        assert res["has_data"] is True
        assert res["total_profiles"] >= 1
        assert res["total_floats"] >= 1
