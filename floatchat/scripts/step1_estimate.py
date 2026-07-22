#!/usr/bin/env python3
"""
Phase 2, Step 1: Estimate — CSV streaming analysis.
"""

import csv
import gzip
import logging
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# India bounding box (same as metadata_service/regions.py)
INDIA_LAT_MIN = -10.0
INDIA_LAT_MAX = 30.0
INDIA_LON_MIN = 40.0
INDIA_LON_MAX = 100.0

# Average compressed NetCDF file sizes for estimation
AVG_CORE_FILE_SIZE_MB = 0.15   # 150 KB
AVG_BGC_FILE_SIZE_MB = 0.40    # 400 KB

CACHE_DIR = Path(__file__).parent.parent / ".cache"


def count_profiles(path: Path, is_core: bool) -> dict:
    """Stream-read a GDAC index CSV and filter to India bbox."""
    label = "Core" if is_core else "Bio"
    logger.info("Analyzing %s index (streaming CSV)...", label)

    total = 0
    india_count = 0
    floats_india = set()
    years_india = Counter()
    year_min = 9999
    year_max = 0

    with gzip.open(path, "rt", errors="replace") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or row[0].startswith("#") or row[0].startswith("file"):
                continue

            total += 1

            if total % 500000 == 0:
                logger.info("  %s: processed %d rows, India match: %d", label, total, india_count)

            if is_core:
                # file,date,latitude,longitude,ocean,profiler_type,institution,date_update
                if len(row) < 8:
                    continue
                file_path = row[0]
                date_str = row[1].strip()
                try:
                    lat = float(row[2])
                    lon = float(row[3])
                except (ValueError, IndexError):
                    continue
            else:
                # file,date,latitude,longitude,ocean,profiler_type,institution,parameters,parameter_data_mode,date_update
                if len(row) < 10:
                    continue
                file_path = row[0]
                date_str = row[1].strip()
                try:
                    lat = float(row[2])
                    lon = float(row[3])
                except (ValueError, IndexError):
                    continue

            # Filter to India bbox
            if not (INDIA_LAT_MIN <= lat <= INDIA_LAT_MAX and
                    INDIA_LON_MIN <= lon <= INDIA_LON_MAX):
                continue

            india_count += 1

            # Extract year from YYYYMMDDHHMMSS
            if not date_str or len(date_str) < 4:
                continue
            try:
                year = int(date_str[:4])
            except ValueError:
                continue
            years_india[year] += 1
            if year < year_min:
                year_min = year
            if year > year_max:
                year_max = year

            # Extract float ID
            m = re.search(r"/(\d{7,})/", file_path)
            if m:
                floats_india.add(m.group(1))

    logger.info("  %s: DONE — total=%d, india=%d, floats=%d, years=%d-%d",
                label, total, india_count, len(floats_india), year_min, year_max)

    return {
        "label": label,
        "total_world": total,
        "total_india_box": india_count,
        "unique_floats": len(floats_india),
        "year_min": year_min,
        "year_max": year_max,
        "by_year": dict(sorted(years_india.items())),
    }


