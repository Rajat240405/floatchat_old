"""Abstract base for Query Normalizer."""

from abc import ABC, abstractmethod


class AbstractQueryNormalizer(ABC):
    """Normalize user queries before intent parsing."""

    @abstractmethod
    def normalize(self, query: str) -> str:
        """Return a normalized version of the query.

        Must preserve user intent. Only correct spelling, terminology,
        variable names, region names, and expand abbreviations.
        """
        ...