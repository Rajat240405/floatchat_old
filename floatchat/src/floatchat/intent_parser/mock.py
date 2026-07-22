"""Mock intent parser for development and integration testing.

Returns deterministic :class:`ParsedIntent` objects based on hard-coded
message patterns so the entire pipeline can be exercised without an LLM.
"""

import logging

from floatchat.exceptions import IntentParseError
from floatchat.intent_parser.base import AbstractIntentParser
from floatchat.models import ParsedIntent

logger = logging.getLogger(__name__)

# Hard-coded mappings for MVP demonstration.
_MOCK_MAP: dict[str, ParsedIntent] = {
    "show oxygen profile in arabian sea for 2024": ParsedIntent(
        intent="profile_plot",
        region="arabian_sea",
        variables=["DOXY"],
        year=2024,
        limit=5,
    ),
    "plot chlorophyll and backscattering in north atlantic": ParsedIntent(
        intent="profile_plot",
        region="north_atlantic",
        variables=["CHLA", "BBP700"],
        limit=5,
    ),
    "get nitrate data for float 6903091": ParsedIntent(
        intent="profile_plot",
        float_id="6903091",
        variables=["NITRATE"],
        limit=3,
    ),
}


class MockIntentParser(AbstractIntentParser):
    """Deterministic parser that matches messages against a hard-coded dictionary."""

    def parse(self, message: str) -> ParsedIntent:
        """Return a mock intent or raise :class:`IntentParseError`."""
        normalized = message.strip().lower().rstrip(".")
        logger.debug("MockIntentParser received: %r", message)

        if normalized in _MOCK_MAP:
            intent = _MOCK_MAP[normalized]
            logger.info("MockIntentParser matched intent=%s", intent.intent)
            return intent

        logger.warning("MockIntentParser could not match: %r", message)
        raise IntentParseError(
            f"No mock intent defined for message: {message!r}",
            details={"available_patterns": list(_MOCK_MAP.keys())},
        )
