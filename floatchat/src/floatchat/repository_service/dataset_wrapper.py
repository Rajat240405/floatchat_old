"""NetCDF dataset wrapper to keep in-memory bytes alive."""

import logging

from netCDF4 import Dataset

logger = logging.getLogger(__name__)


class NetCDFDataset:
    """Wrapper that keeps the raw HTTP bytes alive alongside the Dataset.

    ``netCDF4.Dataset(memory=...)`` may hold a reference to the original
    buffer; this wrapper prevents premature garbage collection.
    """

    def __init__(self, relative_path: str, data: bytes, dataset: Dataset) -> None:
        self.relative_path = relative_path
        self._data = data
        self.dataset = dataset

    def close(self) -> None:
        """Close the underlying NetCDF dataset and release the byte buffer."""
        if self.dataset is not None:
            self.dataset.close()
            self.dataset = None  # type: ignore[assignment]
        self._data = b""
        logger.debug("Closed NetCDFDataset for %s", self.relative_path)

    def __enter__(self) -> "NetCDFDataset":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def __del__(self) -> None:
        # Defensive cleanup if the caller forgets to close.
        if getattr(self, "dataset", None) is not None:
            self.close()
