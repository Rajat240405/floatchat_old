#!/usr/bin/env python3
"""
Phase 2 — Full India-region Argo Data Lake ETL Builder.

Builds four Parquet tables from GDAC NetCDF profiles:

1. **float_registry** — one row per float (metadata, sensors, deployment info)
2. **profile_index** — one row per profile/cycle (date, location, data mode, variables)
3. **levels** — one row per depth measurement (level-by-level ocean data)
4. **region_month_stats** — precomputed aggregate counts per region/month/year

Partitioning:
- levels, profile_index: by year/month
- float_registry: one file (small table)
- region_month_stats: by year

Usage:
    python -m floatchat.data_lake.phase2_builder --max-profiles 10
    python -m floatchat.data_lake.phase2_builder (full bulk)
"""

from __future__ import annotations

import argparse
import csv
import gzip
import logging
import os
import re
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pandas as pd
from tqdm import tqdm

# Add src for package imports
src_path = str(Path(__file__).parent.parent.parent)
if src_path not in sys.path:
    sys.path.insert(0, src_path)

from floatchat.config import settings
from floatchat.ontology.regions import INDIA_DEPLOYMENT_BBOX, tag_india_region

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────────────── #

GDAC_BASE = "https://data-argo.ifremer.fr"
CORE_INDEX_URL = f"{GDAC_BASE}/ar_index_global_prof.txt.gz"
BIO_INDEX_URL = f"{GDAC_BASE}/argo_bio-profile_index.txt.gz"

# India bounding box (matches metadata_service/regions.py).
# Ontology 2.0 (Phase 1): single-sourced from the domain ontology's
# INDIA_DEPLOYMENT_BBOX; values are unchanged.
INDIA_LAT_MIN = INDIA_DEPLOYMENT_BBOX["lat_min"]
INDIA_LAT_MAX = INDIA_DEPLOYMENT_BBOX["lat_max"]
INDIA_LON_MIN = INDIA_DEPLOYMENT_BBOX["lon_min"]
INDIA_LON_MAX = INDIA_DEPLOYMENT_BBOX["lon_max"]

# HTTP settings
HTTP_TIMEOUT = 120
HTTP_MAX_CONNECTIONS = 20

# Float ID regex
FLOAT_ID_RE = re.compile(r"[\\/](\d{7,})[\\/]")
CYCLE_RE = re.compile(r"_(\d{3})\.nc$")

# ── Index loading ───────────────────────────────────────────────────────── #

CORE_INDEX_COLUMNS = [
    "file", "date", "latitude", "longitude", "ocean",
    "profiler_type", "institution", "date_update",
]

BIO_INDEX_COLUMNS = [
    "file", "date", "latitude", "longitude", "ocean",
    "profiler_type", "institution", "parameters",
    "parameter_data_mode", "date_update",
]


def download_index(url: str, dest: Path, label: str) -> Path:
    """Download a GDAC index file if not already cached."""
    if dest.exists():
        logger.info("%s cache exists (%.0f KB), reusing", label, dest.stat().st_size / 1024)
        return dest
    logger.info("Downloading %s from %s ...", label, url)
    tmp = dest.with_name(f"{dest.name}.tmp")
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
        tmp.replace(dest)
        logger.info("Downloaded %s: %.0f KB", label, dest.stat().st_size / 1024)
        return dest
    except Exception as e:
        tmp.unlink(missing_ok=True)
        logger.error("Failed to download %s: %s", label, e)
        raise


def load_index_csv(path: Path) -> list[dict[str, Any]]:
    """Load a GDAC index CSV file (Core or Bio) into a list of dicts.
    
    Returns only rows within the India bounding box.
    Uses streaming for memory efficiency.
    """
    with gzip.open(path, "rt", errors="replace", newline="") as f:
        reader = csv.reader(f)
        records = []
        for row in reader:
            if not row or row[0].startswith("#") or row[0].startswith("file"):
                continue
            if len(row) < 8:
                continue

            try:
                lat = float(row[2])
                lon = float(row[3])
            except (ValueError, IndexError):
                continue

            # Filter to India bbox early
            if not (INDIA_LAT_MIN <= lat <= INDIA_LAT_MAX and
                    INDIA_LON_MIN <= lon <= INDIA_LON_MAX):
                continue

            date_str = row[1].strip()
            if len(date_str) < 8:
                continue

            try:
                profile_date = datetime(
                    int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]),
                    int(date_str[8:10]) if len(date_str) > 8 else 0,
                    int(date_str[10:12]) if len(date_str) > 10 else 0,
                    int(date_str[12:14]) if len(date_str) > 12 else 0,
                    tzinfo=timezone.utc,
                )
            except (ValueError, IndexError):
                continue

            m_float = FLOAT_ID_RE.search(row[0])
            float_id = m_float.group(1) if m_float else "unknown"
            m_cycle = CYCLE_RE.search(row[0])
            cycle_number = int(m_cycle.group(1)) if m_cycle else 0

            rec = {
                "file": row[0],
                "date": profile_date,
                "latitude": lat,
                "longitude": lon,
                "ocean": row[4].strip() if len(row) > 4 else "",
                "profiler_type": row[5].strip() if len(row) > 5 else "",
                "institution": row[6].strip() if len(row) > 6 else "",
                "date_update": row[-1].strip() if len(row) > 7 else "",
                "float_id": float_id,
                "cycle_number": cycle_number,
                "parameters": row[7].strip() if len(row) > 7 else "",
                "parameter_data_mode": row[8].strip() if len(row) > 8 else "",
            }
            # Classify region
            rec["region_tag"] = _classify_region(lat, lon)
            records.append(rec)

    return records


# ── NetCDF downloading ──────────────────────────────────────────────────── #


def _classify_region(lat: float, lon: float) -> str:
    """Classify coordinate into India sub-region."""
    # Ontology 2.0 (Phase 1): the sub-region rule lives in the domain ontology
    # (tag_india_region); the ETL "indian_ocean" fallback is preserved.
    return tag_india_region(lat, lon) or "indian_ocean"