def main():
    t_start = time.perf_counter()

    print()
    print("=" * 70)
    print("  PHASE 2, STEP 1 — DOWNLOAD ESTIMATE")
    print("=" * 70)
    print()

    core_path = CACHE_DIR / "ar_index_global_prof.txt.gz"
    bio_path = CACHE_DIR / "argo_bio-profile_index.txt.gz"

    for p, label in [(core_path, "Core"), (bio_path, "Bio")]:
        if not p.exists():
            print(f"ERROR: {label} index not found at {p}")
            sys.exit(1)
        print(f"  {label} index: {p.name} ({p.stat().st_size / 1024 / 1024:.1f} MB)")

    print()

    print("[1/2] Analyzing Core index (streaming)...")
    t0 = time.perf_counter()
    core = count_profiles(core_path, is_core=True)
    t1 = time.perf_counter()
    print(f"  → Core analysis: {t1 - t0:.1f}s")
    print()

    print("[2/2] Analyzing Bio index (streaming)...")
    t0 = time.perf_counter()
    bio = count_profiles(bio_path, is_core=False)
    t1 = time.perf_counter()
    print(f"  → Bio analysis: {t1 - t0:.1f}s")
    print()

    # ── Print estimate ────────────────────────────────────────────── #
    total_core = core["total_india_box"]
    total_bio = bio["total_india_box"]
    total_profiles = total_core + total_bio

    core_size_mb = total_core * AVG_CORE_FILE_SIZE_MB
    bio_size_mb = total_bio * AVG_BGC_FILE_SIZE_MB
    total_size_mb = core_size_mb + bio_size_mb
    total_size_gb = total_size_mb / 1024

    print("=" * 70)
    print("  BULK DOWNLOAD ESTIMATE")
    print("=" * 70)
    print()
    print(f"  Region scope:   India region (bbox -10..30N, 40..100E)")
    print(f"  Includes:       Arabian Sea + Bay of Bengal + N. Indian Ocean")
    print()

    print(f"  {'─' * 60}")
    print(f"  {'Dataset':<20} {'Profiles':>15} {'Floats':>12}")
    print(f"  {'─' * 60}")
    print(f"  {'Core (TEMP/PSAL/PRES)':<20} {total_core:>15,d} {core['unique_floats']:>12,d}")
    print(f"  {'BGC (DOXY/CHLA/etc.)':<20} {total_bio:>15,d} {bio['unique_floats']:>12,d}")
    print(f"  {'─' * 60}")
    print(f"  {'TOTAL':<20} {total_profiles:>15,d}")
    print()

    print(f"  Estimated download size (compressed NetCDF):")
    print(f"    Core: {total_core:,d} × {AVG_CORE_FILE_SIZE_MB*1024:.0f} KB = {core_size_mb:,.0f} MB")
    print(f"    BGC:  {total_bio:,d} × {AVG_BGC_FILE_SIZE_MB*1024:.0f} KB = {bio_size_mb:,.0f} MB")
    print(f"    ───────────────────────────────────────────────")
    print(f"    TOTAL: {total_profiles:,d} profiles ≈ {total_size_mb:,.0f} MB ({total_size_gb:.2f} GB)")
    print()

    print(f"  Estimated Parquet storage (typically 30-50% of uncompressed NetCDF):")
    raw_gb = total_size_gb * 3  # Uncompressed ~3x compressed
    print(f"    Raw uncompressed: ~{raw_gb:.2f} GB")
    print(f"    Parquet (est.):   ~{raw_gb * 0.35:.2f} GB")
    print()

    print(f"  Year-by-year breakdown:")
    print(f"  {'─' * 50}")
    print(f"  {'Year':>6} {'Core Profiles':>16} {'BGC Profiles':>16}")
    print(f"  {'─' * 50}")

    all_years = sorted(set(core["by_year"].keys()) | set(bio["by_year"].keys()))
    for y in all_years:
        c = core["by_year"].get(y, 0)
        b = bio["by_year"].get(y, 0)
        print(f"  {y:>6} {c:>16,d} {b:>16,d}")
    print(f"  {'─' * 50}")
    print()

    year_range_core = f"{core['year_min']}–{core['year_max']}" if core['year_min'] <= core['year_max'] else "N/A"
    year_range_bio = f"{bio['year_min']}–{bio['year_max']}" if bio['year_min'] <= bio['year_max'] else "N/A"
    print(f"  Year range:  Core: {year_range_core}  |  BGC: {year_range_bio}")
    print()

    for label, mbps in [("50 Mbps", 50), ("100 Mbps", 100), ("200 Mbps", 200)]:
        mins = (total_size_mb * 8 / mbps) / 60
        print(f"  Est. download at {label}: ~{mins:.1f} min")

    print(f"\n  Est. ETL processing (approx 0.5s/profile Core, 1.0s/profile BGC):")
    core_etl_min = total_core * 0.5 / 60
    bio_etl_min = total_bio * 1.0 / 60
    print(f"    Core: ~{core_etl_min:.1f} min | BGC: ~{bio_etl_min:.1f} min | TOTAL: ~{(core_etl_min + bio_etl_min):.1f} min")
    print()

    t_end = time.perf_counter()
    print(f"  Analysis completed in {t_end - t_start:.1f} seconds.")
    print("=" * 70)
    print()

    return core, bio


if __name__ == "__main__":
    main()
