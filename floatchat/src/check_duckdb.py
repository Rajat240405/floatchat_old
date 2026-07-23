import duckdb

conn = duckdb.connect()
res = conn.execute("""
SELECT
COUNT(*) total,
COUNT(latitude),
COUNT(longitude),
SUM(CASE WHEN latitude=0 AND longitude=0 THEN 1 ELSE 0 END),
MIN(latitude),
MAX(latitude),
MIN(longitude),
MAX(longitude)
FROM read_parquet('E:/floatchat_data_lake/parquet/profile_index/**/*.parquet', hive_partitioning=true);
""").fetchall()

print(res)
