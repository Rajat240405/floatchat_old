#!/usr/bin/env python3
"""
ETL Script: Build the local Argo Data Lake (Parquet) for Phase 1.

Usage:
    python -m floatchat.data_lake.ingest --year 2024 --month 3

This script:
1. Downloads a targeted subset of Argo NetCDF profiles for the Indian Ocean
   (Arabian Sea + Bay of Bengal) from the Ifremer GDAC.
2. Parses each file into a flat, tidy level-by-level structure.
3. Saves the result as partitioned Parquet files (year/month/).

Dependencies: duckdb, pyarrow (already in pyproject.toml).
Output: .data_lake/parquet/year=YYYY/month=MM/*.parquet

WARNING: This script downloads real data from GDAC. For a full Indian Ocean
ingest, expect ~500 MB and 30-60 minutes depending on network speed.
The Phase 1 walk skeleton ingests ONE month only.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# Add package to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from floatchat.config import settings
from floatchat.metadata_service.gdac import GDACMetadataService
from floatchat.metadata_service.polygons import point_in_region
from floatchat.repository_service.gdac_http import GDACRepositoryService
from floatchat.models import SearchCriteria

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# GDAC base URL for NetCDF file downloads.
_GDAC_NETCDF_BASE = "https://data-argo.ifremer.fr"

# India region bounding boxes (coarse filter before polygon test).
_INDIA_BOUNDS = {
    "arabian_sea": {"lat_min": 0.0, "lat_max": 30.0, "lon_min": 45.0, "lon_max": 80.0},
    "bay_of_bengal": {"lat_min": 0.0, "lat_max": 25.0, "lon_min": 78.0, "lon_max": 100.0},
}

# Default output root.
_DEFAULT_OUTPUT = Path(".data_lake/parquet")


def _is_india_region(lat: float, lon: float) -> bool:
    """Return True if coordinate is within the India box -10 to 30N, 40 to 100E across all DACs."""
    return -10.0 <= lat <= 30.0 and 40.0 <= lon <= 100.0


def _build_region_tag(lat: float, lon: float) -> str:
    """Return canonical region tag for a coordinate inside the Indian Ocean box."""
    if point_in_region(lon, lat, "arabian_sea"):
        return "arabian_sea"
    if point_in_region(lon, lat, "bay_of_bengal"):
        return "bay_of_bengal"
    return "indian_ocean"


def _load_india_metadata(year: int | None, month: int | None, max_files: int = 2000) -> list:
    """Load metadata and filter to Indian Ocean box -10..30N, 40..100E across all DACs."""
    logger.info("Loading metadata index...")
    svc = GDACMetadataService()
    svc.load()

    # Check #3: India box -10 to 30N, 40 to 100E across all DACs
    criteria = SearchCriteria(
        lat_min=-10.0,
        lat_max=30.0,
        lon_min=40.0,
        lon_max=100.0,
        year=year,
        month=month,
        parameters=["TEMP", "DOXY"],
        limit=10000,
    )
    records = svc.search(criteria)
    logger.info("Retrieved %d candidate metadata records matching box [-10..30N, 40..100E]", len(records))

    india_records = [
        r for r in records
        if _is_india_region(r.latitude, r.longitude)
    ]
    logger.info("India-region box filter: %d records retained across %d unique DACs (%s)",
                len(india_records),
                len({r.institution for r in india_records}),
                sorted({str(r.institution) for r in india_records}))

    # Separate into sub-regions (arabian_sea, bay_of_bengal, indian_ocean)
    arabian = [r for r in india_records if _build_region_tag(r.latitude, r.longitude) == "arabian_sea"]
    bengal = [r for r in india_records if _build_region_tag(r.latitude, r.longitude) == "bay_of_bengal"]
    other_io = [r for r in india_records if _build_region_tag(r.latitude, r.longitude) == "indian_ocean"]

    def _interleave(recs: list) -> list:
        core = [r for r in recs if not r.file.split("/")[-1].startswith("B")]
        bio = [r for r in recs if r.file.split("/")[-1].startswith("B")]
        out = []
        for c, b in zip(core, bio):
            out.append(c)
            out.append(b)
        out.extend(core[len(bio):])
        out.extend(bio[len(core):])
        return out

    arabian_inter = _interleave(arabian)
    bengal_inter = _interleave(bengal)
    other_io_inter = _interleave(other_io)

    if max_files <= 0:
        logger.info("No file limit imposed (max_files <= 0); returning all %d profiles", len(india_records))
        return arabian_inter + bengal_inter + other_io_inter

    q1 = max_files // 3
    q2 = max_files // 3
    q3 = max_files - q1 - q2
    balanced = arabian_inter[:q1] + bengal_inter[:q2] + other_io_inter[:q3]
    return balanced[:max_files]


def _parse_cycle_number(file_path: str) -> int:
    """Extract the 3-digit cycle/profile number from a GDAC file path."""
    import re
    match = re.search(r"_(\d{3})\.nc$", file_path)
    return int(match.group(1)) if match else 0


def _parse_float_id(file_path: str) -> str:
    """Extract the WMO float ID from a GDAC file path."""
    import re
    match = re.search(r"/(\d{7,})/", file_path)
    return match.group(1) if match else "unknown"


def _parse_netcdf_to_dataframe(
    ncd_bytes: bytes,
    file_path: str,
    record: object,
) -> pd.DataFrame:
    """Parse a single Argo NetCDF file into a tidy level-by-level DataFrame.

    Parameters
    ----------
    ncd_bytes : bytes
        Raw NetCDF file content.
    file_path : str
        GDAC relative path (used for float_id/cycle extraction).
    record : MetadataRecord
        Associated metadata record with lat/lon/date.

    Returns
    -------
    pd.DataFrame
        One row per pressure level with all core + BGC variables.
    """
    import netCDF4

    # Open from memory
    ds = netCDF4.Dataset(
        filename="in-memory",
        memory=ncd_bytes,
        mode="r",
        format="NETCDF4",
    )

    float_id = _parse_float_id(file_path)
    cycle_number = _parse_cycle_number(file_path)

    if "PRES" not in ds.variables:
        ds.close()
        return pd.DataFrame()

    pres_raw = ds.variables["PRES"][:]
    if hasattr(pres_raw, "filled"):
        pres_raw = pres_raw.filled(np.nan)
    pres_flat = np.asarray(pres_raw).flatten()
    n_levels = len(pres_flat)
    if n_levels == 0:
        ds.close()
        return pd.DataFrame()

    def _read_var(name: str) -> np.ndarray:
        if name not in ds.variables:
            return np.full(n_levels, np.nan, dtype=float)
        raw = ds.variables[name][:]
        if hasattr(raw, "filled"):
            raw = raw.filled(np.nan)
        flat = np.asarray(raw).flatten()
        if hasattr(ds.variables[name], "_FillValue"):
            fill = ds.variables[name]._FillValue
            flat = np.where(flat == fill, np.nan, flat)
        if len(flat) != n_levels:
            if len(flat) < n_levels:
                flat = np.pad(flat, (0, n_levels - len(flat)), constant_values=np.nan)
            else:
                flat = flat[:n_levels]
        return flat.astype(float)

    def _read_qc(name: str) -> np.ndarray:
        if name not in ds.variables:
            return np.full(n_levels, "", dtype=object)
        raw = ds.variables[name][:]
        if hasattr(raw, "filled"):
            raw = raw.filled(b" ")
        flat = np.asarray(raw).flatten()
        if flat.dtype.kind == "S":
            decoded = [x.decode("utf-8", errors="ignore").strip() for x in flat]
        else:
            decoded = [str(x).strip() if str(x).strip() != "nan" else "" for x in flat]
        if len(decoded) != n_levels:
            if len(decoded) < n_levels:
                decoded = decoded + [""] * (n_levels - len(decoded))
            else:
                decoded = decoded[:n_levels]
        return np.asarray(decoded, dtype=object)

    # Read all variables (flatten N_PROF × N_LEVELS to 1-D)
    pressure = _read_var("PRES")
    temp = _read_var("TEMP")
    temp_qc = _read_qc("TEMP_QC")
    temp_adjusted = _read_var("TEMP_ADJUSTED")
    psal = _read_var("PSAL")
    psal_qc = _read_qc("PSAL_QC")
    psal_adjusted = _read_var("PSAL_ADJUSTED")
    doxy = _read_var("DOXY")
    doxy_qc = _read_qc("DOXY_QC")
    doxy_adjusted = _read_var("DOXY_ADJUSTED")
    chla = _read_var("CHLA")
    chla_qc = _read_qc("CHLA_QC")
    chla_adjusted = _read_var("CHLA_ADJUSTED")

    # Get data mode from metadata record or file
    data_mode = str(record.parameter_data_mode or "R").split()[0] if record.parameter_data_mode else "R"

    # Profile date
    profile_date = record.date
    year = profile_date.year if profile_date else 2024
    month = profile_date.month if profile_date else 1

    region_tag = _build_region_tag(record.latitude, record.longitude)

    # Build tidy DataFrame
    df = pd.DataFrame({
        "float_id": [float_id] * n_levels,
        "cycle_number": [cycle_number] * n_levels,
        "date": [profile_date.date() if profile_date else None] * n_levels,
        "year": [year] * n_levels,
        "month": [month] * n_levels,
        "lat": [record.latitude] * n_levels,
        "lon": [record.longitude] * n_levels,
        "data_mode": [data_mode] * n_levels,
        "pressure": pressure,
        "temp": temp,
        "temp_qc": temp_qc,
        "temp_adjusted": temp_adjusted,
        "psal": psal,
        "psal_qc": psal_qc,
        "psal_adjusted": psal_adjusted,
        "doxy": doxy,
        "doxy_qc": doxy_qc,
        "doxy_adjusted": doxy_adjusted,
        "chla": chla,
        "chla_qc": chla_qc,
        "chla_adjusted": chla_adjusted,
        "region_tag": [region_tag] * n_levels,
        "source_file": [file_path] * n_levels,
        "dac": [record.institution] * n_levels,
    })

    ds.close()
    return df


def run_ingest(
    year: int,
    month: int,
    output_root: Path | None = None,
    max_files: int = 50,
    dry_run: bool = False,
) -> Path:
    """Run the full ETL pipeline for a single year/month slice.

    Parameters
    ----------
    year, month : int
        The year and month to ingest.
    output_root : Path, optional
        Root directory for Parquet partitions. Defaults to .data_lake/parquet.
    max_files : int
        Maximum number of NetCDF files to download (for Phase 1 walk skeleton).
    dry_run : bool
        If True, only count files without downloading.

    Returns
    -------
    Path
        The output root that was written to.
    """
    output_root = output_root or _DEFAULT_OUTPUT
    logger.info("=" * 60)
    if month is not None:
        logger.info("Phase 1 ETL: Ingest Argo data for %04d-%02d", year, month)
    else:
        logger.info("Phase 1 ETL: Ingest Argo data for full year %04d", year)
    logger.info("Output: %s", output_root)
    logger.info("Max files: %s", "ALL (no limit)" if max_files <= 0 else max_files)
    logger.info("=" * 60)

    t_start = time.perf_counter()

    # --- Step 1: Load metadata ----------------------------------------- #
    records = _load_india_metadata(year, month, max_files)

    if not records:
        logger.warning("No India-region records found for year=%s month=%s", year, month)
        return output_root

    records_to_fetch = records if max_files <= 0 else records[:max_files]
    logger.info("Will fetch %d of %d candidate records", len(records_to_fetch), len(records))

    # --- Step 2: Download and parse NetCDFs ---------------------------- #
    repo = GDACRepositoryService()
    all_dfs: list[pd.DataFrame] = []
    fetched = 0
    failed = 0

    for rec in records_to_fetch:
        try:
            # Construct full GDAC URL
            url = f"{_GDAC_NETCDF_BASE}/{rec.file}"
            logger.info("Fetching: %s", rec.file)

            ncd = repo.fetch(rec.file)
            ncd_bytes = ncd._data  # type: ignore[attr-defined]
            ncd.close()

            df = _parse_netcdf_to_dataframe(ncd_bytes, rec.file, rec)
            if not df.empty:
                all_dfs.append(df)
                fetched += 1

            logger.info(
                "  → %d levels from float %s cycle %s",
                len(df),
                _parse_float_id(rec.file),
                _parse_cycle_number(rec.file),
            )

        except Exception as exc:
            logger.warning("Failed to process %s: %s", rec.file, exc)
            failed += 1

    if not all_dfs:
        logger.error("No data successfully fetched. Aborting.")
        return output_root

    # --- Step 3: Combine and partition --------------------------------- #
    combined = pd.concat(all_dfs, ignore_index=True)
    logger.info("Combined DataFrame: %d rows × %d columns", combined.shape[0], combined.shape[1])

    # Ensure correct dtypes
    combined["year"] = combined["year"].astype("int16")
    combined["month"] = combined["month"].astype("int8")
    combined["cycle_number"] = combined["cycle_number"].astype("int16")
    combined["pressure"] = combined["pressure"].astype("float32")
    combined["lat"] = combined["lat"].astype("float32")
    combined["lon"] = combined["lon"].astype("float32")
    # Convert date to proper type
    combined["date"] = pd.to_datetime(combined["date"], errors="coerce").dt.date

    # --- Step 4: Write partitioned Parquet ------------------------------ #
    output_root.mkdir(parents=True, exist_ok=True)

    logger.info("Writing partitioned Parquet files...")
    # pyarrow partition by year/month
    combined["year"] = combined["year"].astype(str).str.zfill(4)
    combined["month"] = combined["month"].astype(str).str.zfill(2)
    combined["year"] = combined["year"].astype("int16")
    combined["month"] = combined["month"].astype("int8")

    # Write with pyarrow (partition by year, month)
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        logger.error(
            "pyarrow is required to write Parquet files. "
            "Please install it in your environment by running:\n"
            "    pip install pyarrow duckdb\n"
            "or:\n"
            "    pip install -e \".[dev]\""
        )
        raise exc from None

    table = pa.Table.from_pandas(combined, preserve_index=False)

    pq.write_to_dataset(
        table,
        root_path=str(output_root),
        partition_cols=["year", "month"],
        compression="snappy",
        )


    t_end = time.perf_counter()
    logger.info("=" * 60)
    logger.info("ETL Complete!")
    logger.info("  Fetched: %d files (%d failed)", fetched, failed)
    logger.info("  Total rows: %d", len(combined))
    logger.info("  Unique floats: %d", combined["float_id"].nunique())
    logger.info("  Unique profiles: %d", combined[["float_id", "cycle_number"]].drop_duplicates().shape[0])
    logger.info("  Output: %s", output_root)
    logger.info("  Time: %.1f seconds", t_end - t_start)
    logger.info("=" * 60)

    # Print a quick summary of the lake
    _print_lake_summary(output_root)

    return output_root


def _print_lake_summary(output_root: Path) -> None:
    """Print a quick summary of the lake using DuckDB."""
    try:
        import duckdb

        conn = duckdb.connect(database=":memory:")
        pattern = (output_root / "**" / "*.parquet").as_posix()
        df = conn.execute(
            f"""
            SELECT
                year,
                month,
                region_tag,
                COUNT(*) as total_levels,
                COUNT(DISTINCT float_id) as floats,
                COUNT(DISTINCT cycle_number) as profiles
            FROM read_parquet(?, hive_partitioning=true)
            GROUP BY year, month, region_tag
            ORDER BY year, month, region_tag
            """,
            [pattern],
        ).fetchdf()
        logger.info("\nLake Summary:\n%s", df.to_string(index=False))
        conn.close()
    except Exception as exc:
        logger.warning("Could not print lake summary: %s", exc)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Argo Data Lake (Phase 1 ETL)")
    parser.add_argument("--year", type=int, required=True, help="Year to ingest")
    parser.add_argument("--month", type=int, required=False, default=None, help="Month to ingest (1-12, optional)")
    parser.add_argument(
        "--output",
        type=str,
        default=".data_lake/parquet",
        help="Output root directory",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=1500,
        help="Max NetCDF files to download (<=0 means all)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Count files without downloading")

    args = parser.parse_args()

    if args.month is not None and not (1 <= args.month <= 12):
        parser.error("--month must be between 1 and 12")

    output_root = Path(args.output)
    run_ingest(
        year=args.year,
        month=args.month,
        output_root=output_root,
        max_files=args.max_files,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
