"""Unit tests for strict scientific narrator output parsing."""

import json

import pytest

from floatchat.exceptions import NarratorOutputParseError
from floatchat.scientific_explanation.output_parser import NarratorOutputParser
from floatchat.scientific_explanation.schemas import NarratorOutput

_VALID_EXPLANATION = (
    "The supplied profile facts show a grounded vertical pattern with documented quality context."
)


def _raw_output(**updates) -> str:
    payload = {
        "explanation": _VALID_EXPLANATION,
        "key_findings": ["The finding is present in the supplied facts."],
        "confidence": "medium",
    }
    payload.update(updates)
    return json.dumps(payload)


def _schema_error_locations(exc: NarratorOutputParseError) -> set[str]:
    return {error["location"] for error in exc.details.get("errors", [])}


class TestNarratorOutputParser:
    def test_parses_valid_json_into_narrator_output(self) -> None:
        parser = NarratorOutputParser()

        output = parser.parse(_raw_output(confidence="high"))

        assert isinstance(output, NarratorOutput)
        assert output.explanation == _VALID_EXPLANATION
        assert output.key_findings == ["The finding is present in the supplied facts."]
        assert output.confidence == "high"

    def test_accepts_json_surrounded_only_by_whitespace(self) -> None:
        parser = NarratorOutputParser()

        output = parser.parse(f"\n\t  {_raw_output()}  \r\n")

        assert output.confidence == "medium"

    def test_strips_explanation_whitespace(self) -> None:
        parser = NarratorOutputParser()

        output = parser.parse(_raw_output(explanation=f"  {_VALID_EXPLANATION}  "))

        assert output.explanation == _VALID_EXPLANATION

    def test_accepts_long_multi_paragraph_scientific_explanation(self) -> None:
        parser = NarratorOutputParser()
        words = ["oceanographic"] * 260
        explanation = " ".join(words[:130]) + "\n\n" + " ".join(words[130:])

        output = parser.parse(_raw_output(explanation=explanation))

        assert output.explanation == explanation
        assert len(output.explanation) > 2000

    def test_schema_defaults_are_applied_when_optional_fields_are_omitted(self) -> None:
        parser = NarratorOutputParser()
        raw = json.dumps({"explanation": _VALID_EXPLANATION})

        output = parser.parse(raw)

        assert output.key_findings == []
        assert output.confidence == "medium"

    @pytest.mark.parametrize(
        "raw_text",
        [
            "{",
            "{'explanation': 'single quotes are not JSON'}",
            '{"explanation":"value",}',
            f"```json\n{_raw_output()}\n```",
            f"Here is the result: {_raw_output()}",
            f"{_raw_output()} trailing text",
        ],
    )
    def test_rejects_malformed_or_wrapped_json(self, raw_text: str) -> None:
        parser = NarratorOutputParser()

        with pytest.raises(NarratorOutputParseError, match="not valid JSON"):
            parser.parse(raw_text)

    def test_rejects_extra_fields(self) -> None:
        parser = NarratorOutputParser()

        with pytest.raises(NarratorOutputParseError, match="required schema") as exc_info:
            parser.parse(_raw_output(unsupported_claim="not allowed"))

        assert "unsupported_claim" in _schema_error_locations(exc_info.value)
        assert exc_info.value.details["errors"][0]["type"] == "extra_forbidden"

    @pytest.mark.parametrize("confidence", ["very_high", "HIGH", "uncertain", 1, None])
    def test_rejects_invalid_confidence_values(self, confidence: object) -> None:
        parser = NarratorOutputParser()

        with pytest.raises(NarratorOutputParseError, match="required schema") as exc_info:
            parser.parse(_raw_output(confidence=confidence))

        assert "confidence" in _schema_error_locations(exc_info.value)

    @pytest.mark.parametrize("raw_text", ["[]", '"text"', "42", "true", "null"])
    def test_rejects_non_object_json(self, raw_text: str) -> None:
        parser = NarratorOutputParser()

        with pytest.raises(NarratorOutputParseError, match="must be a JSON object"):
            parser.parse(raw_text)

    @pytest.mark.parametrize("raw_text", ["", "   ", "\n\t"])
    def test_rejects_empty_text(self, raw_text: str) -> None:
        parser = NarratorOutputParser()

        with pytest.raises(NarratorOutputParseError, match="must not be empty"):
            parser.parse(raw_text)

    @pytest.mark.parametrize("raw_value", [None, 123, {}, []])
    def test_rejects_non_string_input(self, raw_value: object) -> None:
        parser = NarratorOutputParser()

        with pytest.raises(NarratorOutputParseError, match="must be text") as exc_info:
            parser.parse(raw_value)  # type: ignore[arg-type]

        assert "received_type" in exc_info.value.details

    def test_rejects_missing_explanation(self) -> None:
        parser = NarratorOutputParser()
        raw = json.dumps({"key_findings": [], "confidence": "low"})

        with pytest.raises(NarratorOutputParseError, match="required schema") as exc_info:
            parser.parse(raw)

        assert "explanation" in _schema_error_locations(exc_info.value)

    @pytest.mark.parametrize("explanation", ["too short", "x" * 5001, 123, None])
    def test_rejects_invalid_explanation(self, explanation: object) -> None:
        parser = NarratorOutputParser()

        with pytest.raises(NarratorOutputParseError, match="required schema") as exc_info:
            parser.parse(_raw_output(explanation=explanation))

        assert "explanation" in _schema_error_locations(exc_info.value)

    def test_rejects_more_than_four_key_findings_instead_of_truncating(self) -> None:
        parser = NarratorOutputParser()
        findings = [f"Grounded finding {index}" for index in range(5)]

        with pytest.raises(NarratorOutputParseError, match="required schema") as exc_info:
            parser.parse(_raw_output(key_findings=findings))

        assert "key_findings" in _schema_error_locations(exc_info.value)

    @pytest.mark.parametrize(
        "key_findings",
        [
            "not a list",
            ["valid finding", 2],
            ["valid finding", None],
        ],
    )
    def test_rejects_invalid_key_findings(self, key_findings: object) -> None:
        parser = NarratorOutputParser()

        with pytest.raises(NarratorOutputParseError, match="required schema") as exc_info:
            parser.parse(_raw_output(key_findings=key_findings))

        assert any(
            location.startswith("key_findings")
            for location in _schema_error_locations(exc_info.value)
        )

    def test_rejects_duplicate_json_fields(self) -> None:
        parser = NarratorOutputParser()
        raw = (
            "{"
            f'"explanation":{json.dumps(_VALID_EXPLANATION)},'
            '"confidence":"high",'
            '"confidence":"low"'
            "}"
        )

        with pytest.raises(NarratorOutputParseError, match="duplicate JSON field") as exc_info:
            parser.parse(raw)

        assert exc_info.value.details == {"field": "confidence"}

    def test_validation_errors_do_not_echo_raw_model_values(self) -> None:
        parser = NarratorOutputParser()
        secret = "UNTRUSTED_MODEL_TEXT_MUST_NOT_BE_ECHOED"

        with pytest.raises(NarratorOutputParseError) as exc_info:
            parser.parse(_raw_output(extra_field=secret))

        assert secret not in str(exc_info.value)
        assert secret not in repr(exc_info.value.details)
