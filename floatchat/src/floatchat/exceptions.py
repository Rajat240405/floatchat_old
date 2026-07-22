"""Domain exception hierarchy for FloatChat.

All custom exceptions inherit from :class:`FloatChatError` so the API layer can
catch them uniformly and map them to appropriate HTTP status codes.
"""


class FloatChatError(Exception):
    """Base exception for all FloatChat domain errors."""

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class IntentParseError(FloatChatError):
    """Raised when the intent parser fails to produce a valid ParsedIntent."""


class MetadataError(FloatChatError):
    """Raised when the metadata service cannot load or search the index."""


class RepositoryError(FloatChatError):
    """Raised when the repository service cannot fetch a NetCDF file."""


class NetCDFReadError(FloatChatError):
    """Raised when the NetCDF reader cannot extract requested variables."""


class VisualizationError(FloatChatError):
    """Raised when the visualization engine cannot render a figure."""


class ScientificNarratorError(FloatChatError):
    """Raised when the scientific narrator cannot obtain a usable model response."""


class NarratorOutputParseError(FloatChatError):
    """Raised when raw scientific narration cannot be parsed into its output schema."""


class NarrationVerificationError(FloatChatError):
    """Raised when parsed narration is not grounded in its scientific facts."""
