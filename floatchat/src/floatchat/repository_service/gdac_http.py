"""GDAC HTTP repository implementation.

Streams NetCDF files directly into RAM without writing to disk.
Uses connection pooling and exponential backoff retries.
Phase 23: Adds local NetCDF cache with configurable TTL and improved retry logging.
"""

import logging
import os
from pathlib import Path
from time import sleep

import httpx
from netCDF4 import Dataset

from floatchat.config import settings
from floatchat.exceptions import RepositoryError
from floatchat.repository_service.base import AbstractRepositoryService
from floatchat.repository_service.dataset_wrapper import NetCDFDataset

logger = logging.getLogger(__name__)

_NETCDF_CACHE_DIR = Path(os.environ.get("FLOATCHAT_CACHE_DIR", ".cache")) / "netcdf"


def _cache_path(relative_path: str) -> Path:
    """Return the local cache path for a GDAC relative path.

    Uses only the filename (basename) as the cache key.
    """
    filename = relative_path.replace("/", "-")
    return _NETCDF_CACHE_DIR / filename


def cleanup_expired_netcdf_cache() -> int:
    """Delete NetCDF cache files older than the configured TTL (Phase 23).

    Does NOT delete metadata indexes (.cache/*.txt.gz).
    Returns the number of files deleted.
    """
    import time as _time

    if not _NETCDF_CACHE_DIR.exists():
        logger.info("NetCDF cache dir does not exist; nothing to clean up.")
        return 0

    ttl_seconds = settings.netcdf_cache_ttl_days * 24 * 3600
    now = _time.time()
    deleted = 0
    kept = 0

    for entry in _NETCDF_CACHE_DIR.iterdir():
        if not entry.is_file():
            continue
        age = now - entry.stat().st_mtime
        if age > ttl_seconds:
            entry.unlink()
            deleted += 1
            logger.info(
                "Cache cleanup: deleted expired %s (age: %.1f days)",
                entry.name, age / 86400,
            )
        else:
            kept += 1

    if deleted:
        logger.info(
            "Cache cleanup: %d expired files deleted, %d files retained.",
            deleted, kept,
        )
    else:
        logger.info(
            "Cache cleanup: all %d files within TTL, none expired.", kept,
        )
    return deleted


class GDACRepositoryService(AbstractRepositoryService):
    """Fetch profiles from ``https://data-argo.ifremer.fr/dac/``.

    Phase 23: Caches downloaded NetCDF files locally to avoid redundant
    downloads. Logs cache hits and misses clearly.
    """

    def __init__(self, client: httpx.Client | None = None) -> None:
        if client is not None:
            self._client = client
        else:
            limits = httpx.Limits(
                max_connections=settings.http_max_connections,
                max_keepalive_connections=settings.http_max_keepalive,
            )
            self._client = httpx.Client(timeout=settings.http_timeout, limits=limits)

    def fetch(self, relative_path: str) -> NetCDFDataset:
        """Download *relative_path* with retries and open it as a NetCDF dataset.

        Phase 23: Checks local cache first; saves downloads to cache on miss.
        """
        cache_file = _cache_path(relative_path)
        filename = relative_path.rsplit("/", 1)[-1] if "/" in relative_path else relative_path

        # --- Phase 23: Local cache hit --------------------------------------- #
        if cache_file.exists():
            logger.info("Cache hit: %s", filename)
            return self._open_cached(cache_file, relative_path)

        # --- Phase 23: Cache miss — download --------------------------------- #
        logger.info("Cache miss: Downloading %s ...", filename)

        url = f"{settings.gdac_base_url}/dac/{relative_path}"
        data = self._fetch_with_retries(url, filename)

        # --- Phase 23: Save to cache ----------------------------------------- #
        _NETCDF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(data)
        logger.info("Cached: %s (%d bytes)", filename, len(data))

        return self._open_dataset(data, relative_path)

    # --------------------------------------------------------------------- #
    # Internals
    # --------------------------------------------------------------------- #

    def _fetch_with_retries(self, url: str, filename: str) -> bytes:
        """Download with exponential backoff and improved logging (Phase 23)."""
        last_exc: Exception | None = None
        for attempt in range(1, settings.http_max_retries + 1):
            backoff = min(2 ** attempt, 30)
            try:
                response = self._client.get(url)
                response.raise_for_status()
                logger.info(
                    "Downloaded %s (%d bytes) on attempt %d",
                    filename, len(response.content), attempt,
                )
                return response.content
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                last_exc = exc
                if attempt < settings.http_max_retries:
                    logger.warning(
                        "Retry %s attempt %d/%d, delay %.1fs: %s",
                        filename,
                        attempt,
                        settings.http_max_retries,
                        backoff,
                        exc,
                    )
                    sleep(backoff)
                else:
                    logger.error(
                        "Failed %s after %d attempts: %s",
                        filename,
                        settings.http_max_retries,
                        exc,
                    )
                    if isinstance(exc, httpx.HTTPStatusError):
                        raise RepositoryError(
                            f"GDAC returned {exc.response.status_code} for {url}",
                            details={
                                "url": url,
                                "status_code": exc.response.status_code,
                            },
                        ) from exc
                    raise RepositoryError(
                        f"Network error fetching {url}",
                        details={"url": url, "exception": str(exc)},
                    ) from exc

        # Should never reach here, but satisfy type checker
        raise RepositoryError(
            f"Unexpected: all retries exhausted for {url}",
            details={"url": url},
        )

    def _open_cached(self, cache_file: Path, relative_path: str) -> NetCDFDataset:
        """Open a locally-cached NetCDF file from disk."""
        data = cache_file.read_bytes()
        return self._open_dataset(data, relative_path)

    def _open_dataset(self, data: bytes, relative_path: str) -> NetCDFDataset:
        """Open a NetCDF Dataset from raw bytes."""
        safe_name = relative_path.replace("/", "-")
        try:
            dataset = Dataset(
                filename=f"in-memory-{safe_name}",
                memory=data,
                mode="r",
                format="NETCDF4",
            )
        except Exception as exc:
            raise RepositoryError(
                f"Failed to open NetCDF dataset from memory: {relative_path}",
                details={"exception": str(exc)},
            ) from exc

        return NetCDFDataset(relative_path, data, dataset)