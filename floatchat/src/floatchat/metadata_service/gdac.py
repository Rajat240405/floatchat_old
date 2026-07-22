"""GDAC metadata service implementation.

Downloads the official ``argo_bio-profile_index.txt.gz``, loads it into a
Pandas DataFrame, and provides fast in-memory filtering.
"""

import logging
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pandas as pd

from floatchat.config import settings
from floatchat.exceptions import MetadataError
from floatchat.metadata_service.base import AbstractMetadataService
from floatchat.metadata_service.regions import has_polygon, point_in_region, resolve_region
from floatchat.models import MetadataRecord, SearchCriteria
from floatchat.retrieval_planner.planner import RetrievalPlanner
from floatchat.variable_registry.registry import VariableRegistry

logger = logging.getLogger(__name__)

# Columns defined by the Argo GDAC bio/synthetic-profile index specification.
# See: https://data-argo.ifremer.fr/argo_bio-profile_index.txt.gz
_INDEX_COLUMNS = [
    "file",
    "date",
    "latitude",
    "longitude",
    "ocean",
    "profiler_type",
    "institution",
    "parameters",
    "parameter_data_mode",
    "date_update",
]

# The core profile directory is an eight-column index: unlike the bio and
# synthetic indexes, it has no parameter list or per-parameter data modes.
# It must not be parsed with ``_INDEX_COLUMNS`` or its final date is shifted
# into the ``parameters`` field and ``date_update`` becomes missing.
_CORE_INDEX_COLUMNS = [
    "file",
    "date",
    "latitude",
    "longitude",
    "ocean",
    "profiler_type",
    "institution",
    "date_update",
]

# Local cache path (relative to working directory or env override).
_CACHE_DIR = Path(os.environ.get("FLOATCHAT_CACHE_DIR", ".cache"))
_CACHE_FILE = _CACHE_DIR / "argo_bio-profile_index.txt.gz"
_CORE_CACHE_FILE = _CACHE_DIR / "ar_index_global_prof.txt.gz"
_SYNTHETIC_CACHE_FILE = _CACHE_DIR / "argo_synthetic-profile_index.txt.gz"
_DOWNLOAD_CHUNK_BYTES = 1024 * 1024
_DOWNLOAD_PROGRESS_BYTES = 5 * 1024 * 1024


def _parse_argo_timestamp(val: str) -> datetime:
    """Parse Argo index timestamps: YYYYMMDDHHMMSS."""
    return datetime.strptime(val.strip(), "%Y%m%d%H%M%S").replace(tzinfo=UTC)


