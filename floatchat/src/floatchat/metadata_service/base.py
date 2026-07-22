"""Abstract interface for metadata services."""

from abc import ABC, abstractmethod

from floatchat.models import MetadataRecord, SearchCriteria


class AbstractMetadataService(ABC):
    """Load and search the Argo profile metadata index.

    Implementations are responsible for keeping the index in memory and
    providing fast filtering capabilities.
    """

    @abstractmethod
    def load(self) -> None:
        """Download (if necessary) and load the metadata index into RAM.

        This method is idempotent; subsequent calls should refresh only if
        the cached data is stale.
        """
        ...

    @abstractmethod
    def search(self, criteria: SearchCriteria) -> list[MetadataRecord]:
        """Return metadata records matching ``criteria``.

        Args:
            criteria: Search filters.

        Returns:
            Ordered list of matching records (newest first, limited by
            ``criteria.limit``).
        """
        ...

    @abstractmethod
    def is_loaded(self) -> bool:
        """Return ``True`` if the index is loaded and ready for queries."""
        ...
