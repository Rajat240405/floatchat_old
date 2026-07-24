"""Check which expected variables exist in the lake levels Parquet schema.

Usage:
    python scripts/check_schema.py --parquet-root /path/to/lake/parquet/levels

If --parquet-root is omitted, the script uses
$FLOATCHAT_DATA_LAKE_DIR/parquet/levels when FLOATCHAT_DATA_LAKE_DIR is set.
No machine-specific default path is assumed.
"""

import argparse
import os
import sys

import pyarrow.parquet as pq

wanted = [
    "bbp700",
    "nitrate",
    "ph_in_situ_total",
    "par",
    "pressure",
    "temp",
    "psal",
    "doxy",
    "chla",
]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--parquet-root",
        default="",
        help="Path to the levels Parquet root.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    parquet_root = args.parquet_root
    if not parquet_root:
        lake_dir = os.environ.get("FLOATCHAT_DATA_LAKE_DIR", "")
        if lake_dir:
            parquet_root = os.path.join(lake_dir, "parquet", "levels")
    if not parquet_root:
        sys.exit(
            "error: no parquet root provided. Pass --parquet-root or set "
            "FLOATCHAT_DATA_LAKE_DIR."
        )

    columns = set()

    for root, _, files in os.walk(parquet_root):
        for f in files:
            if f.endswith(".parquet"):
                schema = pq.read_schema(os.path.join(root, f))
                columns.update(c.lower() for c in schema.names)

    print("\nColumn check:")
    for c in wanted:
        print(f"{c:20} {'FOUND' if c in columns else 'NOT FOUND'}")


if __name__ == "__main__":
    main()