def _download_to_cache(client: httpx.Client, url: str, destination: Path, label: str) -> int:
    """Stream a GDAC index to disk and return the number of bytes written."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp_destination = destination.with_name(f"{destination.name}.tmp")
    bytes_written = 0
    next_progress = _DOWNLOAD_PROGRESS_BYTES

    logger.info("Starting %s download: %s", label, url)
    try:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            logger.info("Writing %s to cache: %s", label, destination)
            with tmp_destination.open("wb") as handle:
                for chunk in response.iter_bytes(chunk_size=_DOWNLOAD_CHUNK_BYTES):
                    if not chunk:
                        continue
                    handle.write(chunk)
                    bytes_written += len(chunk)
                    if bytes_written >= next_progress:
                        logger.info("%s download progress: %d bytes", label, bytes_written)
                        next_progress += _DOWNLOAD_PROGRESS_BYTES
    except Exception:
        tmp_destination.unlink(missing_ok=True)
        raise

    tmp_destination.replace(destination)
    logger.info("Wrote %s metadata cache (%d bytes)", label, bytes_written)
    return bytes_written


class GDACMetadataService(AbstractMetadataService):
    """Metadata service backed by the Ifremer GDAC.

    Phase 21: Supports both bio and synthetic indexes and uses
    the RetrievalPlanner + VariableRegistry for correct routing.
    """

    def __init__(self) -> None:
        self._df: pd.DataFrame | None = None          # bio index
        self._core_df: pd.DataFrame | None = None     # core index
        self._synthetic_df: pd.DataFrame | None = None  # synthetic (fallback)
        self._last_load: datetime | None = None
        self.planner = RetrievalPlanner()

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    def load(self) -> None:
        """Ensure Core and Bio indexes are loaded (Phase 22).

        Phase 23: Measures and logs startup timing for each stage.
        """
        t_start = time.perf_counter()

        core_missing = not _CORE_CACHE_FILE.exists()
        bio_missing = not _CACHE_FILE.exists()

        if not core_missing and not bio_missing and self._is_cache_fresh():
            logger.info("Loading metadata indexes from local cache")

            logger.info("Loading Core metadata ...")
            t0 = time.perf_counter()
            self._load_from_file(_CORE_CACHE_FILE, is_core=True)
            t1 = time.perf_counter()
            logger.info("Core load: %.1f sec", t1 - t0)

            logger.info("Loading Bio metadata ...")
            t0 = time.perf_counter()
            self._load_from_file(_CACHE_FILE, is_bio=True)
            t1 = time.perf_counter()
            logger.info("Bio load: %.1f sec", t1 - t0)

            if settings.enable_synthetic_index and _SYNTHETIC_CACHE_FILE.exists():
                self._load_from_file(_SYNTHETIC_CACHE_FILE, is_synthetic=True)

            t_total = time.perf_counter()
            logger.info("Metadata total: %.1f sec", t_total - t_start)
            logger.info("Metadata initialization complete.")
            return

        logger.info("Downloading metadata indexes from GDAC ...")
        if core_missing:
            self._download_core_index()
        if bio_missing:
            self._download_index()
        if settings.enable_synthetic_index:
            self._download_synthetic_index()

        if _CORE_CACHE_FILE.exists():
            logger.info("Loading Core metadata ...")
            t0 = time.perf_counter()
            self._load_from_file(_CORE_CACHE_FILE, is_core=True)
            t1 = time.perf_counter()
            logger.info("Core load: %.1f sec", t1 - t0)

        if _CACHE_FILE.exists():
            logger.info("Loading Bio metadata ...")
            t0 = time.perf_counter()
            self._load_from_file(_CACHE_FILE, is_bio=True)
            t1 = time.perf_counter()
            logger.info("Bio load: %.1f sec", t1 - t0)

        if settings.enable_synthetic_index and _SYNTHETIC_CACHE_FILE.exists():
            self._load_from_file(_SYNTHETIC_CACHE_FILE, is_synthetic=True)

        t_total = time.perf_counter()
        logger.info("Metadata total: %.1f sec", t_total - t_start)
        logger.info("Metadata initialization complete.")

    def search(self, criteria: SearchCriteria) -> list[MetadataRecord]:
        """Filter the in-memory index according to *criteria*."""
        if self._df is None and self._core_df is None:
            raise MetadataError("Metadata index not loaded. Call load() first.")

        # Phase 22: Planning happens once at the beginning
        plan = self.planner.plan(criteria.parameters or [])

        if plan.metadata_index == "core":
            if self._core_df is None:
                raise MetadataError(
                    "Core metadata index is unavailable; cannot satisfy a core-variable query."
                )
            logger.info("RetrievalPlanner selected Core index")
            return self._search_dataframe(self._core_df, criteria, parameter_filter=[])

        elif plan.metadata_index == "bio":
            if self._df is None:
                raise MetadataError("Bio metadata index not loaded. Call load() first.")
            logger.info("RetrievalPlanner selected Bio index")
            records = self._search_dataframe(
                self._df,
                criteria,
                parameter_filter=criteria.parameters,
                metadata_index="bio",
            )
            if not records and criteria.float_id is not None and self._core_df is not None:
                logger.info("Bio index returned 0 records for float %s; checking Core index fallback", criteria.float_id)
                records = self._search_dataframe(self._core_df, criteria, parameter_filter=[], metadata_index="core")
            return records

        elif plan.metadata_index == "both":
            logger.info("RetrievalPlanner selected both Core + Bio indexes")
            classification = VariableRegistry.classify_variables(criteria.parameters or [])
            if plan.requires_core and self._core_df is None:
                raise MetadataError(
                    "Core metadata index is unavailable; cannot satisfy the core variables "
                    "in this query."
                )
            if plan.requires_bio and self._df is None:
                raise MetadataError(
                    "Bio metadata index is unavailable; cannot satisfy the BGC variables "
                    "in this query."
                )

            records: list[MetadataRecord] = []
            if plan.requires_core:
                records.extend(self._search_dataframe(self._core_df, criteria, parameter_filter=[]))
            if plan.requires_bio:
                records.extend(
                    self._search_dataframe(
                        self._df,
                        criteria,
                        parameter_filter=classification["bgc"],
                        metadata_index="bio",
                    )
                )
            return records

        else:
            if self._df is None:
                raise MetadataError("Bio metadata index not loaded. Call load() first.")
            logger.info("RetrievalPlanner selected Bio index (default)")
            return self._search_dataframe(
                self._df,
                criteria,
                parameter_filter=criteria.parameters,
                metadata_index="bio",
            )

    def _search_dataframe(
        self,
        df: pd.DataFrame,
        criteria: SearchCriteria,
        parameter_filter: list[str],
        metadata_index: str = "core",
    ) -> list[MetadataRecord]:
        """Apply common metadata filters and optional Bio parameter matching."""
        logger.debug("Starting search on %d rows", len(df))

        # --- Region / bounding box ---------------------------------------- #
        bounds = resolve_region(getattr(criteria, "region", None))
        if bounds:
            criteria = criteria.model_copy(update=bounds)

        if criteria.lat_min is not None:
            df = df[df["latitude"] >= criteria.lat_min]
        if criteria.lat_max is not None:
            df = df[df["latitude"] <= criteria.lat_max]
        if criteria.lon_min is not None:
            df = df[df["longitude"] >= criteria.lon_min]
        if criteria.lon_max is not None:
            df = df[df["longitude"] <= criteria.lon_max]

        # --- Polygon filter (authoritative) ----------------------------- #
        region_name = getattr(criteria, "region", None)
        if has_polygon(region_name):
            logger.debug("Applying polygon filter for region: %s", region_name)
            pre_polygon = len(df)
            mask = df.apply(
                lambda row: point_in_region(row["longitude"], row["latitude"], region_name),
                axis=1,
            )
            df = df[mask]
            logger.info(
                "Polygon filter '%s': %d / %d records retained",
                region_name,
                len(df),
                pre_polygon,
            )

        # --- Date filters ------------------------------------------------- #
        if criteria.year is not None:
            df = df[df["date"].dt.year == criteria.year]
        if criteria.month is not None:
            df = df[df["date"].dt.month == criteria.month]
        if criteria.day is not None:
            df = df[df["date"].dt.day == criteria.day]

        # --- Float ID ----------------------------------------------------- #
        if criteria.float_id is not None:
            # The file path contains the WMO id, e.g. coriolis/6903091/...
            df = df[df["file"].str.contains(f"/{criteria.float_id}/", regex=False)]

        # --- Profile number (exact cycle match) --------------------------- #
        if criteria.profile_number is not None:
            # Argo filenames use zero-padded 3-digit profile numbers:
            # BR3902490_052.nc, BD3902490_052.nc, etc.
            profile_pattern = f"_{criteria.profile_number:03d}.nc"
            df = df[df["file"].str.contains(profile_pattern, regex=False, na=False)]

        # --- Phase 22: Bio-only exact parameter matching (token-based) ---- #
        if parameter_filter:
            # Exact token matching (not substring)
            mask = pd.Series(True, index=df.index)
            for param in parameter_filter:
                mask &= df["parameters"].apply(
                    lambda x, param=param: param in str(x).split() if pd.notna(x) else False
                )
            df = df[mask]

        # --- Sort & limit ------------------------------------------------- #
        # Phase 24: Quality-aware ranking — prefer delayed-mode, newest,
        # and most-complete profiles.
        _mode_rank = {"D": 0, "A": 1, "R": 2}

        def _quality_key(row):
            modes = str(row.get("parameter_data_mode", "")).split()
            best_mode = min((_mode_rank.get(m, 3) for m in modes), default=3)
            n_params = len(str(row.get("parameters", "")).split())
            newest = row["date"].timestamp() if pd.notna(row["date"]) else 0
            return (best_mode, -newest, -n_params)

        # Compute quality scores and sort
        df = df.copy()
        df["_quality"] = df.apply(_quality_key, axis=1)
        df = df.sort_values("_quality", ascending=True).drop(columns=["_quality"])
        df = df.head(criteria.limit)
        logger.info("%s metadata search returned %d records", metadata_index, len(df))

        return [MetadataRecord(**row) for row in df.to_dict("records")]

    def is_loaded(self) -> bool:
        return self._df is not None or self._core_df is not None

    # --------------------------------------------------------------------- #
    # Internals
    # --------------------------------------------------------------------- #

    def _is_cache_fresh(self) -> bool:
        """Return True if both Core and Bio cache files exist and are fresh."""
        if not _CACHE_FILE.exists() or not _CORE_CACHE_FILE.exists():
            return False
        now = datetime.now(UTC)
        ttl = timedelta(hours=settings.metadata_cache_ttl_hours)
        bio_mtime = datetime.fromtimestamp(_CACHE_FILE.stat().st_mtime, tz=UTC)
        core_mtime = datetime.fromtimestamp(_CORE_CACHE_FILE.stat().st_mtime, tz=UTC)
        return (now - bio_mtime) < ttl and (now - core_mtime) < ttl

    def _download_core_index(self) -> None:
        """Download the Core (global profile) index."""
        core_url = f"{settings.gdac_base_url}/ar_index_global_prof.txt.gz"

        try:
            limits = httpx.Limits(
                max_connections=settings.http_max_connections,
                max_keepalive_connections=settings.http_max_keepalive,
            )
            with httpx.Client(timeout=settings.http_timeout, limits=limits) as client:
                _download_to_cache(client, core_url, _CORE_CACHE_FILE, "Core index")
        except httpx.HTTPError as exc:
            logger.warning("Failed to download Core index: %s", exc)
            return

    def _download_index(self) -> None:
        url = f"{settings.gdac_base_url}{settings.metadata_index_path}"
        try:
            limits = httpx.Limits(
                max_connections=settings.http_max_connections,
                max_keepalive_connections=settings.http_max_keepalive,
            )
            with httpx.Client(timeout=settings.http_timeout, limits=limits) as client:
                _download_to_cache(client, url, _CACHE_FILE, "Bio index")
        except httpx.HTTPError as exc:
            raise MetadataError(
                f"Failed to download metadata index from {url}",
                details={"exception": str(exc)},
            ) from exc

    def _download_synthetic_index(self) -> None:
        """Download the synthetic profile index."""
        synthetic_url = f"{settings.gdac_base_url}/argo_synthetic-profile_index.txt.gz"
        try:
            limits = httpx.Limits(
                max_connections=settings.http_max_connections,
                max_keepalive_connections=settings.http_max_keepalive,
            )
            with httpx.Client(timeout=settings.http_timeout, limits=limits) as client:
                _download_to_cache(
                    client,
                    synthetic_url,
                    _SYNTHETIC_CACHE_FILE,
                    "Synthetic index",
                )
        except httpx.HTTPError as exc:
            logger.warning("Failed to download synthetic index: %s", exc)
            return

    def _load_from_file(
        self, path: Path, is_core: bool = False, is_bio: bool = False, is_synthetic: bool = False
    ) -> None:
        logger.info("Reading CSV ...")
        columns = _CORE_INDEX_COLUMNS if is_core else _INDEX_COLUMNS
        try:
            df = pd.read_csv(
                path,
                comment="#",
                compression="gzip",
                names=columns,
                dtype={
                    "file": "string",
                    "ocean": "string",
                    "profiler_type": "string",
                    "institution": "string",
                    "parameters": "string",
                    "parameter_data_mode": "string",
                },
                low_memory=False,
            )
        except Exception as exc:
            raise MetadataError(
                f"Failed to parse metadata index: {path}",
                details={"exception": str(exc)},
            ) from exc

        logger.info("Building DataFrame ...")
        if is_core:
            # Keep a uniform downstream MetadataRecord shape while preserving
            # the core index's real date_update column.
            df["parameters"] = ""
            df["parameter_data_mode"] = ""

        df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
        df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")

        for col in (
            "file",
            "ocean",
            "profiler_type",
            "institution",
            "parameters",
            "parameter_data_mode",
        ):
            df[col] = df[col].fillna("").astype("string")

        for col in ("date", "date_update"):
            df[col] = pd.to_datetime(df[col], format="%Y%m%d%H%M%S", errors="coerce", utc=True)

        df = df.dropna(subset=["date", "latitude", "longitude"]).reset_index(drop=True)

        if is_core:
            self._core_df = df
            logger.info("Loaded %d rows", len(df))
        elif is_bio:
            self._df = df
            self._last_load = datetime.now(UTC)
            logger.info("Loaded %d rows", len(df))
        elif is_synthetic:
            self._synthetic_df = df
            logger.info("Loaded synthetic metadata index: %d rows", len(df))
        else:
            # Backward compatibility
            self._df = df
            self._last_load = datetime.now(UTC)
            logger.info("Loaded %d rows", len(df))
