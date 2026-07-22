"""Abstract interface for repository services."""

from abc import ABC, abstractmethod

from floatchat.repository_service.dataset_wrapper import NetCDFDataset


class AbstractRepositoryService(ABC):
    """Fetch Argo NetCDF profile files from a remote repository.

    Implementations receive a relative path (as found in
    :attr:`MetadataRecord.file`) and return an in-memory
    :class:`NetCDFDataset` wrapper.
    """

    @abstractmethod
    def fetch(self, relative_path: str) -> NetCDFDataset:
        """Fetch a single NetCDF file and return it as an in-memory dataset.

        Args:
            relative_path: Path relative to the repository root,
                e.g. ``coriolis/6903091/profiles/BR6903091_001.nc``.

        Returns:
            A :class:`NetCDFDataset` wrapper that keeps the underlying bytes
            alive while the ``netCDF4.Dataset`` is open.

        Raises:
            floatchat.exceptions.RepositoryError: On network or HTTP failure.
        """
        ...
