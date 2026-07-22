"""Tests for the provider-agnostic scientific narrator."""

from unittest.mock import MagicMock

import pytest

from floatchat.exceptions import ScientificNarratorError
from floatchat.llm_service.base import AbstractLLMService
from floatchat.scientific_explanation.narrator import ScientificNarrator


class TestScientificNarrator:
    def test_generate_delegates_to_abstract_llm_service(self) -> None:
        llm = MagicMock(spec=AbstractLLMService)
        llm.generate.return_value = '  {"explanation":"grounded result"}  '
        narrator = ScientificNarrator(llm, max_retries=0)

        result = narrator.generate("facts-only prompt", system="narrator system")

        assert result == '{"explanation":"grounded result"}'
        llm.generate.assert_called_once_with(
            "facts-only prompt",
            system="narrator system",
        )

    def test_generate_without_system_delegates_none(self) -> None:
        llm = MagicMock(spec=AbstractLLMService)
        llm.generate.return_value = "raw output"
        narrator = ScientificNarrator(llm, max_retries=0)

        narrator.generate("prompt")

        llm.generate.assert_called_once_with("prompt", system=None)

    def test_provider_failure_is_retried(self) -> None:
        llm = MagicMock(spec=AbstractLLMService)
        llm.generate.side_effect = [ConnectionError("temporarily unavailable"), "recovered"]
        narrator = ScientificNarrator(llm, max_retries=1)

        assert narrator.generate("prompt") == "recovered"
        assert llm.generate.call_count == 2

    def test_empty_provider_response_is_retried(self) -> None:
        llm = MagicMock(spec=AbstractLLMService)
        llm.generate.side_effect = ["   ", "recovered"]
        narrator = ScientificNarrator(llm, max_retries=1)

        assert narrator.generate("prompt") == "recovered"
        assert llm.generate.call_count == 2

    def test_provider_failure_raises_after_configured_retries(self) -> None:
        llm = MagicMock(spec=AbstractLLMService)
        llm.generate.side_effect = ConnectionError("provider unavailable")
        narrator = ScientificNarrator(llm, max_retries=2)

        with pytest.raises(ScientificNarratorError) as exc_info:
            narrator.generate("prompt")

        assert exc_info.value.details == {
            "provider": "AbstractLLMService",
            "attempts": 3,
            "exception": "ConnectionError",
        }
        assert llm.generate.call_count == 3

    def test_empty_prompt_is_rejected_without_provider_call(self) -> None:
        llm = MagicMock(spec=AbstractLLMService)
        narrator = ScientificNarrator(llm)

        with pytest.raises(ScientificNarratorError):
            narrator.generate("   ")

        llm.generate.assert_not_called()

    def test_negative_retry_count_is_rejected(self) -> None:
        llm = MagicMock(spec=AbstractLLMService)

        with pytest.raises(ValueError):
            ScientificNarrator(llm, max_retries=-1)
