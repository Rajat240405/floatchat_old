"""Tests for GDACMetadataService."""

import gzip
from pathlib import Path

import pandas as pd
import pytest
from pandas import DatetimeTZDtype

from floatchat.exceptions import MetadataError
from floatchat.metadata_service.gdac import GDACMetadataService
from floatchat.models import SearchCriteria


class TestGDACMetadataService:
    def _make_service(self) -> GDACMetadataService:
        svc = GDACMetadataService()
        # Inject a synthetic DataFrame directly to avoid HTTP
        svc._df = pd.DataFrame(
            {
                "file": [
                    "coriolis/6903091/profiles/BR6903091_001.nc",
                    "coriolis/6903091/profiles/BR6903091_002.nc",
                    "aoml/6901234/profiles/BR6901234_001.nc",
                ],
                "date": pd.to_datetime(
                    ["20240115120000", "20240220120000", "20240310120000"],
                    format="%Y%m%d%H%M%S",
                    utc=True,
                ),
                "latitude": [10.5, 11.0, 35.0],
                "longitude": [65.2, 66.0, -40.0],
                "ocean": ["I", "I", "A"],
                "profiler_type": ["846", "846", "845"],
                "institution": ["IF", "IF", "AO"],
                "parameters": [
                    "PRES PSAL TEMP DOXY",
                    "PRES PSAL TEMP DOXY CHLA",
                    "PRES PSAL TEMP",
                ],
                "parameter_data_mode": ["R R R A", "R R R A A", "R R R"],
                "date_update": pd.to_datetime(
                    ["20240116000000", "20240221000000", "20240311000000"],
                    format="%Y%m%d%H%M%S",
                    utc=True,
                ),
            }
        )
        return svc

    def _make_service_with_core(self) -> GDACMetadataService:
        svc = self._make_service()
        svc._core_df = pd.DataFrame(
            {
                "file": [
                    "coriolis/6903091/profiles/R6903091_001.nc",
                    "coriolis/6903091/profiles/R6903091_002.nc",
                ],
                "date": pd.to_datetime(
                    ["20240115120000", "20240220120000"],
                    format="%Y%m%d%H%M%S",
                    utc=True,
                ),
                "latitude": [10.5, 11.0],
                "longitude": [65.2, 66.0],
                "ocean": ["I", "I"],
                "profiler_type": ["846", "846"],
                "institution": ["IF", "IF"],
                "parameters": ["", ""],
                "parameter_data_mode": ["", ""],
                "date_update": pd.to_datetime(
                    ["20240116000000", "20240221000000"],
                    format="%Y%m%d%H%M%S",
                    utc=True,
                ),
            }
        )
        return svc

    def test_search_by_region(self) -> None:
        svc = self._make_service()
        criteria = SearchCriteria(region="arabian_sea", limit=10)
        results = svc.search(criteria)
        assert len(results) == 2
        assert all(0.0 <= r.latitude <= 30.0 for r in results)

    def test_search_by_parameters(self) -> None:
        svc = self._make_service()
        criteria = SearchCriteria(parameters=["DOXY"], limit=10)
        results = svc.search(criteria)
        assert len(results) == 2
        assert all("DOXY" in r.parameters for r in results)

    def test_core_search_does_not_apply_bio_parameter_tokens(self) -> None:
        svc = self._make_service_with_core()
        criteria = SearchCriteria(region="arabian_sea", parameters=["TEMP"], limit=10)
        results = svc.search(criteria)
        assert len(results) == 2
        assert all(r.file.startswith("coriolis/6903091/profiles/R") for r in results)

    def test_search_by_float_id(self) -> None:
        svc = self._make_service()
        criteria = SearchCriteria(float_id="6903091", limit=10)
        results = svc.search(criteria)
        assert len(results) == 2
        assert all("6903091" in r.file for r in results)

    def test_search_by_year(self) -> None:
        svc = self._make_service()
        criteria = SearchCriteria(year=2024, limit=10)
        results = svc.search(criteria)
        assert len(results) == 3

    def test_search_no_match(self) -> None:
        svc = self._make_service()
        criteria = SearchCriteria(year=1999, limit=10)
        results = svc.search(criteria)
        assert len(results) == 0

    def test_search_by_parameters_and_logic(self) -> None:
        """Multiple parameters use AND logic (all must be present)."""
        svc = self._make_service()
        criteria = SearchCriteria(parameters=["DOXY", "CHLA"], limit=10)
        results = svc.search(criteria)
        assert len(results) == 1
        assert "DOXY" in results[0].parameters
        assert "CHLA" in results[0].parameters

    def test_search_by_profile_number(self) -> None:
        """Profile number filters to exact filename match (_001, _002, etc.)."""
        svc = self._make_service()
        criteria = SearchCriteria(float_id="6903091", profile_number=1, limit=10)
        results = svc.search(criteria)
        assert len(results) == 1
        assert "BR6903091_001.nc" in results[0].file

    def test_search_by_profile_number_no_match(self) -> None:
        """Profile number 999 does not exist — zero results."""
        svc = self._make_service()
        criteria = SearchCriteria(float_id="6903091", profile_number=999, limit=10)
        results = svc.search(criteria)
        assert len(results) == 0

    def test_search_not_loaded_raises(self) -> None:
        svc = GDACMetadataService()
        with pytest.raises(MetadataError):
            svc.search(SearchCriteria(limit=1))

    def test_load_from_file_coerces_mixed_types(self, tmp_path: Path) -> None:
        """Verify that latitude/longitude strings and mixed-type rows are coerced."""
        raw = (
            "# This is a comment line\n"
            "coriolis/6903091/profiles/BR6903091_001.nc,20240115120000,10.5,65.2,"
            "I,846,IF,PRES PSAL TEMP DOXY,R R R A,20240116000000\n"
            "coriolis/6903091/profiles/BR6903091_002.nc,20240220120000,11.0,66.0,"
            "I,846,IF,PRES PSAL TEMP DOXY CHLA,R R R A A,20240221000000\n"
            "bad/6900000/profiles/BR6900000_001.nc,invalid,not_a_lat,not_a_lon,"
            "A,845,AO,PRES PSAL TEMP,R R R,20240311000000\n"
        )
        gz_path = tmp_path / "test_index.txt.gz"
        with gzip.open(gz_path, "wt", encoding="utf-8") as f:
            f.write(raw)

        svc = GDACMetadataService()
        svc._load_from_file(gz_path)

        assert svc.is_loaded()
        assert len(svc._df) == 2  # bad row dropped
        assert svc._df["latitude"].dtype == "float64"
        assert svc._df["longitude"].dtype == "float64"
        assert isinstance(svc._df["date"].dtype, DatetimeTZDtype)

        # Search with numeric bounds must succeed without TypeError
        results = svc.search(SearchCriteria(lat_min=10.0, lat_max=11.0, limit=10))
        assert len(results) == 2

    def test_load_from_file_parses_core_index_without_shifting_date_update(
        self, tmp_path: Path
    ) -> None:
        """Core indexes have eight columns, unlike bio/synthetic indexes."""
        gz_path = tmp_path / "core_index.txt.gz"
        raw = (
            "coriolis/7900000/profiles/D7900000_001.nc,20240115120000,10.5,65.2,"
            "I,846,IF,20240116000000\n"
        )
        with gzip.open(gz_path, "wt", encoding="utf-8") as handle:
            handle.write(raw)

        svc = GDACMetadataService()
        svc._load_from_file(gz_path, is_core=True)

        assert svc._core_df is not None
        row = svc._core_df.iloc[0]
        assert row["parameters"] == ""
        assert row["parameter_data_mode"] == ""
        assert row["date_update"] == pd.Timestamp("2024-01-16T00:00:00Z")

        result = svc.search(SearchCriteria(parameters=["TEMP", "PSAL"], limit=1))
        assert result[0].file.endswith("D7900000_001.nc")
        assert result[0].date_update == pd.Timestamp("2024-01-16T00:00:00Z")

    def test_core_query_does_not_fall_through_to_bio_when_core_index_is_missing(self) -> None:
        svc = self._make_service()

        with pytest.raises(MetadataError, match="Core metadata index is unavailable"):
            svc.search(SearchCriteria(parameters=["TEMP"], limit=1))