def download_netcdf(file_path: str, dest_dir: Path, client: httpx.Client | None = None) -> Path | None:
    """Download a single NetCDF file from GDAC to local storage.
    
    The GDAC file paths in the index do NOT include 'dac/',
    but the actual download URLs need it:
    https://data-argo.ifremer.fr/dac/<file_path>
    
    Returns the local path if successful, None on failure.
    """
    url = f"{GDAC_BASE}/dac/{file_path}"
    dest = dest_dir / file_path
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists():
        return dest

    close_client = False
    if client is None:
        client = httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True)
        close_client = True

    try:
        tmp = dest.with_name(f"{dest.name}.tmp")
        with client.stream("GET", url) as resp:
            resp.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in resp.iter_bytes(chunk_size=512 * 1024):
                    if chunk:
                        f.write(chunk)
        tmp.replace(dest)
        return dest
    except Exception as e:
        logger.debug("Failed to download %s: %s", url, e)
        return None
    finally:
        if close_client:
            client.close()


# ── NetCDF parsing ──────────────────────────────────────────────────────── #

def parse_netcdf_to_tables(
    file_path: str,
    ncd_bytes: bytes,
    record: dict[str, Any],
) -> dict[str, Any]:
    """Parse a single Argo NetCDF file into float_registry, profile_index, and levels data.
    
    Returns:
        dict with keys:
        - 'float': dict for float_registry (or None)
        - 'profile': dict for profile_index (or None)
        - 'levels': pd.DataFrame for levels table
    """
    import netCDF4

    float_id = record["float_id"]
    cycle_number = record["cycle_number"]

    try:
        ds = netCDF4.Dataset(filename="in-memory", memory=ncd_bytes, mode="r", format="NETCDF4")
    except Exception:
        return {"float": None, "profile": None, "levels": pd.DataFrame()}

    if "PRES" not in ds.variables:
        ds.close()
        return {"float": None, "profile": None, "levels": pd.DataFrame()}

    # Read pressure to determine number of levels
    pres_raw = ds.variables["PRES"][:]
    if hasattr(pres_raw, "filled"):
        pres_raw = pres_raw.filled(np.nan)
    pres_flat = np.asarray(pres_raw).flatten()
    n_levels = len(pres_flat)
    if n_levels == 0:
        ds.close()
        return {"float": None, "profile": None, "levels": pd.DataFrame()}

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
            decoded = decoded[:n_levels] if len(decoded) > n_levels else decoded + [""] * (n_levels - len(decoded))
        return np.asarray(decoded, dtype=object)

    # Read variable data
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
    bbp700 = _read_var("BBP700")
    bbp700_qc = _read_qc("BBP700_QC")
    bbp700_adjusted = _read_var("BBP700_ADJUSTED")
    nitrate = _read_var("NITRATE")
    nitrate_qc = _read_qc("NITRATE_QC")
    nitrate_adjusted = _read_var("NITRATE_ADJUSTED")
    ph_in_situ_total = _read_var("PH_IN_SITU_TOTAL")
    ph_in_situ_total_qc = _read_qc("PH_IN_SITU_TOTAL_QC")
    ph_in_situ_total_adjusted = _read_var("PH_IN_SITU_TOTAL_ADJUSTED")
    downwelling_par = _read_var("DOWNWELLING_PAR")
    downwelling_par_qc = _read_qc("DOWNWELLING_PAR_QC")
    downwelling_par_adjusted = _read_var("DOWNWELLING_PAR_ADJUSTED")

    # Build available_variables list
    available_vars = []
    for var_name, data in [
        ("TEMP", temp), ("PSAL", psal), ("DOXY", doxy), ("CHLA", chla),
        ("BBP700", bbp700), ("NITRATE", nitrate),
        ("PH_IN_SITU_TOTAL", ph_in_situ_total),
        ("DOWNWELLING_PAR", downwelling_par),
        ("TEMP_ADJUSTED", temp_adjusted), ("PSAL_ADJUSTED", psal_adjusted),
        ("DOXY_ADJUSTED", doxy_adjusted), ("CHLA_ADJUSTED", chla_adjusted),
        ("BBP700_ADJUSTED", bbp700_adjusted),
        ("NITRATE_ADJUSTED", nitrate_adjusted),
        ("PH_IN_SITU_TOTAL_ADJUSTED", ph_in_situ_total_adjusted),
        ("DOWNWELLING_PAR_ADJUSTED", downwelling_par_adjusted),
    ]:
        if np.any(~np.isnan(data)):
            available_vars.append(var_name)

    # Data mode
    data_mode = record.get("parameter_data_mode", "R")
    if isinstance(data_mode, str) and data_mode:
        data_mode = data_mode.split()[0] if data_mode else "R"
    else:
        data_mode = "R"

    profile_date = record["date"]
    year = profile_date.year
    month = profile_date.month

    # Build levels DataFrame
    levels_df = pd.DataFrame({
        "float_id": [float_id] * n_levels,
        "cycle_number": [cycle_number] * n_levels,
        "date": [profile_date.date()] * n_levels,
        "year": [year] * n_levels,
        "month": [month] * n_levels,
        "lat": [record["latitude"]] * n_levels,
        "lon": [record["longitude"]] * n_levels,
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
        "bbp700": bbp700,
        "bbp700_qc": bbp700_qc,
        "bbp700_adjusted": bbp700_adjusted,
        "nitrate": nitrate,
        "nitrate_qc": nitrate_qc,
        "nitrate_adjusted": nitrate_adjusted,
        "ph_in_situ_total": ph_in_situ_total,
        "ph_in_situ_total_qc": ph_in_situ_total_qc,
        "ph_in_situ_total_adjusted": ph_in_situ_total_adjusted,
        "downwelling_par": downwelling_par,
        "downwelling_par_qc": downwelling_par_qc,
        "downwelling_par_adjusted": downwelling_par_adjusted,
        "region_tag": [record["region_tag"]] * n_levels,
        "source_file": [file_path] * n_levels,
        "dac": [record["institution"]] * n_levels,
    })

    # Build profile_index record
    profile_rec = {
        "float_id": float_id,
        "cycle_number": cycle_number,
        "date": profile_date,
        "year": year,
        "month": month,
        "latitude": record["latitude"],
        "longitude": record["longitude"],
        "data_mode": data_mode,
        "region_tag": record["region_tag"],
        "available_variables": " ".join(sorted(available_vars)),
        "dac": record["institution"],
        "source_file": file_path,
        "n_levels": n_levels,
    }

    # Extract float metadata (from first encounter; updated on subsequent)
    # Get platform info from global attributes if available
    platform_type = getattr(ds, "PLATFORM_TYPE", record.get("profiler_type", ""))
    float_md = {
        "float_id": float_id,
        "platform_type": str(platform_type),
        "institution": record["institution"],
        "profiler_type": record.get("profiler_type", ""),
        "region_tag": record["region_tag"],
        "sensors": "",  # populated from available variables
        "first_profile_date": profile_date,
        "last_profile_date": profile_date,
        "profile_count": 1,
    }

    ds.close()
    return {"float": float_md, "profile": profile_rec, "levels": levels_df}


