"""DuckDB + Parquet implementation of the local data lake.

Phase 1: Walking skeleton that reads pre-ingested Argo level-by-level
data from partitioned Parquet files and serves queries via DuckDB SQL.

Priority 1C: Canonical variable resolver — prefers _ADJUSTED columns when
they contain valid (non-NULL, non-NaN) data, falls back to raw columns.

Priority 1D: Availability probing for zero-result explanations.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from floatchat.data_lake.base import (
    AbstractDataLake,
    LakeQueryCriteria,
    LakeQueryResult,
)
from floatchat.metadata_service.polygons import point_in_region

logger = logging.getLogger(__name__)

# Default root for Parquet partitions.
_DEFAULT_LAKE_ROOT = Path(
    os.environ.get("FLOATCHAT_DATA_LAKE_ROOT", ".data_lake/parquet")
)

# ── Priority 1C: Canonical Variable Resolver ────────────────────────────── #
# Maps canonical Argo variable names → (adjusted_col, raw_col, units).
# The resolver prefers _ADJUSTED when it has valid data (non-NULL, non-NaN),
# falling back to the raw column otherwise.
# Column names must match the actual Parquet schema produced by phase2_builder.
_LAKE_VARIABLES: dict[str, tuple[str, str, str]] = {
    "TEMP": ("temp_adjusted", "temp", "degree_Celsius"),
    "PSAL": ("psal_adjusted", "psal", "psu"),
    "DOXY": ("doxy_adjusted", "doxy", "umol/kg"),
    "CHLA": ("chla_adjusted", "chla", "mg/m^3"),
}


def _variable_presence_filter(var: str) -> str:
    """Build a DuckDB WHERE clause fragment that checks for valid (non-NULL,
    non-NaN) data for a given canonical variable.

    Priority 1C: NaN values are stored by the ETL for missing measurements.
    DuckDB treats NaN ≠ NULL, so a simple ``IS NOT NULL`` is insufficient.
    We must also exclude NaN values.
    """
    col_info = _LAKE_VARIABLES.get(var.upper())
    if not col_info:
        return "1=1"
    adj_col, raw_col, _ = col_info
    return (
        f"(({adj_col} IS NOT NULL AND NOT isnan({adj_col})) "
        f"OR ({raw_col} IS NOT NULL AND NOT isnan({raw_col})))"
    )


def _month_filter(
    month: int | None,
    months: list[int] | None,
) -> tuple[str, list[int]] | None:
    """P3 #3: Build a month WHERE-clause fragment honoring a season window.

    A season window (``months``) takes precedence over the single ``month``.
    Returns ``(sql_fragment, params)`` or ``None`` when no month filter applies.

    Examples:
        month=6, months=None       -> ('month = ?', [6])
        month=6, months=[6,7,8,9]  -> ('month IN (?, ?, ?, ?)', [6,7,8,9])
        month=None, months=[12,1,2]-> ('month IN (?, ?, ?)', [12,1,2])
    """
    if months:
        uniq: list[int] = []
        for m in months:
            try:
                mi = int(m)
            except (TypeError, ValueError):
                continue
            if 1 <= mi <= 12 and mi not in uniq:
                uniq.append(mi)
        if not uniq:
            return None
        placeholders = ", ".join("?" for _ in uniq)
        return f"month IN ({placeholders})", uniq
    if month is not None:
        return "month = ?", [int(month)]
    return None


def _resolve_variable_column(df: pd.DataFrame, var: str) -> tuple[pd.Series, str]:
    """Resolve the best available column for a canonical variable.

    Priority 1C: Returns (series, column_name).
    Prefers the _ADJUSTED column when it has valid (non-NaN) data;
    falls back to the raw column otherwise.
    """
    col_info = _LAKE_VARIABLES.get(var.upper())
    if not col_info:
        # Unknown variable — try direct column lookup
        if var in df.columns:
            return pd.to_numeric(df[var], errors="coerce"), var
        return pd.Series(dtype=float), var

    adj_col, raw_col, _ = col_info
    if adj_col in df.columns:
        adj_series = pd.to_numeric(df[adj_col], errors="coerce")
        if adj_series.notna().any():
            return adj_series, adj_col
    if raw_col in df.columns:
        raw_series = pd.to_numeric(df[raw_col], errors="coerce")
        if raw_series.notna().any():
            return raw_series, raw_col
    # Last resort: return adjusted column even if all NaN
    if adj_col in df.columns:
        return pd.to_numeric(df[adj_col], errors="coerce"), adj_col
    if raw_col in df.columns:
        return pd.to_numeric(df[raw_col], errors="coerce"), raw_col
    return pd.Series(dtype=float), var


class DuckDBDataLake(AbstractDataLake):
    """DuckDB-backed Parquet data lake for Argo profile queries.

    Phase 1: Serves region-level TEMP/PSAL/DOXY/CHLA queries from
    pre-ingested Indian Ocean (Arabian Sea + Bay of Bengal) data.

    Phase 2: Full India-region data lake with 4 tables:
    - levels (level-by-level measurements, partitioned by year/month)
    - profile_index (one row per profile, partitioned by year/month)
    - float_registry (one row per float metadata)
    - region_month_stats (precomputed aggregates, partitioned by year)

    Priority 1: All data queries go through DuckDB exclusively.
    Remote GDAC fallback is controlled by FLOATCHAT_ALLOW_REMOTE_GDAC_FALLBACK.
    """

    def __init__(
        self,
        lake_root: Path | str | None = None,
        phase2_root: Path | str | None = None,
        use_phase2: bool = False,
    ) -> None:
        # Phase 1 root (levels table)
        self._lake_root = Path(lake_root or _DEFAULT_LAKE_ROOT)
        # Phase 2 root (E:\\floatchat_data_lake\\ or similar)
        self._phase2_root = Path(phase2_root) if phase2_root else None
        self._use_phase2 = use_phase2 and self._phase2_root is not None
        if self._use_phase2:
            # Point to the Phase 2 levels table
            self._lake_root = self._phase2_root / "parquet" / "levels"
            logger.info("DuckDBDataLake: Phase 2 mode, levels root = %s", self._lake_root)

            # Verify at least the directory exists (files may not exist yet)
            if not self._lake_root.exists():
                logger.warning("Phase 2 levels directory does not exist: %s", self._lake_root)

        self._conn: Any = None  # duckdb.DuckDBPyConnection — set lazily
        self._availability_cache: dict[str, Any] | None = None

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def query(self, criteria: LakeQueryCriteria) -> LakeQueryResult:
        """Execute a structured query against the Parquet lake via DuckDB."""
        if not self.is_available():
            logger.warning("Data lake not available; returning empty result")
            return LakeQueryResult(df=pd.DataFrame())

        conn = self._get_connection()
        df = self._execute_query(criteria, conn)
        return self._build_result(df, criteria)

    def is_available(self) -> bool:
        """Check whether the Parquet lake exists and has at least one file."""
        if not self._lake_root.exists():
            return False
        parquet_files = list(self._lake_root.rglob("*.parquet"))
        return len(parquet_files) > 0

    def get_region_tag(self, lat: float, lon: float) -> str | None:
        """Classify a coordinate into Indian Ocean sub-region."""
        if point_in_region(lon, lat, "arabian_sea"):
            return "arabian_sea"
        if point_in_region(lon, lat, "bay_of_bengal"):
            return "bay_of_bengal"
        return None

    def list_available_years(self) -> list[int]:
        """Return years that have Parquet partitions."""
        if not self.is_available():
            return []
        try:
            conn = self._get_connection()
            pattern = (self._lake_root / "**" / "*.parquet").as_posix()
            result = conn.execute(
                f"SELECT DISTINCT year FROM read_parquet('{pattern}', hive_partitioning=true) "
                "GROUP BY year ORDER BY year"
            ).fetchall()
            return [row[0] for row in result]
        except Exception:
            return []

    # ── Priority 1D: Availability probing ────────────────────────────── #

    def probe_availability(self, variables: list[str] | None = None) -> dict[str, Any]:
        """Probe what data is actually available in the lake.

        Returns a dict with:
          - available_years: list of years with data
          - available_regions: list of regions with data
          - variable_coverage: {var: {region: [years]}}
        Used for zero-result explanations.
        """
        if self._availability_cache is not None:
            return self._availability_cache

        if not self.is_available():
            return {
                "available_years": [],
                "available_regions": [],
                "variable_coverage": {},
            }

        try:
            conn = self._get_connection()
            parquet_pattern = (self._lake_root / "**" / "*.parquet").as_posix()

            # General year/region availability
            yr_result = conn.execute(
                f"SELECT DISTINCT year FROM read_parquet('{parquet_pattern}', hive_partitioning=true) ORDER BY year"
            ).fetchall()
            available_years = [r[0] for r in yr_result]

            reg_result = conn.execute(
                f"SELECT DISTINCT region_tag FROM read_parquet('{parquet_pattern}', hive_partitioning=true) WHERE region_tag IS NOT NULL ORDER BY region_tag"
            ).fetchall()
            available_regions = [r[0] for r in reg_result]

            # Per-variable availability
            variable_coverage: dict[str, dict[str, list[int]]] = {}
            vars_to_check = variables or list(_LAKE_VARIABLES.keys())
            for var in vars_to_check:
                var_upper = var.upper()
                var_filter = _variable_presence_filter(var_upper)
                var_result = conn.execute(
                    f"SELECT region_tag, year, COUNT(DISTINCT float_id || '-' || cycle_number) as n_profiles "
                    f"FROM read_parquet('{parquet_pattern}', hive_partitioning=true) "
                    f"WHERE {var_filter} "
                    f"GROUP BY region_tag, year ORDER BY region_tag, year"
                ).fetchall()
                coverage: dict[str, list[int]] = {}
                for region_tag, year, _count in var_result:
                    coverage.setdefault(region_tag, []).append(year)
                variable_coverage[var_upper] = coverage

            self._availability_cache = {
                "available_years": available_years,
                "available_regions": available_regions,
                "variable_coverage": variable_coverage,
            }
            return self._availability_cache
        except Exception as exc:
            logger.warning("Availability probe failed: %s", exc)
            return {
                "available_years": [],
                "available_regions": [],
                "variable_coverage": {},
            }

    def build_zero_result_message(
        self,
        criteria: LakeQueryCriteria,
    ) -> str:
        """Priority 1D: Build a helpful zero-result explanation message.

        Instead of a generic "No data found", returns precise availability
        information and clickable suggestion chips.
        """
        availability = self.probe_availability(criteria.variables or None)
        var_coverage = availability.get("variable_coverage", {})
        available_years = availability.get("available_years", [])

        # Build human-readable variable name
        var_name_map = {
            "TEMP": "temperature",
            "PSAL": "salinity",
            "DOXY": "dissolved oxygen",
            "CHLA": "chlorophyll",
        }
        var_desc = ", ".join(var_name_map.get(v, v) for v in (criteria.variables or []))
        if not var_desc:
            var_desc = "data"

        # Region description
        region_desc = criteria.region.replace("_", " ").title() if criteria.region else "the requested area"
        year_desc = f" for {criteria.year}" if criteria.year else ""

        # Build availability info
        parts = [f"No {var_desc} profiles found in {region_desc}{year_desc} in the local data lake."]

        # Check what IS available for the requested variables
        suggestions: list[str] = []
        for var in (criteria.variables or []):
            var_upper = var.upper()
            cov = var_coverage.get(var_upper, {})
            var_label = var_name_map.get(var_upper, var_upper)
            if cov:
                available_info = []
                for region, years in cov.items():
                    region_label = region.replace("_", " ").title()
                    year_range = f"{min(years)}-{max(years)}" if len(years) > 1 else str(years[0])
                    available_info.append(f"{region_label} {year_range}")
                parts.append(f"{var_label} data is available for: {'; '.join(available_info)}.")

                # Generate suggestion chips
                for region, years in cov.items():
                    region_label = region.replace("_", " ").title()
                    # Suggest the nearest available year
                    if criteria.year:
                        nearest_year = min(years, key=lambda y: abs(y - criteria.year))
                        suggestions.append(f"{var_label} in {region_label} {nearest_year}")
                    else:
                        suggestions.append(f"{var_label} in {region_label}")
            else:
                parts.append(f"No {var_label} data found anywhere in the local data lake.")

        if suggestions:
            parts.append("\nSuggestions:")
            for s in suggestions[:4]:
                parts.append(f"  • {s}")

        return "\n".join(parts)

    def get_map_markers(self, criteria: LakeQueryCriteria) -> list[dict[str, Any]]:
        """Return all unique float locations matching criteria without profile limits."""
        if not self.is_available():
            return []
        try:
            conn = self._get_connection()
            where_parts: list[str] = []
            params: list[Any] = []

            def _add(cond: str, val: Any) -> None:
                where_parts.append(cond)
                params.append(val)

            if criteria.year is not None:
                _add("year = ?", criteria.year)
            # P3 #3: season window takes precedence over single month.
            _mf = _month_filter(criteria.month, criteria.months)
            if _mf is not None:
                cond, mvals = _mf
                where_parts.append(cond)
                params.extend(mvals)
            if criteria.region:
                _add("region_tag = ?", criteria.region)
            if criteria.lat_min is not None:
                _add("lat >= ?", criteria.lat_min)
            if criteria.lat_max is not None:
                _add("lat <= ?", criteria.lat_max)
            if criteria.lon_min is not None:
                _add("lon >= ?", criteria.lon_min)
            if criteria.lon_max is not None:
                _add("lon <= ?", criteria.lon_max)

            # Priority 1C: NaN-safe variable presence filters
            requested_vars = [v.upper() for v in criteria.variables]
            for var in requested_vars:
                where_parts.append(_variable_presence_filter(var))

            where_clause = " AND ".join(where_parts) if where_parts else "1=1"
            parquet_pattern = (self._lake_root / "**" / "*.parquet").as_posix()

            sql = (
                f"SELECT\n"
                f"    float_id,\n"
                f"    arg_max(lat, date) AS lat,\n"
                f"    arg_max(lon, date) AS lon,\n"
                f"    max(date) AS profile_date,\n"
                f"    arg_max(dac, date) AS dac\n"
                f"FROM read_parquet('{parquet_pattern}', hive_partitioning=true)\n"
                f"WHERE {where_clause}\n"
                f"GROUP BY float_id\n"
                f"ORDER BY profile_date DESC\n"
                f"LIMIT 5000"
            )
            result = conn.execute(sql, params).fetchall()
            return [
                {
                    "float_id": str(row[0]),
                    "lat": float(row[1]) if row[1] is not None else None,
                    "lon": float(row[2]) if row[2] is not None else None,
                    "profile_date": str(row[3]) if row[3] is not None else None,
                    "dac": str(row[4] or ""),
                }
                for row in result
            ]
        except Exception as exc:
            logger.warning("Failed to query map markers from DuckDB: %s", exc)
            return []

    def get_stats(self, criteria: LakeQueryCriteria) -> dict[str, Any]:
        """Convenience wrapper: query and return pre-computed stats dict."""
        result = self.query(criteria)
        return result.stats

    def _get_connection(self) -> Any:
        """Lazily create and cache the DuckDB connection."""
        if self._conn is None:
            import duckdb

            self._conn = duckdb.connect(database=":memory:")
            logger.info("DuckDB in-memory connection created for data lake")
        return self._conn

    def _execute_query(
        self,
        criteria: LakeQueryCriteria,
        conn: Any,
    ) -> pd.DataFrame:
        """Translate LakeQueryCriteria into DuckDB SQL and execute.

        DuckDB requires glob patterns as string literals in SQL, not as
        bound parameters. We build the query with f-string interpolation
        for the glob path (safe: it's a local filesystem path) and use
        positional parameters (?) for all dynamic WHERE conditions.

        Priority 1A: No max_profiles=5 cap. LIMIT is set by
        data_lake_max_profiles (default 100), not the legacy 5-profile cap.

        Priority 1C: NaN-safe variable presence filters.
        """
        # Build WHERE conditions as (clause, value) pairs
        where_parts: list[str] = []
        params: list[Any] = []

        def _add(cond: str, val: Any) -> None:
            where_parts.append(cond)
            params.append(val)

        if criteria.year is not None:
            _add("year = ?", criteria.year)
        # P3 #3: season window takes precedence over single month.
        _mf = _month_filter(criteria.month, criteria.months)
        if _mf is not None:
            cond, mvals = _mf
            where_parts.append(cond)
            params.extend(mvals)
        if criteria.region:
            _add("region_tag = ?", criteria.region)
        if criteria.lat_min is not None:
            _add("lat >= ?", criteria.lat_min)
        if criteria.lat_max is not None:
            _add("lat <= ?", criteria.lat_max)
        if criteria.lon_min is not None:
            _add("lon >= ?", criteria.lon_min)
        if criteria.lon_max is not None:
            _add("lon <= ?", criteria.lon_max)
        if criteria.depth_min is not None:
            _add("pressure >= ?", criteria.depth_min)
        if criteria.depth_max is not None:
            _add("pressure <= ?", criteria.depth_max)
        if criteria.float_id is not None:
            _add("float_id = ?", str(criteria.float_id))
        if criteria.profile_number is not None:
            _add("cycle_number = ?", criteria.profile_number)

        # Priority 1C: NaN-safe variable presence filters
        requested_vars = [v.upper() for v in criteria.variables]
        for var in requested_vars:
            where_parts.append(_variable_presence_filter(var))

        where_clause = " AND ".join(where_parts) if where_parts else "1=1"
        limit = max(criteria.limit, 1)
        parquet_pattern = (self._lake_root / "**" / "*.parquet").as_posix()

        # Profile-level LIMIT: returns all depth levels per profile cycle
        sql = (
            f"WITH filtered AS (\n"
            f"    SELECT *\n"
            f"    FROM read_parquet('{parquet_pattern}', hive_partitioning=true)\n"
            f"    WHERE {where_clause}\n"
            f"),\n"
            f"selected_profiles AS (\n"
            f"    SELECT DISTINCT float_id, cycle_number\n"
            f"    FROM filtered\n"
            f"    ORDER BY float_id, cycle_number\n"
            f"    LIMIT {limit}\n"
            f")\n"
            "SELECT\n"
            "    f.float_id,\n"
            "    f.cycle_number,\n"
            "    f.date,\n"
            "    f.year,\n"
            "    f.month,\n"
            "    f.lat,\n"
            "    f.lon,\n"
            "    f.data_mode,\n"
            "    f.pressure,\n"
            "    f.temp,\n"
            "    f.temp_qc,\n"
            "    f.temp_adjusted,\n"
            "    f.psal,\n"
            "    f.psal_qc,\n"
            "    f.psal_adjusted,\n"
            "    f.doxy,\n"
            "    f.doxy_qc,\n"
            "    f.doxy_adjusted,\n"
            "    f.chla,\n"
            "    f.chla_qc,\n"
            "    f.chla_adjusted,\n"
            "    f.region_tag,\n"
            "    f.source_file,\n"
            "    f.dac\n"
            "FROM filtered f\n"
            "JOIN selected_profiles sp USING (float_id, cycle_number)\n"
            "ORDER BY f.date DESC, f.float_id, f.cycle_number, f.pressure"
        )

        logger.debug("Data lake SQL: %s", sql)
        logger.debug("Data lake params: %s", params)

        try:
            result_df = conn.execute(sql, params).fetchdf()
            logger.info("Data lake query returned %d rows", len(result_df))
            if result_df.empty:
                # Priority 1D: Compact log line instead of massive diagnostic dump
                logger.info(
                    "Zero-result: intent=%s vars=%s region=%s year=%s float=%s "
                    "available_years=%s available_regions=%s",
                    "lake_query",
                    criteria.variables,
                    criteria.region,
                    criteria.year,
                    criteria.float_id,
                    self.list_available_years(),
                    self.probe_availability(criteria.variables).get("available_regions", []),
                )
            return result_df
        except Exception as exc:
            logger.error("Data lake query failed: %s", exc)
            return pd.DataFrame()

    def _build_result(
        self,
        df: pd.DataFrame,
        criteria: LakeQueryCriteria,
    ) -> LakeQueryResult:
        """Compute aggregates and wrap in LakeQueryResult.

        Priority 1C: Uses _resolve_variable_column for canonical resolution.
        """
        if df.empty:
            return LakeQueryResult(df=df)

        if "date" in df.columns:
            df = df.copy()
            df["date"] = pd.to_datetime(df["date"], errors="coerce")

        requested_vars = (
            [v.upper() for v in criteria.variables] if criteria.variables else []
        )

        stats: dict[str, dict[str, float | int | None]] = {}
        for var in requested_vars:
            col_info = _LAKE_VARIABLES.get(var)
            if not col_info:
                continue
            # Priority 1C: Use canonical resolver
            series, val_col_name = _resolve_variable_column(df, var)
            if series.empty or series.dropna().empty:
                continue

            series = series.dropna()
            pres = pd.to_numeric(df["pressure"], errors="coerce")

            # Surface layer: shallowest levels
            surface_mask = (
                pres <= pres.quantile(0.2)
                if not pres.empty
                else pd.Series(False, index=df.index)
            )
            surface_vals = series[surface_mask.reindex(series.index, fill_value=False) & series.notna()]
            surface_mean = float(surface_vals.mean()) if surface_vals.size else None

            # Deep layer: below 200 dbar
            deep_mask = pres.reindex(series.index, fill_value=0) >= 200
            deep_vals = series[deep_mask & series.notna()]
            deep_mean = float(deep_vals.mean()) if deep_vals.size else None

            _, _, units = col_info
            stats[var] = {
                "n_obs": int(series.count()),
                "min_val": float(series.min()) if series.size else None,
                "max_val": float(series.max()) if series.size else None,
                "mean_val": float(series.mean()) if series.size else None,
                "median_val": float(series.median()) if series.size else None,
                "surface_mean_0_10m": surface_mean,
                "deep_mean_below_200m": deep_mean,
                "deepest_pres": float(pres.max()) if not pres.empty else None,
                "deepest_val": float(series.iloc[-1]) if series.size else None,
                "units": units,
                "resolved_column": val_col_name,
            }

        date_col = df["date"] if "date" in df.columns else pd.Series(dtype="datetime64[ns]")
        date_min = date_col.min()
        date_max = date_col.max()

        def _to_py_datetime(val):
            if hasattr(val, "to_pydatetime"):
                return val.to_pydatetime()
            return val

        return LakeQueryResult(
            df=df,
            stats=stats,
            unique_floats=int(df["float_id"].nunique()) if "float_id" in df.columns else 0,
            unique_profiles=int(
                df[["float_id", "cycle_number"]].drop_duplicates().shape[0]
            ),
            date_min=_to_py_datetime(date_min),
            date_max=_to_py_datetime(date_max),
            total_measurements=len(df),
            has_data=True,
            source=f"Argo Data Lake — {self._lake_root}",
        )


    # ------------------------------------------------------------------ #
    # Phase 2 — Full data lake methods
    # ------------------------------------------------------------------ #

    def is_phase2_available(self) -> bool:
        """Check if the Phase 2 data lake is available (all 4 tables exist)."""
        if not self._phase2_root:
            return False
        levels = self._phase2_root / "parquet" / "levels"
        if not levels.exists():
            return False
        return len(list(levels.rglob("*.parquet"))) > 0

    def get_profile_index(
        self,
        year: int | None = None,
        month: int | None = None,
        region: str | None = None,
        float_id: str | None = None,
        limit: int = 1000,
    ) -> pd.DataFrame:
        """Query the profile_index table for quick metadata lookups.

        Returns profile-level metadata (date, location, data mode, variables).
        """
        if not self._phase2_root:
            logger.warning("Phase 2 root not configured")
            return pd.DataFrame()

        pi_root = self._phase2_root / "parquet" / "profile_index"
        if not pi_root.exists():
            return pd.DataFrame()

        conn = self._get_connection()
        pattern = (pi_root / "**" / "*.parquet").as_posix()
        parts: list[str] = []
        params: list[Any] = []

        if year is not None:
            parts.append("year = ?")
            params.append(year)
        if month is not None:
            parts.append("month = ?")
            params.append(month)
        if region:
            parts.append("region_tag = ?")
            params.append(region)
        if float_id:
            parts.append("CAST(float_id AS VARCHAR) = ?")
            params.append(str(float_id).strip())

        where = " AND ".join(parts) if parts else "1=1"
        sql = (
            f"SELECT * FROM read_parquet('{pattern}', hive_partitioning=true) "
            f"WHERE {where} ORDER BY date DESC LIMIT {limit}"
        )
        try:
            return conn.execute(sql, params).fetchdf()
        except Exception as exc:
            logger.warning("profile_index query failed: %s", exc)
            return pd.DataFrame()

    def get_float_registry(self, float_id: str | None = None) -> pd.DataFrame:
        """Query the float_registry table for float metadata.
        
        Schema: float_id, platform_type, institution, profiler_type,
        region_tag, sensors, first_profile_date, last_report_date,
        last_global_report_date, profile_count, status
        """
        if not self._phase2_root:
            return pd.DataFrame()

        fr_root = self._phase2_root / "parquet" / "float_registry"
        fr_path = fr_root / "float_registry.parquet"
        if not fr_path.exists():
            return pd.DataFrame()

        try:
            df = pd.read_parquet(fr_path)
            if float_id:
                df = df[df["float_id"].astype(str) == str(float_id).strip()]
            return df
        except Exception as exc:
            logger.warning("float_registry query failed: %s", exc)
            return pd.DataFrame()

    def query_region_month_stats(
        self,
        region: str | None = None,
        year: int | None = None,
    ) -> pd.DataFrame:
        """Query the precomputed region_month_stats table."""
        return self.get_region_month_stats(region=region, year=year)

    def query_nearest_float(
        self,
        lat: float,
        lon: float,
        limit: int = 5,
    ) -> pd.DataFrame:
        """Find float(s) nearest to (lat, lon) with exact distance in km.
        
        Works with Phase 2 tables (profile_index / float_registry) or falls back
        to Phase 1 levels table. NO GDAC fallback.
        """
        conn = self._get_connection()

        pi_path = None
        if self._phase2_root and (self._phase2_root / "parquet" / "profile_index").exists():
            pi_path = (self._phase2_root / "parquet" / "profile_index" / "**" / "*.parquet").as_posix()
        if not pi_path and self._lake_root.exists():
            pi_path = (self._lake_root / "**" / "*.parquet").as_posix()

        if not pi_path:
            return pd.DataFrame()

        lat_col = "latitude" if "profile_index" in str(pi_path) else "lat"
        lon_col = "longitude" if "profile_index" in str(pi_path) else "lon"

        fr_file = None
        if self._phase2_root and (self._phase2_root / "parquet" / "float_registry" / "float_registry.parquet").exists():
            fr_file = (self._phase2_root / "parquet" / "float_registry" / "float_registry.parquet").as_posix()

        if fr_file:
            sql = f"""
            WITH latest_profiles AS (
                SELECT
                    CAST(float_id AS VARCHAR) AS float_id,
                    arg_max({lat_col}, date) AS lat,
                    arg_max({lon_col}, date) AS lon,
                    max(date) AS profile_date,
                    count(DISTINCT cycle_number) AS profile_count
                FROM read_parquet('{pi_path}', hive_partitioning=true)
                GROUP BY float_id
            )
            SELECT
                p.float_id,
                p.lat,
                p.lon,
                p.profile_date,
                p.profile_count,
                COALESCE(r.sensors, '') AS sensors,
                COALESCE(r.status, 'unknown') AS status,
                COALESCE(r.institution, '') AS institution,
                COALESCE(r.platform_type, '') AS platform_type,
                COALESCE(r.profiler_type, '') AS profiler_type,
                COALESCE(CAST(r.first_profile_date AS VARCHAR), '') AS first_profile_date,
                COALESCE(CAST(r.last_report_date AS VARCHAR), CAST(p.profile_date AS VARCHAR)) AS last_report_date,
                (
                    6371 * 2 * asin(sqrt(
                        power(sin(radians(p.lat - ?) / 2), 2) +
                        cos(radians(?)) * cos(radians(p.lat)) *
                        power(sin(radians(p.lon - ?) / 2), 2)
                    ))
                ) AS distance_km
            FROM latest_profiles p
            LEFT JOIN read_parquet('{fr_file}') r ON p.float_id = CAST(r.float_id AS VARCHAR)
            ORDER BY distance_km ASC
            LIMIT ?
            """
        else:
            sql = f"""
            WITH latest_profiles AS (
                SELECT
                    CAST(float_id AS VARCHAR) AS float_id,
                    arg_max({lat_col}, date) AS lat,
                    arg_max({lon_col}, date) AS lon,
                    max(date) AS profile_date,
                    count(DISTINCT cycle_number) AS profile_count,
                    COALESCE(arg_max(dac, date), '') AS institution
                FROM read_parquet('{pi_path}', hive_partitioning=true)
                GROUP BY float_id
            )
            SELECT
                p.float_id,
                p.lat,
                p.lon,
                p.profile_date,
                p.profile_count,
                '' AS sensors,
                'unknown' AS status,
                p.institution,
                '' AS platform_type,
                '' AS profiler_type,
                '' AS first_profile_date,
                CAST(p.profile_date AS VARCHAR) AS last_report_date,
                (
                    6371 * 2 * asin(sqrt(
                        power(sin(radians(p.lat - ?) / 2), 2) +
                        cos(radians(?)) * cos(radians(p.lat)) *
                        power(sin(radians(p.lon - ?) / 2), 2)
                    ))
                ) AS distance_km
            FROM latest_profiles p
            ORDER BY distance_km ASC
            LIMIT ?
            """

        params = [lat, lat, lon, limit]
        try:
            return conn.execute(sql, params).fetchdf()
        except Exception as exc:
            logger.warning("query_nearest_float failed: %s", exc)
            return pd.DataFrame()

    def query_radius_search(
        self,
        lat: float,
        lon: float,
        radius_km: float = 100.0,
        limit: int = 500,
        alive_date_start: str | None = None,
        alive_date_end: str | None = None,
    ) -> pd.DataFrame:
        """Find all floats within radius_km of (lat, lon). NO GDAC fallback.

        P3 #2: When alive_date_start/alive_date_end are set, a float only
        qualifies if it has >=1 profile in profile_index within [start, end].
        Implements "alive during <period>" — NOT float_registry.status.
        """
        conn = self._get_connection()

        pi_path = None
        if self._phase2_root and (self._phase2_root / "parquet" / "profile_index").exists():
            pi_path = (self._phase2_root / "parquet" / "profile_index" / "**" / "*.parquet").as_posix()
        if not pi_path and self._lake_root.exists():
            pi_path = (self._lake_root / "**" / "*.parquet").as_posix()

        if not pi_path:
            return pd.DataFrame()

        lat_col = "latitude" if "profile_index" in str(pi_path) else "lat"
        lon_col = "longitude" if "profile_index" in str(pi_path) else "lon"

        fr_file = None
        if self._phase2_root and (self._phase2_root / "parquet" / "float_registry" / "float_registry.parquet").exists():
            fr_file = (self._phase2_root / "parquet" / "float_registry" / "float_registry.parquet").as_posix()

        # P3 #2: optional date window applied BEFORE grouping so only floats
        # with >=1 profile in the window survive ("alive during period").
        alive_cond = ""
        if alive_date_start is not None and alive_date_end is not None:
            alive_cond = f"WHERE date >= '{alive_date_start}' AND date <= '{alive_date_end}'"

        if fr_file:
            sql = f"""
            WITH floats_dist AS (
                SELECT
                    CAST(float_id AS VARCHAR) AS float_id,
                    arg_max({lat_col}, date) AS lat,
                    arg_max({lon_col}, date) AS lon,
                    max(date) AS profile_date,
                    count(DISTINCT cycle_number) AS profile_count,
                    (
                        6371 * 2 * asin(sqrt(
                            power(sin(radians(arg_max({lat_col}, date) - ?) / 2), 2) +
                            cos(radians(?)) * cos(radians(arg_max({lat_col}, date))) *
                            power(sin(radians(arg_max({lon_col}, date) - ?) / 2), 2)
                        ))
                    ) AS distance_km
                FROM read_parquet('{pi_path}', hive_partitioning=true)
                {alive_cond}
                GROUP BY float_id
            )
            SELECT
                p.float_id,
                p.lat,
                p.lon,
                p.profile_date,
                p.profile_count,
                p.distance_km,
                COALESCE(r.sensors, '') AS sensors,
                COALESCE(r.status, 'unknown') AS status,
                COALESCE(r.institution, '') AS institution,
                COALESCE(r.platform_type, '') AS platform_type,
                COALESCE(r.profiler_type, '') AS profiler_type,
                COALESCE(CAST(r.first_profile_date AS VARCHAR), '') AS first_profile_date,
                COALESCE(CAST(r.last_report_date AS VARCHAR), CAST(p.profile_date AS VARCHAR)) AS last_report_date
            FROM floats_dist p
            LEFT JOIN read_parquet('{fr_file}') r ON p.float_id = CAST(r.float_id AS VARCHAR)
            WHERE p.distance_km <= ?
            ORDER BY p.distance_km ASC
            LIMIT ?
            """
        else:
            sql = f"""
            WITH floats_dist AS (
                SELECT
                    CAST(float_id AS VARCHAR) AS float_id,
                    arg_max({lat_col}, date) AS lat,
                    arg_max({lon_col}, date) AS lon,
                    max(date) AS profile_date,
                    count(DISTINCT cycle_number) AS profile_count,
                    COALESCE(arg_max(dac, date), '') AS institution,
                    (
                        6371 * 2 * asin(sqrt(
                            power(sin(radians(arg_max({lat_col}, date) - ?) / 2), 2) +
                            cos(radians(?)) * cos(radians(arg_max({lat_col}, date))) *
                            power(sin(radians(arg_max({lon_col}, date) - ?) / 2), 2)
                        ))
                    ) AS distance_km
                FROM read_parquet('{pi_path}', hive_partitioning=true)
                {alive_cond}
                GROUP BY float_id
            )
            SELECT
                p.float_id,
                p.lat,
                p.lon,
                p.profile_date,
                p.profile_count,
                p.distance_km,
                '' AS sensors,
                'unknown' AS status,
                p.institution,
                '' AS platform_type,
                '' AS profiler_type,
                '' AS first_profile_date,
                CAST(p.profile_date AS VARCHAR) AS last_report_date
            FROM floats_dist p
            WHERE p.distance_km <= ?
            ORDER BY p.distance_km ASC
            LIMIT ?
            """

        params = [lat, lat, lon, radius_km, limit]
        try:
            return conn.execute(sql, params).fetchdf()
        except Exception as exc:
            logger.warning("query_radius_search failed: %s", exc)
            return pd.DataFrame()

    # Phase 5 Part A: Manufacturer lookup from profiler type code
    _PROFILER_MANUFACTURER_MAP: dict[str, tuple[str, str]] = {
        "831": ("APEX", "Teledyne Webb (USA)"),
        "832": ("APEX", "Teledyne Webb (USA)"),
        "833": ("APEX", "Teledyne Webb (USA)"),
        "834": ("APEX", "Teledyne Webb (USA)"),
        "835": ("APEX", "Teledyne Webb (USA)"),
        "836": ("PROVOR CTS4", "Teledyne CARAIBE (France)"),
        "837": ("PROVOR CTS5", "Teledyne CARAIBE (France)"),
        "838": ("PROVOR", "Teledyne CARAIBE (France)"),
        "839": ("PROVOR", "Teledyne CARAIBE (France)"),
        "840": ("PROVOR", "Teledyne CARAIBE (France)"),
        "841": ("PROVOR", "Teledyne CARAIBE (France)"),
        "842": ("PROVOR", "Teledyne CARAIBE (France)"),
        "843": ("PROVOR", "Teledyne CARAIBE (France)"),
        "844": ("PROVOR", "Teledyne CARAIBE (France)"),
        "845": ("NAVIS", "Teledyne Webb (USA)"),
        "846": ("NINJA", "Tsurumi Seiki (Japan)"),
        "847": ("NINJA", "Tsurumi Seiki (Japan)"),
        "848": ("NEMO", "Nortek (Norway)"),
        "849": ("NEMO", "Nortek (Norway)"),
        "850": ("SOLO", "Scripps/Floats Inc. (USA)"),
        "851": ("SOLO", "Scripps/Floats Inc. (USA)"),
        "852": ("SOLO", "Scripps/Floats Inc. (USA)"),
        "853": ("SOLO", "Scripps/Floats Inc. (USA)"),
        "854": ("SOLO", "Scripps/Floats Inc. (USA)"),
        "860": ("ARVOR", "Teledyne CARAIBE (France)"),
        "861": ("ARVOR", "Teledyne CARAIBE (France)"),
        "862": ("ARVOR", "Teledyne CARAIBE (France)"),
        "863": ("ARVOR", "Teledyne CARAIBE (France)"),
        "864": ("ARVOR", "Teledyne CARAIBE (France)"),
    }

    @staticmethod
    def _estimate_battery_status(
        profile_count: int,
        first_profile_date: str | None,
        last_report_date: str | None,
        status: str,
        profiler_type: str | None = None,
    ) -> dict[str, Any]:
        """Phase 5 Part A: Estimate battery status from float operational data.
        
        Argo floats report raw voltage in tech.nc files, not percentages.
        Since tech.nc files are not part of the standard profile metadata pipeline,
        we estimate battery status from operational indicators.
        
        Estimation model:
        - Profiler-type-specific expected lifetimes (modern lithium packs last longer)
        - Active floats with recent reports get a minimum "Fair" floor
        - Linear discharge curve within expected lifetime
        
        Returns dict with: battery_voltage (estimated V), battery_percentage (0-100),
        battery_status (Good/Fair/Low/Critical/Unknown)
        """
        result: dict[str, Any] = {
            "battery_voltage": None,
            "battery_percentage": None,
            "battery_status": "Unknown",
            "battery_note": "Estimated from operational data (no tech.nc voltage available)",
        }
        
        if status == "inactive":
            result["battery_status"] = "Depleted"
            result["battery_voltage"] = 11.0
            result["battery_percentage"] = 0
            result["battery_note"] = "Float inactive — battery likely depleted"
            return result
        
        if profile_count <= 0:
            result["battery_status"] = "Unknown"
            result["battery_note"] = "No profile data available for estimation"
            return result
        
        _PROFILER_LIFETIME: dict[str, int] = {
            "831": 280, "832": 280, "833": 280, "834": 280, "835": 280,
            "836": 500, "837": 550,
            "838": 450, "839": 450, "840": 450, "841": 450, "842": 450, "843": 450, "844": 450,
            "845": 450,
            "846": 220, "847": 220,
            "848": 400, "849": 400,
            "850": 380, "851": 400, "852": 400, "853": 400, "854": 400,
            "860": 450, "861": 500, "862": 500, "863": 500, "864": 500,
        }
        
        code = str(profiler_type).strip() if profiler_type else ""
        expected_lifetime = _PROFILER_LIFETIME.get(code, 400)
        
        remaining_fraction = max(0.0, 1.0 - (profile_count / expected_lifetime))
        pct = max(0, min(100, int(remaining_fraction * 100)))
        
        voltage_fresh = 15.2
        voltage_dead = 11.0
        voltage = round(voltage_dead + (voltage_fresh - voltage_dead) * remaining_fraction, 1)
        
        if pct >= 70:
            bat_status = "Good"
        elif pct >= 40:
            bat_status = "Fair"
        elif pct >= 15:
            bat_status = "Low"
        else:
            bat_status = "Critical"
        
        if status == "active" and last_report_date:
            try:
                from datetime import datetime, timezone
                last_dt = datetime.fromisoformat(str(last_report_date)[:10])
                days_ago = (datetime.now() - last_dt).days
                
                if days_ago <= 30:
                    if pct < 25:
                        pct = max(pct, 25)
                        bat_status = "Fair"
                        voltage = round(voltage_dead + (voltage_fresh - voltage_dead) * (pct / 100), 1)
                        result["battery_note"] = (
                            f"Estimated — float reported {days_ago}d ago (active). "
                            "Actual battery may be higher than linear model suggests."
                        )
                elif days_ago <= 90:
                    if pct < 15:
                        pct = max(pct, 15)
                        bat_status = "Low"
                        voltage = round(voltage_dead + (voltage_fresh - voltage_dead) * (pct / 100), 1)
            except (ValueError, TypeError):
                pass
        
        if status == "drifted" and pct < 10:
            pct = max(pct, 10)
            bat_status = "Low"
            voltage = round(voltage_dead + (voltage_fresh - voltage_dead) * (pct / 100), 1)
        
        result["battery_voltage"] = voltage
        result["battery_percentage"] = pct
        result["battery_status"] = bat_status
        return result

    def query_metadata_lookup(self, float_id: str) -> dict[str, Any]:
        """Look up metadata registry info for a given float_id. NO GDAC fallback."""
        clean_fid = str(float_id).strip()
        reg_df = self.get_float_registry(float_id=clean_fid)

        PROFILER_MAP = {
            "836": "PROVOR CTS4",
            "837": "PROVOR CTS5",
            "841": "PROVOR",
            "842": "PROVOR",
            "831": "APEX",
            "832": "APEX",
            "845": "NAVIS",
            "851": "SOLO",
            "861": "ARVOR",
            "862": "ARVOR",
        }
        DAC_MAP = {
            "IF": "IFREMER (Coriolis)",
            "IN": "INCOIS (India)",
            "AO": "AOML (NOAA)",
            "JM": "JMA (Japan)",
            "CS": "CSIRO (Australia)",
            "KM": "KORDI / KMA (Korea)",
            "BO": "BODC (UK)",
            "HZ": "CSIO (China)",
        }

        info: dict[str, Any] = {
            "float_id": clean_fid,
            "found": False,
            "status": "unknown",
            "sensors": [],
            "institution": "unknown",
            "platform_type": "unknown",
            "profiler_type": "unknown",
            "manufacturer": "unknown",
            "battery_voltage": None,
            "battery_percentage": None,
            "battery_status": "Unknown",
            "battery_note": "Estimated from operational data (no tech.nc voltage available)",
            "first_profile_date": None,
            "last_report_date": None,
            "profile_count": 0,
            "region_tag": None,
            "last_lat": None,
            "last_lon": None,
            # First-class scientific attributes surfaced for the redesigned UI.
            # Network is derived from the sensor payload (Core Argo vs BGC Argo).
            # DAC is the resolved data-assembly-centre name; wmo_id mirrors the
            # float_id (which is itself the WMO identifier). deployment_date is
            # proxied from first_profile_date. These are additive — if the
            # backend later exposes authoritative fields, the UI consumes them
            # unchanged because the keys match.
            "wmo_id": clean_fid,
            "network": "Core Argo",
            "dac": "unknown",
            "deployment_date": None,
            "last_global_report_date": None,
        }

        if not reg_df.empty:
            row = reg_df.iloc[0]
            info["found"] = True
            info["status"] = str(row.get("status", "unknown"))
            raw_inst = str(row.get("institution", "unknown")).strip().upper()
            info["institution"] = DAC_MAP.get(raw_inst, raw_inst or "unknown")
            info["profiler_type"] = str(row.get("profiler_type", "unknown"))

            p_type = str(row.get("platform_type", "unknown"))
            p_code = str(info["profiler_type"]).strip()
            if p_type in ("unknown", "", "None") and p_code in PROFILER_MAP:
                info["platform_type"] = PROFILER_MAP[p_code]
            else:
                info["platform_type"] = p_type

            mfr_info = self._PROFILER_MANUFACTURER_MAP.get(p_code)
            if mfr_info:
                info["manufacturer"] = mfr_info[1]
                if info["platform_type"] in ("unknown", "", "None"):
                    info["platform_type"] = mfr_info[0]
            else:
                info["manufacturer"] = "unknown"

            info["region_tag"] = str(row.get("region_tag", ""))

            raw_sensors = row.get("sensors", "")
            if isinstance(raw_sensors, list):
                info["sensors"] = raw_sensors
            elif isinstance(raw_sensors, str) and raw_sensors:
                info["sensors"] = [s.strip() for s in raw_sensors.split(",") if s.strip()]

            info["first_profile_date"] = str(row.get("first_profile_date"))[:10] if pd.notna(row.get("first_profile_date")) else None
            info["last_report_date"] = str(row.get("last_report_date"))[:10] if pd.notna(row.get("last_report_date")) else None
            info["profile_count"] = int(row.get("profile_count", 0)) if pd.notna(row.get("profile_count")) else 0

            # Derive Network from the sensor payload. A float carrying any BGC
            # sensor (optode, fluorometer, nitrate, irradiance, backscatter, pH)
            # is classified as "BGC Argo"; otherwise "Core Argo".
            sensor_blob = " ".join(s.upper() for s in info["sensors"])
            _BGC_MARKERS = (
                "OPTODE", "OXYGEN", "FLUOROMETER", "CHLOROPHYLL", "CHLA",
                "NITRATE", "NO3", "IRRADIANCE", "PAR", "RADIOMETRY",
                "BACKSCATTER", "BBP", "PH", "SUNA", "ISUS", "OCR",
            )
            info["network"] = "BGC Argo" if any(m in sensor_blob for m in _BGC_MARKERS) else "Core Argo"

            # DAC: the human-readable data-assembly-centre name. Prefer the
            # resolved institution; fall back to the raw code.
            info["dac"] = info["institution"] if info["institution"] != "unknown" else (raw_inst or "unknown")

            # Deployment date has no dedicated source; first_profile_date is the
            # closest operational proxy.
            info["deployment_date"] = info["first_profile_date"]

            # last_global_report_date exists in the registry parquet but was not
            # previously surfaced. Expose it as an additive field.
            if pd.notna(row.get("last_global_report_date")):
                info["last_global_report_date"] = str(row.get("last_global_report_date"))[:10]

            battery_info = self._estimate_battery_status(
                profile_count=info["profile_count"],
                first_profile_date=info["first_profile_date"],
                last_report_date=info["last_report_date"],
                status=info["status"],
                profiler_type=info.get("profiler_type"),
            )
            info["battery_voltage"] = battery_info["battery_voltage"]
            info["battery_percentage"] = battery_info["battery_percentage"]
            info["battery_status"] = battery_info["battery_status"]
            info["battery_note"] = battery_info["battery_note"]

        # Query location and profile details from profile_index or levels
        pi_path = None
        if self._phase2_root and (self._phase2_root / "parquet" / "profile_index").exists():
            pi_path = (self._phase2_root / "parquet" / "profile_index" / "**" / "*.parquet").as_posix()
        elif self._lake_root.exists():
            pi_path = (self._lake_root / "**" / "*.parquet").as_posix()

        if pi_path:
            try:
                conn = self._get_connection()
                lat_col = "latitude" if "profile_index" in str(pi_path) else "lat"
                lon_col = "longitude" if "profile_index" in str(pi_path) else "lon"

                sql = f"""
                SELECT
                    CAST(float_id AS VARCHAR) AS float_id,
                    COUNT(DISTINCT cycle_number) AS profile_count,
                    MIN(date) AS first_profile_date,
                    MAX(date) AS last_report_date,
                    ARG_MAX({lat_col}, date) AS last_lat,
                    ARG_MAX({lon_col}, date) AS last_lon
                FROM read_parquet('{pi_path}', hive_partitioning=true)
                WHERE CAST(float_id AS VARCHAR) = ?
                GROUP BY float_id
                """
                df = conn.execute(sql, [clean_fid]).fetchdf()
                if not df.empty:
                    p_row = df.iloc[0]
                    info["found"] = True
                    if not info["profile_count"]:
                        info["profile_count"] = int(p_row["profile_count"])
                    if not info["first_profile_date"]:
                        info["first_profile_date"] = str(p_row["first_profile_date"])[:10] if pd.notna(p_row["first_profile_date"]) else None
                    if not info["last_report_date"]:
                        info["last_report_date"] = str(p_row["last_report_date"])[:10] if pd.notna(p_row["last_report_date"]) else None
                    info["last_lat"] = float(p_row["last_lat"]) if pd.notna(p_row["last_lat"]) else None
                    info["last_lon"] = float(p_row["last_lon"]) if pd.notna(p_row["last_lon"]) else None
            except Exception as exc:
                logger.warning("query_metadata_lookup position query failed: %s", exc)

        # Ensure battery estimation is populated
        if info.get("battery_percentage") is None and info.get("found"):
            battery_info = self._estimate_battery_status(
                profile_count=info.get("profile_count", 0),
                first_profile_date=info.get("first_profile_date"),
                last_report_date=info.get("last_report_date"),
                status=info.get("status", "unknown"),
                profiler_type=info.get("profiler_type"),
            )
            info["battery_voltage"] = battery_info["battery_voltage"]
            info["battery_percentage"] = battery_info["battery_percentage"]
            info["battery_status"] = battery_info["battery_status"]
            info["battery_note"] = battery_info["battery_note"]

        return info

    def query_count_aggregate(
        self,
        region: str | None = None,
        year: int | None = None,
        month: int | None = None,
        float_id: str | None = None,
        variables: list[str] | None = None,
        months: list[int] | None = None,
    ) -> dict[str, Any]:
        """Query count/existence statistics for given search filters.

        P3 #3: ``months`` (season window, e.g. [6,7,8,9] for monsoon) takes
        precedence over ``month`` when filtering.
        """
        conn = self._get_connection()

        rms_root = self._phase2_root / "parquet" / "region_month_stats" if self._phase2_root else None

        if rms_root and rms_root.exists() and not float_id and not variables:
            pattern = (rms_root / "**" / "*.parquet").as_posix()
            parts: list[str] = []
            params: list[Any] = []
            if region:
                parts.append("region_tag = ?")
                params.append(region)
            if year is not None:
                parts.append("year = ?")
                params.append(year)
            _mf = _month_filter(month, months)
            if _mf is not None:
                cond, mvals = _mf
                parts.append(cond)
                params.extend(mvals)

            where = " AND ".join(parts) if parts else "1=1"
            sql = f"""
            SELECT
                COALESCE(SUM(profile_count), 0) AS total_profiles,
                COALESCE(MAX(float_count), 0) AS total_floats
            FROM read_parquet('{pattern}', hive_partitioning=true)
            WHERE {where}
            """
            try:
                res = conn.execute(sql, params).fetchone()
                p_cnt = int(res[0]) if res else 0
                f_cnt = int(res[1]) if res else 0
                return {
                    "total_profiles": p_cnt,
                    "total_floats": f_cnt,
                    "has_data": p_cnt > 0,
                    "region": region,
                    "year": year,
                    "month": month,
                }
            except Exception as exc:
                logger.warning("region_month_stats count query failed: %s", exc)

        # If variables are requested, query the levels table which has them.
        use_levels_for_vars = bool(variables)

        if use_levels_for_vars:
            if self._phase2_root and (self._phase2_root / "parquet" / "levels").exists():
                data_path = (self._phase2_root / "parquet" / "levels" / "**" / "*.parquet").as_posix()
            elif self._lake_root.exists():
                data_path = (self._lake_root / "**" / "*.parquet").as_posix()
            else:
                data_path = None
        else:
            if self._phase2_root and (self._phase2_root / "parquet" / "profile_index").exists():
                data_path = (self._phase2_root / "parquet" / "profile_index" / "**" / "*.parquet").as_posix()
            elif self._lake_root.exists():
                data_path = (self._lake_root / "**" / "*.parquet").as_posix()
            else:
                data_path = None

        if not data_path:
            return {"total_profiles": 0, "total_floats": 0, "has_data": False}

        parts = []
        params = []
        if region:
            parts.append("region_tag = ?")
            params.append(region)
        if year is not None:
            parts.append("year = ?")
            params.append(year)
        _mf = _month_filter(month, months)
        if _mf is not None:
            cond, mvals = _mf
            parts.append(cond)
            params.extend(mvals)
        if float_id:
            parts.append("CAST(float_id AS VARCHAR) = ?")
            params.append(str(float_id))

        # Priority 1C: NaN-safe variable filters
        if variables and use_levels_for_vars:
            for v in variables:
                parts.append(_variable_presence_filter(v))

        where = " AND ".join(parts) if parts else "1=1"
        sql = f"""
        SELECT
            COUNT(DISTINCT CAST(float_id AS VARCHAR) || '-' || CAST(cycle_number AS VARCHAR)) AS total_profiles,
            COUNT(DISTINCT CAST(float_id AS VARCHAR)) AS total_floats,
            MIN(date) AS min_date,
            MAX(date) AS max_date
        FROM read_parquet('{data_path}', hive_partitioning=true)
        WHERE {where}
        """
        try:
            res = conn.execute(sql, params).fetchone()
            p_cnt = int(res[0]) if res and res[0] is not None else 0
            f_cnt = int(res[1]) if res and res[1] is not None else 0
            min_d = str(res[2])[:10] if res and res[2] is not None else None
            max_d = str(res[3])[:10] if res and res[3] is not None else None
            return {
                "total_profiles": p_cnt,
                "total_floats": f_cnt,
                "has_data": p_cnt > 0,
                "min_date": min_d,
                "max_date": max_d,
                "region": region,
                "year": year,
                "month": month,
                "float_id": float_id,
            }
        except Exception as exc:
            logger.warning("profile_index count query failed: %s", exc)
            return {"total_profiles": 0, "total_floats": 0, "has_data": False}


def build_region_tag(lat: float, lon: float) -> str | None:
    """Classify a coordinate pair into an India sub-region tag."""
    if point_in_region(lon, lat, "arabian_sea"):
        return "arabian_sea"
    if point_in_region(lon, lat, "bay_of_bengal"):
        return "bay_of_bengal"
    return None
