"""Tests for MockIntentParser."""

import pytest

from floatchat.exceptions import IntentParseError
from floatchat.intent_parser.mock import MockIntentParser
from floatchat.models import ParsedIntent


class TestMockIntentParser:
    def test_parse_known_message(self) -> None:
        parser = MockIntentParser()
        intent = parser.parse("show oxygen profile in arabian sea for 2024")
        assert intent.intent == "profile_plot"
        assert intent.region == "arabian_sea"
        assert intent.variables == ["DOXY"]
        assert intent.year == 2024

    def test_parse_second_known_message(self) -> None:
        parser = MockIntentParser()
        intent = parser.parse("plot chlorophyll and backscattering in north atlantic")
        assert intent.intent == "profile_plot"
        assert intent.region == "north_atlantic"
        assert set(intent.variables) == {"CHLA", "BBP700"}

    def test_parse_float_message(self) -> None:
        parser = MockIntentParser()
        intent = parser.parse("get nitrate data for float 6903091")
        assert intent.float_id == "6903091"
        assert intent.variables == ["NITRATE"]

    def test_parse_unknown_message_raises(self) -> None:
        parser = MockIntentParser()
        with pytest.raises(IntentParseError):
            parser.parse("this is not a known mock pattern")
