"""Ollama-based intent parser.

Calls a local Ollama instance (e.g. ``llama3``, ``mistral``) with a
structured system prompt and expects a JSON response matching the
:class:`ParsedIntent` schema.
"""

import json
import logging

import httpx

from floatchat.config import settings
from floatchat.exceptions import IntentParseError
from floatchat.intent_parser.base import AbstractIntentParser
from floatchat.models import ParsedIntent

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "llama3"
_OLLAMA_URL = "http://localhost:11434/api/generate"

_SYSTEM_PROMPT = """You are an intent parser for an oceanographic data API.
Convert the user's natural language query into a JSON object matching this schema:

{
  "intent": "profile_plot" | "time_series" | "comparison_plot" | "trajectory" | "unknown",
  "region": "arabian_sea" | "north_atlantic" | "south_atlantic" | "north_pacific" | "south_pacific" | "indian_ocean" | "southern_ocean" | "mediterranean_sea" | null,
  "variables": ["DOXY", "CHLA", "BBP700", "NITRATE", "PH_IN_SITU_TOTAL", "DOWNWELLING_PAR", "DOWN_IRRADIANCE380", "DOWN_IRRADIANCE412", "DOWN_IRRADIANCE490", "TEMP", "PSAL"],
  "year": integer or null,
  "month": integer or null,
  "day": integer or null,
  "lat_min": float or null,
  "lat_max": float or null,
  "lon_min": float or null,
  "lon_max": float or null,
  "depth_min": float or null,
  "depth_max": float or null,
  "float_id": "7-digit WMO number string" or null,
  "cycle_number": integer or null,
  "limit": integer (1-20, default 5)
}

Rules:
- Return ONLY the JSON object. No markdown, no explanation.
- Variable names must be uppercase Argo parameter names.
- Region names use underscores and lowercase.
- If the query is ambiguous, use "unknown" for intent.
"""


class OllamaIntentParser(AbstractIntentParser):
    """Intent parser powered by a local Ollama LLM."""

    def __init__(
        self,
        model: str = _DEFAULT_MODEL,
        url: str = _OLLAMA_URL,
        timeout: float = 30.0,
    ) -> None:
        self.model = model
        self.url = url
        self.timeout = timeout

    def parse(self, message: str) -> ParsedIntent:
        """Send *message* to Ollama and parse the JSON response."""
        logger.debug("OllamaIntentParser querying model=%s", self.model)

        payload = {
            "model": self.model,
            "prompt": message,
            "system": _SYSTEM_PROMPT,
            "stream": False,
            "format": "json",
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(self.url, json=payload)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise IntentParseError(
                f"Ollama request failed: {exc}",
                details={"url": self.url, "model": self.model},
            ) from exc

        try:
            raw = response.json()
            response_text = raw.get("response", "")
            parsed_json = json.loads(response_text)
        except (json.JSONDecodeError, KeyError) as exc:
            raise IntentParseError(
                "Ollama returned unparseable JSON",
                details={"raw_response": response.text},
            ) from exc

        logger.debug("Ollama raw JSON: %s", parsed_json)

        try:
            intent = ParsedIntent.model_validate(parsed_json)
        except Exception as exc:
            raise IntentParseError(
                "Ollama JSON does not match ParsedIntent schema",
                details={"parsed_json": parsed_json, "validation_error": str(exc)},
            ) from exc

        logger.info("OllamaIntentParser resolved intent=%s", intent.intent)
        return intent
