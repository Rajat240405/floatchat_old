"""ParsedIntent contract tests (Milestone 5 contract tightening).

Locks the audited state of the single typed object crossing the NL → backend
boundary: the intent vocabulary Literal, the removal of the stale
``cycle_number`` alias, and the canonical ``profile_number`` selector.
"""

from typing import get_args

from floatchat.models import ParsedIntent


EXPECTED_INTENT_VOCABULARY = {
    # data intents (routed to QueryEngine executors)
    "profile_plot", "region_search", "time_series", "comparison_plot",
    "comparison", "trajectory", "hovmoller", "ts_diagram", "nearest_float",
    "radius_search", "metadata_lookup", "count_aggregate",
    # non-data intents (chat routing / guard rails)
    "general_chat", "unknown", "small_talk", "out_of_domain", "knowledge_base",
}


class TestIntentVocabulary:
    def test_literal_matches_documented_vocabulary(self) -> None:
        vocab = set(get_args(ParsedIntent.model_fields["intent"].annotation))
        assert vocab == EXPECTED_INTENT_VOCABULARY


class TestProfileSelector:
    def test_cycle_number_alias_removed(self) -> None:
        assert "cycle_number" not in ParsedIntent.model_fields

    def test_profile_number_is_the_selector(self) -> None:
        assert "profile_number" in ParsedIntent.model_fields
        intent = ParsedIntent(intent="profile_plot", profile_number=205)
        assert intent.profile_number == 205

    def test_parser_payload_mentioning_cycle_number_still_validates(self) -> None:
        # LLM parser output may still contain the legacy key; pydantic's
        # default extra policy ignores it (documented in models/intent.py).
        intent = ParsedIntent.model_validate(
            {"intent": "profile_plot", "float_id": "2902403", "cycle_number": 3}
        )
        assert intent.profile_number is None
