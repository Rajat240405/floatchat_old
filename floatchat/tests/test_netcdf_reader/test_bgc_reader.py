"""Tests for BGCNetCDFReader."""

import numpy as np
import pytest

from floatchat.exceptions import NetCDFReadError
from floatchat.netcdf_reader.bgc_reader import BGCNetCDFReader


class TestBGCNetCDFReader:
    def test_read_variables(self, sample_netcdf_dataset) -> None:
        reader = BGCNetCDFReader()
        df = reader.read(sample_netcdf_dataset, variables=["DOXY"])

        assert "PRES" in df.columns
        assert "DOXY" in df.columns
        assert "DOXY_QC" in df.columns
        assert len(df) == 5
        assert df["PRES"].iloc[0] == pytest.approx(2.0)

    def test_read_missing_variable_raises(self, sample_netcdf_dataset) -> None:
        reader = BGCNetCDFReader()
        with pytest.raises(NetCDFReadError):
            reader.read(sample_netcdf_dataset, variables=["CHLA"])

    def test_qc_values_present(self, sample_netcdf_dataset) -> None:
        reader = BGCNetCDFReader()
        df = reader.read(sample_netcdf_dataset, variables=["DOXY"])
        assert "DOXY_QC" in df.columns
        assert df["DOXY_QC"].iloc[0] == "1"

    def test_pressure_nan_rows_dropped(self, sample_netcdf_dataset) -> None:
        reader = BGCNetCDFReader()
        df = reader.read(sample_netcdf_dataset, variables=["DOXY"])
        assert df["PRES"].isna().sum() == 0
