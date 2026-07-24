"""Sanity-check coordinates in the Phase 2 profile_index table.

Usage:
    python scripts/check_duckdb.py --lake-root /path/to/lake

The lake root may also be supplied via the FLOATCHAT_DATA_LAKE_DIR
environment variable. No machine-specific default path is assumed.
"""

import argparse
import os
import sys

import duckdb


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--lake-root",
        default=os.environ.get("FLOATCHAT_DATA_LAKE_DIR", ""),
        help="Path to the Phase 2 data lake root (or set FLOATCHAT_DATA_LAKE_DIR).",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if not args.lake_root:
        sys.exit(
            "error: no lake root provided. Pass --lake-root or set "
            "FLOATCHAT_DATA_LAKE_DIR."
        )

    conn = duckdb.connect(":memory:")
    res = conn.execute(
        f"""
        SELECT
        COUNT(*) total,
        COUNT(latitude),
        COUNT(longitude),
        SUM(CASE WHEN latitude=0 AND longitude=0 THEN 1 ELSE 0 END),
        MIN(latitude),
        MAX(latitude),
        MIN(longitude),
        MAX(longitude)
        FROM read_parquet('{args.lake_root}/parquet/profile_index/**/*.parquet',
                          hive_partitioning=true);
        """
    ).fetchall()

    print(res)


if __name__ == "__main__":
    main()