# ── Phase 2 Builder ─────────────────────────────────────────────────────── #

class Phase2DataLakeBuilder:
    """Build the complete India-region Argo data lake as partitioned Parquet tables."""

    def __init__(
        self,
        data_lake_dir: str | Path,
        cache_dir: str | Path | None = None,
        download_workers: int = 4,
    ) -> None:
        self.data_lake_dir = Path(data_lake_dir)
        self.raw_dir = self.data_lake_dir / "raw"
        self.parquet_dir = self.data_lake_dir / "parquet"
        self.cache_dir = Path(cache_dir) if cache_dir else self.data_lake_dir / ".cache"
        self.download_workers = download_workers

        # Create directories
        for d in [self.raw_dir / "core", self.raw_dir / "bgc",
                  self.parquet_dir / "float_registry",
                  self.parquet_dir / "profile_index",
                  self.parquet_dir / "levels",
                  self.parquet_dir / "region_month_stats",
                  self.cache_dir]:
            d.mkdir(parents=True, exist_ok=True)

        # Pipelines state
        self.core_records: list[dict] = []
        self.bio_records: list[dict] = []
        self._deduped_core: list[dict] = []
        self._deduped_bio: list[dict] = []
        self.float_metadata: dict[str, dict] = {}
        self.profile_records: list[dict] = []
        self.levels_batches: list[pd.DataFrame] = []
        self.stats: dict = {
            "core_downloaded": 0, "bio_downloaded": 0,
            "core_failed": 0, "bio_failed": 0,
            "total_profiles": 0, "total_levels": 0,
            "unique_floats": set(),
            "skipped_checkpoint": 0,
        }
        # Checkpoint file for resumable parsing
        self._ckpt_path = self.data_lake_dir / ".checkpoint"
        self._checkpoint_done: set[tuple[str, int, str]] = set()
        self._load_checkpoint()
        # Global last-report dates (from unfiltered index) for status computation
        # Key: float_id, Value: latest profile date ANYWHERE in the world
        self._global_last_dates: dict[str, datetime] = {}

    _INACTIVE_THRESHOLD_DAYS = 365  # 12 months without any profile → truly dead

    # ── Checkpoint (resumability) ──────────────────────────────────── #

    def _checkpoint_path(self) -> Path:
        return self.data_lake_dir / ".checkpoint"

    def _load_checkpoint(self) -> None:
        """Load previously-parsed (float_id, cycle_number, dtype) triples from checkpoint file.

        Backward compatible: legacy 2-field lines (``float_id,cycle_number``)
        are loaded as ``(float_id, cycle_number, "core")`` so existing checkpoint
        files do not need to be deleted.
        """
        ckpt = self._checkpoint_path()
        if ckpt.exists():
            with ckpt.open("r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split(",")
                    if len(parts) >= 2:
                        try:
                            float_id = parts[0]
                            cycle_number = int(parts[1])
                            dtype = parts[2] if len(parts) >= 3 else "core"
                            self._checkpoint_done.add((float_id, cycle_number, dtype))
                        except ValueError:
                            pass
            logger.info("Loaded checkpoint: %d profiles already parsed", len(self._checkpoint_done))

    def _save_checkpoint(self, float_id: str, cycle_number: int, dtype: str) -> None:
        """Record a successfully-parsed profile in the checkpoint file."""
        ckpt = self._checkpoint_path()
        with ckpt.open("a") as f:
            f.write(f"{float_id},{cycle_number},{dtype}\n")


    def run(self, max_profiles: int = 0, skip_download: bool = False) -> None:
        """Run the full ETL pipeline.
        
        RESUMPTION: Safe to interrupt and restart. Uses a checkpoint file
        (``<data_lake_dir>/.checkpoint``) that records every successfully
        parsed (float_id, cycle_number) so the parse step skips already-
        done work. The download step is individually resumable (it checks
        each file's existence before downloading). The Parquet table build
        steps rebuild from scratch every time (fast — pure in-memory agg).
        
        Args:
            max_profiles: Max profiles to process (0 = all).
            skip_download: If True, skip download (use existing raw files).
        """
        t_start = time.perf_counter()
        logger.info("=" * 60)
        logger.info("Phase 2 Data Lake Builder")
        logger.info("  Root:     %s", self.data_lake_dir)
        logger.info("  Raw:      %s", self.raw_dir)
        logger.info("  Parquet:  %s", self.parquet_dir)
        logger.info("  Workers:  %d", self.download_workers)
        logger.info("  Max prof: %s", "ALL" if max_profiles <= 0 else max_profiles)
        logger.info("  Skip dl:  %s", skip_download)
        logger.info("=" * 60)

        # Step 1: Load indexes
        self._load_indexes()

        # Step 2: Download NetCDF files (with dedup: skip B- files listed in both indexes)
        if not skip_download:
            self._download_files(max_profiles)

        # Step 3: Parse NetCDF files (resumable via checkpoint)
        self._parse_files(max_profiles)

        # Step 3b: Merge Core+Bio profiles by (float_id, cycle_number)
        # so each logical profile appears once. This fixes double-counting
        # of BGC float cycles that have both a Core R-file and a Bio B-file.
        self._merge_profiles()

        # Step 4: Build float_registry (uses merged profile counts)
        self._build_float_registry()

        # Step 5: Build profile_index
        self._build_profile_index()

        # Step 6: Build levels
        self._build_levels()

        # Step 7: Build region_month_stats
        self._build_region_month_stats()

        # Summary
        t_end = time.perf_counter()
        logger.info("=" * 60)
        logger.info("Phase 2 Build Complete!")
        logger.info("  Duration:      %.1f seconds", t_end - t_start)
        logger.info("  Core dl'd:     %d", self.stats["core_downloaded"])
        logger.info("  BGC dl'd:      %d", self.stats["bio_downloaded"])
        logger.info("  Core failed:   %d", self.stats["core_failed"])
        logger.info("  BGC failed:    %d", self.stats["bio_failed"])
        logger.info("  Skipped (ckpt):%d", self.stats.get("skipped_checkpoint", 0))
        logger.info("  Unique floats: %d", len(self.stats["unique_floats"]))
        logger.info("  Total profs:   %d", self.stats["total_profiles"])
        logger.info("  Total levels:  %d", self.stats["total_levels"])
        logger.info("=" * 60)

        self._print_summary()

    # ── Step 1: Load indexes ───────────────────────────────────────── #

    def _load_indexes(self) -> None:
        logger.info("Step 1/7: Loading Argo indexes...")
        t0 = time.perf_counter()

        core_cache = self.cache_dir / "ar_index_global_prof.txt.gz"
        bio_cache = self.cache_dir / "argo_bio-profile_index.txt.gz"

        download_index(CORE_INDEX_URL, core_cache, "Core index")
        download_index(BIO_INDEX_URL, bio_cache, "Bio index")

        self.core_records = load_index_csv(core_cache)
        self.bio_records = load_index_csv(bio_cache)

        # Also scan the unfiltered indexes to get each float's global last
        # report date (anywhere in the world, not just India region).
        # This is used for accurate status classification: a float that has
        # drifted outside our region should be marked "drifted", not "inactive".
        self._scan_global_last_dates(core_cache, bio_cache)

        t1 = time.perf_counter()
        logger.info("  Core records (India bbox): %d", len(self.core_records))
        logger.info("  Bio records (India bbox):  %d", len(self.bio_records))
        logger.info("  Global dates scanned:      %d floats", len(self._global_last_dates))
        logger.info("  Index loading: %.1fs", t1 - t0)

    def _scan_global_last_dates(self, core_path: Path, bio_path: Path) -> None:
        """Stream through the unfiltered index to find each float's latest
        profile date globally (any ocean, any region).
        
        This is a lightweight streaming pass — we only store a dict of
        (float_id → max_date), not all rows. Memory: O(N_floats) ≈ 1,400.
        """
        for path, label in [(core_path, "Core"), (bio_path, "Bio")]:
            with gzip.open(path, "rt", errors="replace", newline="") as f:
                reader = csv.reader(f)
                for row in reader:
                    if not row or row[0].startswith("#") or row[0].startswith("file"):
                        continue
                    if len(row) < 8:
                        continue
                    try:
                        lat, lon = float(row[2]), float(row[3])
                    except (ValueError, IndexError):
                        continue
                    # NO bounding box filter here — we want ALL profiles globally
                    date_str = row[1].strip()
                    if len(date_str) < 8:
                        continue
                    try:
                        profile_date = datetime(
                            int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]),
                            int(date_str[8:10]) if len(date_str) > 8 else 0,
                            int(date_str[10:12]) if len(date_str) > 10 else 0,
                            int(date_str[12:14]) if len(date_str) > 12 else 0,
                            tzinfo=timezone.utc,
                        )
                    except (ValueError, IndexError):
                        continue
                    m_float = FLOAT_ID_RE.search(row[0])
                    if not m_float:
                        continue
                    fid = m_float.group(1)
                    if fid not in self._global_last_dates or profile_date > self._global_last_dates[fid]:
                        self._global_last_dates[fid] = profile_date

    # ── Step 2: Download NetCDF files (with deduplication) ─────────── #

    def _deduplicate_records(self) -> tuple[list[dict], list[dict]]:
        """Separate Core and Bio records for download.
        
        Analysis confirms:
        - Core index (India bbox): D- and R- files (161K + 37K) — NO B- files
        - Bio index (India bbox):  B- files (21K)
        
        These are disjoint file sets: Core D/R profiles and Bio B profiles
        are different files (even when they share the same float+cycle number,
        they measure different variables). No dedup needed across indexes.
        
        Returns:
            (core_records, bgc_records) — disjoint sets of file records.
        """
        core_records = list(self.core_records)
        bgc_records = list(self.bio_records)

        logger.info(
            "  Core records: %d (D- + R- files) | Bio records: %d (B- files) | Total: %d",
            len(core_records), len(bgc_records),
            len(core_records) + len(bgc_records),
        )
        return core_records, bgc_records

    def _download_files(self, max_profiles: int = 0) -> None:
        logger.info("Step 2/7: Downloading NetCDF files (deduplicated, resumable)...")
        t0 = time.perf_counter()

        core_records, bio_records = self._deduplicate_records()

        # Limit if testing
        if max_profiles > 0:
            half = max_profiles // 2
            core_records = core_records[:half]
            bio_records = bio_records[:max_profiles - half]

        logger.info("  Core (D-) files to download: %d", len(core_records))
        logger.info("  BGC (B-) files to download:  %d", len(bio_records))

        # Track which records are in the queue for parse step
        self._deduped_core = core_records
        self._deduped_bio = bio_records

        all_files = [(r, "core") for r in core_records] + [(r, "bgc") for r in bio_records]

        def _download_one(args: tuple[dict, str]) -> tuple[bool, str]:
            record, dtype = args
            dest_dir = self.raw_dir / dtype
            local = download_netcdf(record["file"], dest_dir)
            return (local is not None, dtype)

        with ThreadPoolExecutor(max_workers=self.download_workers) as executor:
            futures = {executor.submit(_download_one, (r, t)): (r, t) for r, t in all_files}
            progress = tqdm(total=len(futures), unit="files", desc="  Downloading", ncols=80)
            for future in as_completed(futures):
                try:
                    success, dtype = future.result()
                    if success:
                        self.stats["core_downloaded" if dtype == "core" else "bio_downloaded"] += 1
                    else:
                        self.stats["core_failed" if dtype == "core" else "bio_failed"] += 1
                except Exception:
                    pass
                progress.update(1)
            progress.close()

        t1 = time.perf_counter()
        elapsed = t1 - t0
        rate = len(futures) / elapsed if elapsed > 0 else 0
        logger.info("  Download: %.1fs | Core: %d ok, %d failed | BGC: %d ok, %d failed (%.1f files/sec)",
                    elapsed,
                    self.stats["core_downloaded"], self.stats["core_failed"],
                    self.stats["bio_downloaded"], self.stats["bio_failed"],
                    rate)

    # ── Step 3: Parse NetCDF files (resumable via checkpoint) ──────── #

    def _parse_files(self, max_profiles: int = 0) -> None:
        logger.info("Step 3/7: Parsing NetCDF files into tables (resumable)...")
        t0 = time.perf_counter()

        # Use deduped record lists from download step (or fall back to index if skipped)
        core_records = self._deduped_core if getattr(self, "_deduped_core", None) else self.core_records
        bio_records = self._deduped_bio if getattr(self, "_deduped_bio", None) else self.bio_records

        # If no records loaded yet (e.g. --skip-download with no prior download),
        # load from raw dir
        if not core_records and not bio_records:
            core_records = []
            bio_records = []
            for dtype, records_list in [("core", core_records), ("bgc", bio_records)]:
                pattern = self.raw_dir / dtype
                for nc_file in sorted(pattern.rglob("*.nc")):
                    rel = nc_file.relative_to(pattern)
                    m_fid = FLOAT_ID_RE.search(str(rel))
                    m_cyc = CYCLE_RE.search(str(rel))
                    if m_fid and m_cyc:
                        lat = 0.0
                        lon = 0.0
                        prof_date = datetime(2000, 1, 1, tzinfo=timezone.utc)
                        inst = ""
                        ptype = ""
                        dmode = "R"
                        
                        try:
                            import netCDF4
                            with netCDF4.Dataset(nc_file, "r") as ds:
                                if "LATITUDE" in ds.variables:
                                    val = ds.variables["LATITUDE"][0]
                                    if not np.isnan(val) and not np.ma.is_masked(val): lat = float(val)
                                if "LONGITUDE" in ds.variables:
                                    val = ds.variables["LONGITUDE"][0]
                                    if not np.isnan(val) and not np.ma.is_masked(val): lon = float(val)
                                if "JULD" in ds.variables:
                                    val = ds.variables["JULD"][0]
                                    if not np.isnan(val) and not np.ma.is_masked(val):
                                        prof_date = datetime(1950, 1, 1, tzinfo=timezone.utc) + pd.Timedelta(days=float(val))
                                
                                def _decode_char(var_name):
                                    if var_name in ds.variables:
                                        var = ds.variables[var_name]
                                        try:
                                            return netCDF4.chartostring(var[:])[0].strip()
                                        except Exception:
                                            try:
                                                data = var[:]
                                                if hasattr(data, "tobytes"):
                                                    return data.tobytes().decode("utf-8", "ignore").replace("\x00", "").strip()
                                            except Exception:
                                                pass
                                    return ""
                                
                                inst = getattr(ds, "INSTITUTION", _decode_char("INSTITUTION"))
                                ptype = getattr(ds, "PLATFORM_TYPE", _decode_char("PLATFORM_TYPE"))
                                dmode_char = _decode_char("DATA_MODE")
                                if dmode_char: dmode = dmode_char
                        except Exception as e:
                            logger.debug("Failed to extract metadata from %s: %s", nc_file, e)

                        records_list.append({
                            "file": str(rel),
                            "float_id": m_fid.group(1),
                            "cycle_number": int(m_cyc.group(1)),
                            "date": prof_date,
                            "latitude": lat,
                            "longitude": lon,
                            "institution": str(inst),
                            "profiler_type": str(ptype),
                            "parameter_data_mode": str(dmode),
                            "region_tag": _classify_region(lat, lon),
                        })

        # Flatten: (record, dtype) pairs
        all_records = [(r, "core") for r in core_records] + [(r, "bgc") for r in bio_records]

        if max_profiles > 0:
            all_records = all_records[:max_profiles]

        logger.info("  Profiles in queue: %d (checkpoint skipped: %d)",
                    len(all_records), len(self._checkpoint_done))

        progress = tqdm(total=len(all_records), unit="prof", desc="  Parsing", ncols=80)
        for idx, (record, dtype) in enumerate(all_records):

            float_id = record["float_id"]
            cycle_number = record["cycle_number"]
            key = (float_id, cycle_number, dtype)
            rel_path = record["file"]

            # ── Checkpoint: skip if already parsed ── #
            if key in self._checkpoint_done:
                self.stats["skipped_checkpoint"] += 1
                progress.update(1)
                continue

            # Determine local file path
            dest_dir = self.raw_dir / dtype
            nc_path = dest_dir / rel_path
            if not nc_path.exists():
                logger.debug("  Raw file not found: %s (maybe download failed earlier)", nc_path)
                continue

            try:
                raw_bytes = nc_path.read_bytes()
            except Exception:
                logger.debug("  Failed to read %s", nc_path)
                continue

            result = parse_netcdf_to_tables(rel_path, raw_bytes, record)
            if result["levels"].empty:
                logger.debug("  Empty levels for %s — skipping", rel_path)
                # Still checkpoint it to avoid re-parsing bad files
                self._save_checkpoint(float_id, cycle_number, dtype)
                self._checkpoint_done.add(key)
                continue

            self.stats["total_profiles"] += 1
            self.stats["total_levels"] += len(result["levels"])
            self.stats["unique_floats"].add(float_id)

            # Accumulate float metadata
            if float_id not in self.float_metadata:
                self.float_metadata[float_id] = result["float"]
            else:
                fm = self.float_metadata[float_id]
                fm["profile_count"] += 1
                if result["float"]["first_profile_date"] < fm["first_profile_date"]:
                    fm["first_profile_date"] = result["float"]["first_profile_date"]
                if result["float"]["last_profile_date"] > fm["last_profile_date"]:
                    fm["last_profile_date"] = result["float"]["last_profile_date"]

            # Accumulate profile records
            if result["profile"]:
                self.profile_records.append(result["profile"])

            # Accumulate levels
            self.levels_batches.append(result["levels"])

            # ── Save checkpoint ── #
            self._save_checkpoint(float_id, cycle_number, dtype)
            self._checkpoint_done.add(key)
            progress.update(1)

        progress.close()

        # Finalize float metadata
        for float_id in self.float_metadata:
            fm = self.float_metadata[float_id]
            float_profiles = [p for p in self.profile_records if p["float_id"] == float_id]
            all_vars = set()
            for p in float_profiles:
                for v in p["available_variables"].split():
                    all_vars.add(v)
            sensors = []
            if "TEMP" in all_vars:
                sensors.append("CTD")
            if "DOXY" in all_vars:
                sensors.append("OPTODE")
            if "CHLA" in all_vars:
                sensors.append("FLUOROMETER")
            if any("NITRATE" in v for v in all_vars):
                sensors.append("NITRATE_SENSOR")
            if any("BBP" in v for v in all_vars):
                sensors.append("BACKSCATTER")
            fm["sensors"] = ",".join(sensors) if sensors else "CTD"
            fm["profile_count"] = len(float_profiles)

        t1 = time.perf_counter()
        logger.info("  Parsing: %.1fs | %d profiles (+%d ckpt skipped), %d levels, %d unique floats",
                    t1 - t0, self.stats["total_profiles"], self.stats["skipped_checkpoint"],
                    self.stats["total_levels"], len(self.stats["unique_floats"]))

    # ── Step 3b: Merge Core+Bio profiles into logical profiles ─────── #

    def _merge_profiles(self) -> None:
        """Merge profile records by (float_id, cycle_number).

        A single Argo float cycle can produce TWO separate files:
        - A Core R/D-file (TEMP, PSAL, PRES from CTD)
        - A Bio B-file (DOXY, CHLA, etc. from bio-optical sensors)

        These represent ONE logical profile. 99.9% of Bio cycles have a
        matching Core entry for the same (float_id, cycle_number). Without
        merging, every BGC cycle is double-counted in the profile_index,
        inflating count-based queries like "how many profiles in region?".

        Merge strategy:
        - available_variables: union of both sources
        - data_mode: best available (D > A > R)
        - source_file: semicolon-joined list of both file paths
        - n_levels: max of both (Core and BGC may differ in vertical resolution)
        - lat/lon: prefer Core (more authoritative), fall back to Bio
        - date: prefer non-sentinel year, fall back to earliest
        - dac: prefer non-empty
        - region_tag: prefer specific over generic "indian_ocean"
        """
        if not self.profile_records:
            return

        _MODE_RANK = {"D": 0, "A": 1, "R": 2}
        merged: dict[tuple[str, int], dict] = {}

        for rec in self.profile_records:
            key = (rec["float_id"], rec["cycle_number"])

            if key not in merged:
                merged[key] = dict(rec)
                continue

            ex = merged[key]

            # Merge available variables
            ex_vars = set(ex["available_variables"].split())
            new_vars = set(rec["available_variables"].split())
            ex["available_variables"] = " ".join(sorted(ex_vars | new_vars))

            # Data mode — best rank wins
            if _MODE_RANK.get(rec["data_mode"], 3) < _MODE_RANK.get(ex["data_mode"], 3):
                ex["data_mode"] = rec["data_mode"]

            # Combine source files
            if rec["source_file"] not in ex["source_file"]:
                ex["source_file"] = ex["source_file"] + ";" + rec["source_file"]

            # Date: prefer real years over sentinel (2000)
            if ex["date"].year <= 2000 and rec["date"].year > 2000:
                ex["date"] = rec["date"]
                ex["year"] = rec["year"]
                ex["month"] = rec["month"]

            # Lat/lon: prefer non-zero values
            if abs(ex["latitude"]) < 0.01 and abs(rec["latitude"]) > 0.01:
                ex["latitude"] = rec["latitude"]
            if abs(ex["longitude"]) < 0.01 and abs(rec["longitude"]) > 0.01:
                ex["longitude"] = rec["longitude"]

            # n_levels: take max
            ex["n_levels"] = max(ex["n_levels"], rec["n_levels"])

            # dac: prefer non-empty
            if not ex["dac"] and rec["dac"]:
                ex["dac"] = rec["dac"]

            # region_tag: prefer specific over generic
            if ex["region_tag"] == "indian_ocean" and rec["region_tag"] != "indian_ocean":
                ex["region_tag"] = rec["region_tag"]

        pre = len(self.profile_records)
        self.profile_records = list(merged.values())
        post = len(self.profile_records)
        logger.info("  Profile merge: %d raw records → %d logical profiles (removed %d duplicates)",
                    pre, post, pre - post)

        # Also update float metadata profile_count to use merged counts
        for float_id in self.float_metadata:
            fm = self.float_metadata[float_id]
            fm["profile_count"] = sum(
                1 for p in self.profile_records if p["float_id"] == float_id
            )


    # ── Step 4: Build float_registry (with three-way status) ────────── #

    def _build_float_registry(self) -> None:
        """Build the float_registry table with three-way float status.

        Fields:
        - float_id: WMO float identifier
        - platform_type: Argo platform type code
        - institution: Data assembly centre
        - profiler_type: Profiler type code
        - region_tag: Primary operating region (within India scope)
        - sensors: Comma-separated list of inferred sensors
        - first_profile_date: Earliest in-region profile date
        - last_report_date: Date of float's LATEST in-region profile
        - last_global_report_date: Date of float's latest profile ANYWHERE
          in the world (from index, not just our downloaded data). This
          distinguishes "drifted away" from "actually dead."
        - profile_count: Total in-region profiles processed
        - status: One of three values:
          * "active" -- last_report_date within 365 days (float is
            currently reporting inside our region of interest)
          * "drifted" -- last_global_report_date within 365 days, but
            last in-region report is older or missing. The float is alive
            and reporting elsewhere, but has left our area of interest.
          * "inactive" -- no profile anywhere in the world for 365+
            days. Float is likely dead (battery depleted, stopped
            transmitting, or reached end of life).
          * "unknown" -- insufficient data to determine status.

        Status thresholds use the Argo program convention of 365 days.
        Status is recomputed fresh each ETL run.
        """
        logger.info("Step 4/7: Building float_registry table (three-way status)...")
        t0 = time.perf_counter()

        if not self.float_metadata:
            logger.warning("  No float metadata to write")
            return

        _REFERENCE_DATE = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        _THRESHOLD = self._INACTIVE_THRESHOLD_DAYS

        rows = []
        for fid, fm in self.float_metadata.items():
            last_in_region = fm.get("last_profile_date")
            first_report = fm.get("first_profile_date")
            last_global = self._global_last_dates.get(fid)

            # --- Three-way status logic ---
            # Days since last global report
            if last_global is not None:
                global_days = (_REFERENCE_DATE - last_global).days if isinstance(last_global, datetime) else (_REFERENCE_DATE.date() - last_global).days
            else:
                global_days = None
            # Days since last in-region report
            if last_in_region is not None:
                region_days = (_REFERENCE_DATE - last_in_region).days if isinstance(last_in_region, datetime) else (_REFERENCE_DATE.date() - last_in_region).days
            else:
                region_days = None

            # Determine status
            if global_days is not None:
                if global_days <= _THRESHOLD:
                    # Float has reported SOMEWHERE recently
                    status = "active" if (region_days is not None and region_days <= _THRESHOLD) else "drifted"
                else:
                    status = "inactive"  # no report anywhere in 365+ days
            elif region_days is not None and region_days <= _THRESHOLD:
                status = "active"
            else:
                status = "unknown"

            rows.append({
                "float_id": fid,
                "platform_type": str(fm.get("platform_type", "")),
                "institution": str(fm.get("institution", "")),
                "profiler_type": str(fm.get("profiler_type", "")),
                "region_tag": str(fm.get("region_tag", "")),
                "sensors": str(fm.get("sensors", "")),
                "first_profile_date": first_report,
                "last_report_date": last_in_region,
                "last_global_report_date": last_global,
                "profile_count": int(fm.get("profile_count", 0)),
                "status": status,
            })

        df = pd.DataFrame(rows)
        df = df.sort_values("float_id").reset_index(drop=True)

        output_dir = self.parquet_dir / "float_registry"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "float_registry.parquet"
        df.to_parquet(output_path, index=False, compression="snappy")

        status_counts = df["status"].value_counts().to_dict()
        logger.info("  float_registry: %d floats -> %s (%.1fs) | status: %s",
                    len(df), output_path, time.perf_counter() - t0,
                    dict(status_counts))

    # ── Step 5: Build profile_index (records already merged) ────────── #

    def _build_profile_index(self) -> None:
        """Build the profile_index table.

        Profile records are already merged by (float_id, cycle_number) in
        Step 3b (_merge_profiles), so this method simply writes them as
        partitioned Parquet. Each row represents ONE logical profile with
        all variables (Core + BGC) listed in available_variables.
        """
        logger.info("Step 5/7: Writing profile_index table (records already merged)...")
        t0 = time.perf_counter()

        if not self.profile_records:
            logger.warning("  No profile records to write")
            return

        df = pd.DataFrame(self.profile_records)
        df = df.sort_values(["year", "month", "float_id", "cycle_number"]).reset_index(drop=True)

        # Ensure correct dtypes
        df["year"] = df["year"].astype("int16")
        df["month"] = df["month"].astype("int8")
        df["cycle_number"] = df["cycle_number"].astype("int32")
        df["n_levels"] = df["n_levels"].astype("int32")
        df["latitude"] = df["latitude"].astype("float32")
        df["longitude"] = df["longitude"].astype("float32")

        # Write partitioned by year/month
        output_dir = self.parquet_dir / "profile_index"
        self._write_partitioned(df, output_dir, ["year", "month"])

        t1 = time.perf_counter()
        logger.info("  profile_index: %d profiles → %s (%.1fs)",
                    len(df), output_dir, t1 - t0)

    # ── Step 6: Build levels ─────────────────────────────────────────── #

    def _build_levels(self) -> None:
        logger.info("Step 6/7: Building levels table...")
        t0 = time.perf_counter()

        if not self.levels_batches:
            logger.warning("  No levels data to write")
            return

        combined = pd.concat(self.levels_batches, ignore_index=True)
        combined = combined.sort_values(
            ["year", "month", "float_id", "cycle_number", "pressure"]
        ).reset_index(drop=True)

        # Optimize dtypes
        combined["year"] = combined["year"].astype("int16")
        combined["month"] = combined["month"].astype("int8")
        combined["cycle_number"] = combined["cycle_number"].astype("int32")
        combined["pressure"] = combined["pressure"].astype("float32")
        combined["lat"] = combined["lat"].astype("float32")
        combined["lon"] = combined["lon"].astype("float32")

        for col in ["temp", "temp_adjusted", "psal", "psal_adjusted",
                     "doxy", "doxy_adjusted", "chla", "chla_adjusted",
                     "bbp700", "bbp700_adjusted",
                     "nitrate", "nitrate_adjusted",
                     "ph_in_situ_total", "ph_in_situ_total_adjusted",
                     "downwelling_par", "downwelling_par_adjusted"]:
            if col in combined.columns:
                combined[col] = combined[col].astype("float32")

        # Write partitioned by year/month
        output_dir = self.parquet_dir / "levels"
        self._write_partitioned(combined, output_dir, ["year", "month"])

        t1 = time.perf_counter()
        logger.info("  levels: %d rows → %s (%.1fs)",
                    len(combined), output_dir, t1 - t0)

    # ── Step 7: Build region_month_stats ─────────────────────────────── #

    def _build_region_month_stats(self) -> None:
        logger.info("Step 7/7: Building region_month_stats table...")
        t0 = time.perf_counter()

        if not self.profile_records:
            logger.warning("  No profiles to compute stats from")
            return

        df = pd.DataFrame(self.profile_records)
        # Aggregate by region, year, month
        stats_rows = []
        grouped = df.groupby(["region_tag", "year", "month"])
        for (region, yr, mo), grp in grouped:
            all_vars = set()
            for avail in grp["available_variables"]:
                for v in str(avail).split():
                    all_vars.add(v)

            core_vars = [v for v in all_vars if v in ("TEMP", "PSAL", "PRES")]
            bgc_vars = [v for v in all_vars if v not in ("TEMP", "PSAL", "PRES")]

            stats_rows.append({
                "region_tag": region,
                "year": int(yr),
                "month": int(mo),
                "total_profiles": len(grp),
                "unique_floats": grp["float_id"].nunique(),
                "core_profiles": len(grp) if core_vars else 0,
                "bgc_profiles": len(grp) if bgc_vars else 0,
                "variables_present": " ".join(sorted(all_vars)),
            })

        stats_df = pd.DataFrame(stats_rows)
        if stats_df.empty:
            logger.warning("  No stats to write")
            return

        stats_df["year"] = stats_df["year"].astype("int16")
        stats_df["month"] = stats_df["month"].astype("int8")

        output_dir = self.parquet_dir / "region_month_stats"
        self._write_partitioned(stats_df, output_dir, ["year"])

        t1 = time.perf_counter()
        logger.info("  region_month_stats: %d rows → %s (%.1fs)",
                    len(stats_df), output_dir, t1 - t0)

    # ── Helpers ─────────────────────────────────────────────────────── #

    def _write_partitioned(self, df: pd.DataFrame, output_dir: Path, partition_cols: list[str]) -> None:
        """Write a DataFrame as Hive-partitioned Parquet files."""
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError:
            logger.error("pyarrow is required for Parquet writing")
            raise

        table = pa.Table.from_pandas(df, preserve_index=False)
        pq.write_to_dataset(
            table,
            root_path=str(output_dir),
            partition_cols=partition_cols,
            compression="snappy",
        )

    def _print_summary(self) -> None:
        """Print a summary of all tables."""
        import duckdb

        conn = duckdb.connect(":memory:")
        conn.execute("SET memory_limit='1GB'")

        for tbl in ["float_registry", "profile_index", "levels", "region_month_stats"]:
            pattern = str(self.parquet_dir / tbl / "**" / "*.parquet")
            try:
                count = conn.execute(
                    f"SELECT COUNT(*) FROM read_parquet('{pattern}', hive_partitioning=true)"
                ).fetchone()[0]
                logger.info("  %s: %d rows", tbl, count)
            except Exception as e:
                logger.info("  %s: unable to read (%s)", tbl, e)

        conn.close()


