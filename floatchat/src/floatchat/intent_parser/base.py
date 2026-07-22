"""Abstract interface for intent parsers."""

from abc import ABC, abstractmethod

from floatchat.models import ParsedIntent


class AbstractIntentParser(ABC):
    """Convert a natural-language message into a structured :class:`ParsedIntent`.

    Implementations must be stateless and thread-safe.
    """

    @abstractmethod
    def parse(self, message: str) -> ParsedIntent:
        """Parse ``message`` and return a validated :class:`ParsedIntent`.

        Args:
            message: Raw user input.

        Returns:
            A fully populated :class:`ParsedIntent`.

        Raises:
            floatchat.exceptions.IntentParseError: If parsing fails.
        """
        ...
