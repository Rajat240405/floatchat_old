"""Shared test fixtures for FloatChat."""

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import netCDF4
import numpy as np
import pytest

# ── Cleanup M1: deterministic test environment ───────────────────────────── #
# The suite must behave identically regardless of the developer machine's
# environment variables and regardless of the directory pytest is launched
# from. Before M1, the default data-lake root (".data_lake/parquet") resolved
# against the *current working directory*, so API/health tests silently
# passed only when launched from the floatchat/ backend directory (which
# happened to contain a committed sample lake), and the default Phase-2 lake
# directory depended on one developer's Windows path ("E:\\...").
#
# Here we pin every environment-derived setting to this repository's
# committed fixture lake, using an absolute path anchored to THIS file.
from floatchat.config import settings as _test_settings

FIXTURE_LAKE_ROOT = Path(__file__).resolve().parent / "fixtures" / "lake_parquet"

if not FIXTURE_LAKE_ROOT.exists():
    raise RuntimeError(
        f"Committed test fixture lake not found at {FIXTURE_LAKE_ROOT}. "
        "The suite relies on this small sample lake; do not delete it."
    )

# Pin BEFORE anything builds the runtime graph (app/dependencies read these
# values lazily at first request).
_test_settings.data_lake_root = str(FIXTURE_LAKE_ROOT)
# Phase 2 (full lake) must never be consulted during tests — its location is
# machine-specific. Forcing it off makes the suite hermetic.
_test_settings.data_lake_phase2_enabled = False
_test_settings.data_lake_dir = ""

from floatchat.models import MetadataRecord, ParsedIntent
from floatchat.repository_service.dataset_wrapper import NetCDFDataset


@pytest.fixture(scope="session")
def fixture_lake_root() -> Path:
    """Reusable fixture: absolute path to the committed sample Parquet lake.

    Use this instead of relying on the cwd-relative runtime default.
    """
    return FIXTURE_LAKE_ROOT


@pytest.fixture
def sample_parsed_intent() -> ParsedIntent:
    return ParsedIntent(
        intent="profile_plot",
        region="arabian_sea",
        variables=["DOXY"],
        year=2024,
        limit=2,
    )


@pytest.fixture
def sample_metadata_records() -> list[MetadataRecord]:
    return [
        MetadataRecord(
            file="coriolis/6903091/profiles/BR6903091_001.nc",
            date=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
            latitude=10.5,
            longitude=65.2,
            ocean="I",
            profiler_type="846",
            institution="IF",
            parameters="PRES PSAL TEMP DOXY",
            parameter_data_mode="R R R A",
            date_update=datetime(2024, 1, 16, 0, 0, 0, tzinfo=timezone.utc),
        ),
        MetadataRecord(
            file="coriolis/6903091/profiles/BR6903091_002.nc",
            date=datetime(2024, 2, 20, 12, 0, 0, tzinfo=timezone.utc),
            latitude=11.0,
            longitude=66.0,
            ocean="I",
            profiler_type="846",
            institution="IF",
            parameters="PRES PSAL TEMP DOXY CHLA",
            parameter_data_mode="R R R A A",
            date_update=datetime(2024, 2, 21, 0, 0, 0, tzinfo=timezone.utc),
        ),
    ]


def _make_test_nc_bytes() -> bytes:
    """Create a tiny in-memory Argo-like BGC profile NetCDF file."""
    with tempfile.NamedTemporaryFile(suffix=".nc", delete=False) as tmp:
        tmp_name = tmp.name

    nc = netCDF4.Dataset(tmp_name, mode="w", format="NETCDF4")
    nc.createDimension("N_PROF", 1)
    nc.createDimension("N_LEVELS", 5)

    # Pressure
    pres = nc.createVariable(
        "PRES", "f4", ("N_PROF", "N_LEVELS"), fill_value=np.float32(99999.0)
    )
    pres[:] = [2.0, 10.0, 50.0, 100.0, 200.0]

    # Temperature
    temp = nc.createVariable(
        "TEMP", "f4", ("N_PROF", "N_LEVELS"), fill_value=np.float32(99999.0)
    )
    temp[:] = [25.0, 24.0, 20.0, 15.0, 10.0]

    # Salinity
    psal = nc.createVariable(
        "PSAL", "f4", ("N_PROF", "N_LEVELS"), fill_value=np.float32(99999.0)
    )
    psal[:] = [35.0, 35.1, 35.2, 35.3, 35.4]

    # Dissolved Oxygen
    doxy = nc.createVariable(
        "DOXY", "f4", ("N_PROF", "N_LEVELS"), fill_value=np.float32(99999.0)
    )
    doxy[:] = [210.0, 205.0, 190.0, 180.0, 170.0]

    # DOXY QC
    doxy_qc = nc.createVariable("DOXY_QC", "S1", ("N_PROF", "N_LEVELS"))
    doxy_qc[:] = np.array([[b"1", b"1", b"1", b"2", b"1"]])

    nc.close()

    with open(tmp_name, "rb") as f:
        data = f.read()

    import os

    os.unlink(tmp_name)
    return data


@pytest.fixture
def sample_netcdf_dataset() -> NetCDFDataset:
    """Yield an open NetCDFDataset wrapper backed by synthetic bytes."""
    data = _make_test_nc_bytes()
    ds = netCDF4.Dataset(
        filename="in-memory:test.nc",
        memory=data,
        mode="r",
        format="NETCDF4",
    )
    ncd = NetCDFDataset("test.nc", data, ds)
    yield ncd
    ncd.close()