# ── CLI ─────────────────────────────────────────────────────────────────── #

def main():
    parser = argparse.ArgumentParser(description="Phase 2: Build the full India-region Argo Data Lake")
    parser.add_argument(
        "--data-lake-dir",
        type=str,
        default=None,
        help="Root directory for the data lake (default: FLOATCHAT_DATA_LAKE_DIR or E:\\floatchat_data_lake\\)",
    )
    parser.add_argument(
        "--cache-dir",
        type=str,
        default=None,
        help="Cache directory for indexes (default: <data_lake_dir>/.cache)",
    )
    parser.add_argument(
        "--max-profiles",
        type=int,
        default=0,
        help="Maximum profiles to process (0 = all, use small number for testing)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of parallel download workers",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip download (use existing raw files for parsing)",
    )
    parser.add_argument(
        "--reset-checkpoint",
        action="store_true",
        help="Delete the checkpoint file and re-parse all raw files from scratch",
    )

    args = parser.parse_args()

    # Handle checkpoint reset
    if args.reset_checkpoint:
        ckpt_path = Path(args.data_lake_dir or os.environ.get("FLOATCHAT_DATA_LAKE_DIR", settings.data_lake_dir)) / ".checkpoint"
        if ckpt_path.exists():
            ckpt_path.unlink()
            logger.info("Checkpoint file deleted: %s", ckpt_path)
        else:
            logger.info("No checkpoint file to reset at: %s", ckpt_path)

    # Determine data lake dir: CLI arg > env var > default
    data_lake_dir = args.data_lake_dir or os.environ.get(
        "FLOATCHAT_DATA_LAKE_DIR",
        settings.data_lake_dir,
    )

    builder = Phase2DataLakeBuilder(
        data_lake_dir=data_lake_dir,
        cache_dir=args.cache_dir,
        download_workers=args.workers,
    )
    builder.run(max_profiles=args.max_profiles, skip_download=args.skip_download)


if __name__ == "__main__":
    main()
