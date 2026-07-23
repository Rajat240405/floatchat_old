import os
import pyarrow.parquet as pq

PARQUET_ROOT = r"E:\floatchat_data_lake\parquet\levels"

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

columns = set()

for root, _, files in os.walk(PARQUET_ROOT):
    for f in files:
        if f.endswith(".parquet"):
            schema = pq.read_schema(os.path.join(root, f))
            columns.update(c.lower() for c in schema.names)

print("\nColumn check:")
for c in wanted:
    print(f"{c:20} {'FOUND' if c in columns else 'NOT FOUND'}")