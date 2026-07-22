"""Tests for variable alias resolution in BGCNetCDFReader."""

import tempfile

import netCDF4
import numpy as np
import pytest

from floatchat.netcdf_reader.bgc_reader import BGCNetCDFReader
from floatchat.repository_service.dataset_wrapper import NetCDFDataset


def _make_nc_with_adjusted_vars() -> bytes:
    """Create a NetCDF with both raw and _ADJUSTED versions of variables."""
    with tempfile.NamedTemporaryFile(suffix=".nc", delete=False) as tmp:
        tmp_name = tmp.name

    nc = netCDF4.Dataset(tmp_name, mode="w", format="NETCDF4")
    nc.createDimension("N_PROF", 1)
    nc.createDimension("N_LEVELS", 3)

    # Pressure (mandatory)
    pres = nc.createVariable(
        "PRES", "f4", ("N_PROF", "N_LEVELS"), fill_value=np.float32(99999.0)
    )
    pres[:] = [10.0, 50.0, 100.0]

    # Only ADJUSTED versions exist — no raw TEMP, DOXY, etc.
    temp_adj = nc.createVariable(
        "TEMP_ADJUSTED", "f4", ("N_PROF", "N_LEVELS"), fill_value=np.float32(99999.0)
    )
    temp_adj[:] = [25.0, 20.0, 15.0]

    psal_adj = nc.createVariable(
        "PSAL_ADJUSTED", "f4", ("N_PROF", "N_LEVELS"), fill_value=np.float32(99999.0)
    )
    psal_adj[:] = [35.0, 35.1, 35.2]

    doxy_adj = nc.createVariable(
        "DOXY_ADJUSTED", "f4", ("N_PROF", "N_LEVELS"), fill_value=np.float32(99999.0)
    )
    doxy_adj[:] = [210.0, 200.0, 190.0]

    chla_adj = nc.createVariable(
        "CHLA_ADJUSTED", "f4", ("N_PROF", "N_LEVELS"), fill_value=np.float32(99999.0)
    )
    chla_adj[:] = [1.0, 0.8, 0.5]

    nc.close()

    with open(tmp_name, "rb") as f:
        data = f.read()

    import os

    os.unlink(tmp_name)
    return data


@pytest.fixture
def adjusted_dataset() -> NetCDFDataset:
    data = _make_nc_with_adjusted_vars()
    ds = netCDF4.Dataset(
        filename="in-memory:adjusted.nc",
        memory=data,
        mode="r",
        format="NETCDF4",
    )
    ncd = NetCDFDataset("adjusted.nc", data, ds)
    yield ncd
    ncd.close()


class TestVariableAliases:
    def test_temp_resolves_to_temp_adjusted(self, adjusted_dataset) -> None:
        reader = BGCNetCDFReader()
        df = reader.read(adjusted_dataset, ["TEMP"])
        assert "TEMP_ADJUSTED" in df.columns
        assert df["TEMP_ADJUSTED"].iloc[0] == 25.0

    def test_psal_resolves_to_psal_adjusted(self, adjusted_dataset) -> None:
        reader = BGCNetCDFReader()
        df = reader.read(adjusted_dataset, ["PSAL"])
        assert "PSAL_ADJUSTED" in df.columns

    def test_doxy_resolves_to_doxy_adjusted(self, adjusted_dataset) -> None:
        reader = BGCNetCDFReader()
        df = reader.read(adjusted_dataset, ["DOXY"])
        assert "DOXY_ADJUSTED" in df.columns

    def test_chla_resolves_to_chla_adjusted(self, adjusted_dataset) -> None:
        reader = BGCNetCDFReader()
        df = reader.read(adjusted_dataset, ["CHLA"])
        assert "CHLA_ADJUSTED" in df.columns

    def test_multiple_aliases_in_one_read(self, adjusted_dataset) -> None:
        reader = BGCNetCDFReader()
        df = reader.read(adjusted_dataset, ["TEMP", "PSAL", "DOXY"])
        assert "TEMP_ADJUSTED" in df.columns
        assert "PSAL_ADJUSTED" in df.columns
        assert "DOXY_ADJUSTED" in df.columns

    def test_raw_variable_used_when_no_adjusted(self, sample_netcdf_dataset) -> None:
        """When raw variable exists and no _ADJUSTED, use raw."""
        reader = BGCNetCDFReader()
        df = reader.read(sample_netcdf_dataset, ["TEMP"])
        # The fixture has raw TEMP, not TEMP_ADJUSTED
        assert "TEMP" in df.columns
        assert "TEMP_ADJUSTED" not in df.columns
