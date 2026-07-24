"""Rebuild float_registry.parquet from the Phase 2 data lake.

Usage:
    python scripts/rebuild_float_registry.py --lake-root /path/to/lake

The lake root may also be supplied via the FLOATCHAT_DATA_LAKE_DIR
environment variable. No machine-specific default path is assumed.
"""

import argparse
import csv
import gzip
import os
import re
import sys
from datetime import datetime, timezone

import duckdb
import pandas as pd

FLOAT_ID_RE = re.compile(r"/(\d{7,})/")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--lake-root",
        default=os.environ.get("FLOATCHAT_DATA_LAKE_DIR", ""),
        help="Path to the Phase 2 data lake root (or set FLOATCHAT_DATA_LAKE_DIR).",
    )
    return parser.parse_args()


_args = _parse_args()
LAKE = _args.lake_root
if not LAKE:
    sys.exit(
        "error: no lake root provided. Pass --lake-root or set "
        "FLOATCHAT_DATA_LAKE_DIR."
    )

conn = duckdb.connect(":memory:")

# ----------------------------------------------------------------------
# 1. Read profile index
# ----------------------------------------------------------------------

pi = conn.execute(
    f"""
    SELECT float_id, date, region_tag
    FROM read_parquet(
        '{LAKE}/parquet/profile_index/**/*.parquet',
        hive_partitioning=true
    )
    """
).fetchdf()

pi["date"] = pd.to_datetime(pi["date"])

print(f"Loaded {len(pi):,} profile records")

# ----------------------------------------------------------------------
# 2. Build float metadata
# ----------------------------------------------------------------------

float_df = (
    pi.groupby("float_id")
    .agg(
        first_profile_date=("date", "min"),
        last_report_date=("date", "max"),
        profile_count=("float_id", "count"),
        region_tag=(
            "region_tag",
            lambda x: x.value_counts().index[0]
            if len(x.value_counts()) > 0
            else "indian_ocean",
        ),
    )
    .reset_index()
)

# ----------------------------------------------------------------------
# 3. Scan global index files for latest report date
# ----------------------------------------------------------------------

global_dates = {}

index_files = [
    f"{LAKE}/.cache/ar_index_global_prof.txt.gz",
    f"{LAKE}/.cache/argo_bio-profile_index.txt.gz",
]

for path in index_files:
    print(f"Scanning {path}...")

    with gzip.open(path, "rt", errors="replace", newline="") as f:
        reader = csv.reader(f)

        for row in reader:
            if not row:
                continue

            if row[0].startswith("#") or row[0].startswith("file"):
                continue

            if len(row) < 8:
                continue

            match = FLOAT_ID_RE.search(row[0])
            if match is None:
                continue

            float_id = match.group(1)

            ds = row[1].strip()

            if len(ds) < 8:
                continue

            try:
                d = datetime(
                    int(ds[:4]),
                    int(ds[4:6]),
                    int(ds[6:8]),
                    tzinfo=timezone.utc,
                )

                if (
                    float_id not in global_dates
                    or d > global_dates[float_id]
                ):
                    global_dates[float_id] = d

            except Exception:
                pass

print(f"Scanned {len(global_dates):,} floats globally")

float_df["last_global_report_date"] = float_df["float_id"].map(global_dates)

# ----------------------------------------------------------------------
# 4. Compute status
# ----------------------------------------------------------------------

REF = datetime.now(timezone.utc).replace(
    hour=0,
    minute=0,
    second=0,
    microsecond=0,
)

THRESHOLD_DAYS = 365


def compute_status(row):
    global_date = row["last_global_report_date"]
    regional_date = row["last_report_date"]

    if pd.notna(global_date):
        global_age = (REF - global_date).days

        if global_age <= THRESHOLD_DAYS:

            if pd.notna(regional_date):
                regional_age = (REF - regional_date).days

                if regional_age <= THRESHOLD_DAYS:
                    return "active"
                else:
                    return "drifted"

            return "drifted"

        return "inactive"

    if pd.notna(regional_date):
        regional_age = (REF - regional_date).days

        if regional_age <= THRESHOLD_DAYS:
            return "active"

        return "inactive"

    return "unknown"


float_df["status"] = float_df.apply(compute_status, axis=1)

# ----------------------------------------------------------------------
# 5. Additional metadata
# ----------------------------------------------------------------------

float_df["platform_type"] = ""
float_df["institution"] = ""
float_df["profiler_type"] = ""
float_df["sensors"] = ""
# Phase 5 Part A: manufacturer column for float metadata expansion
float_df["manufacturer"] = ""

# ----------------------------------------------------------------------
# 6. Save registry
# ----------------------------------------------------------------------

out = float_df[
    [
        "float_id",
        "platform_type",
        "institution",
        "profiler_type",
        "region_tag",
        "sensors",
        "first_profile_date",
        "last_report_date",
        "last_global_report_date",
        "profile_count",
        "status",
        "manufacturer",
    ]
].sort_values("float_id")

output_path = (
    f"{LAKE}/parquet/float_registry/float_registry.parquet"
)

out.to_parquet(
    output_path,
    index=False,
    compression="snappy",
)

print(f"\nWritten {len(out):,} floats")
print("Status counts:")
print(out["status"].value_counts().to_dict())
print("\n✅ Done! OpenAPI will now show drifted floats correctly.")