"""Strict parser for raw scientific narrator output.

This module converts raw LLM text into the existing ``NarratorOutput`` schema.
It performs structural parsing and schema validation only; it does not verify
scientific grounding or invoke any model.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from floatchat.exceptions import NarratorOutputParseError
from floatchat.scientific_explanation.schemas import NarratorOutput


class _DuplicateFieldError(ValueError):
    """Internal signal raised when a JSON object repeats a field name."""

    def __init__(self, field: str) -> None:
        super().__init__("duplicate JSON field")
        self.field = field


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateFieldError(key)
        result[key] = value
    return result


class NarratorOutputParser:
    """Parse one strict JSON object into :class:`NarratorOutput`."""

    def parse(self, raw_text: str) -> NarratorOutput:
        """Parse and validate raw LLM text.

        Only a standalone JSON object is accepted. Markdown fences, explanatory
        prefixes/suffixes, malformed JSON, duplicate fields, and schema-invalid
        objects are rejected rather than repaired.
        """
        if not isinstance(raw_text, str):
            raise NarratorOutputParseError(
                "Narrator output must be text.",
                details={"received_type": type(raw_text).__name__},
            )

        text = raw_text.strip()
        if not text:
            raise NarratorOutputParseError("Narrator output must not be empty.")

        try:
            decoded = json.loads(text, object_pairs_hook=_object_without_duplicates)
        except _DuplicateFieldError as exc:
            raise NarratorOutputParseError(
                "Narrator output contains a duplicate JSON field.",
                details={"field": exc.field},
            ) from exc
        except json.JSONDecodeError as exc:
            raise NarratorOutputParseError(
                "Narrator output is not valid JSON.",
                details={"line": exc.lineno, "column": exc.colno},
            ) from exc

        if not isinstance(decoded, dict):
            raise NarratorOutputParseError(
                "Narrator output must be a JSON object.",
                details={"received_type": type(decoded).__name__},
            )

        try:
            return NarratorOutput.model_validate(decoded)
        except ValidationError as exc:
            errors = [
                {
                    "location": ".".join(str(part) for part in error["loc"]),
                    "type": error["type"],
                    "message": error["msg"],
                }
                for error in exc.errors(include_input=False, include_url=False)
            ]
            raise NarratorOutputParseError(
                "Narrator output does not match the required schema.",
                details={"errors": errors},
            ) from exc


__all__ = ["NarratorOutputParser"]
