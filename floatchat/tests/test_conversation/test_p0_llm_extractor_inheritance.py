"""P0 regression tests — LLM-extractor → merge_context → reference-phrase interaction.

These tests exercise the EXACT interaction that the existing conversation test
suite missed (which is why the P0 regression slipped in silently):

    Turn 1 establishes context (variable + region/float, year=None).
    Turn 2 contains an explicit reference phrase ("same region", "that float",
    "there") AND triggers the Priority-3 LLM entity extractor (because a slot
    is missing). The extractor fills a slot and RECONSTRUCTS a brand-new
    ParsedIntent. Before the P0 fix that reconstruction dropped the smuggled
    ``_original_message`` attribute, so ``merge_context`` saw an empty message,
    detected NO reference phrase, and silently skipped inheritance.

The fix passes the raw user message explicitly into ``merge_context`` so the
reference phrase is honored regardless of any ParsedIntent reconstruction.

Constraint #6 (reference phrase required to inherit stale filters) is preserved:
without a reference phrase there is still no inheritance.
"""
from unittest.mock import patch

import pytest

from floatchat.api.routes import _try_llm_extraction
from floatchat.conversation.memory import InMemoryConversationManager
from floatchat.entity_extractor.query_spec import QuerySpec
from floatchat.intent_parser.regex import RegexIntentParser
from floatchat.models import ChatResponse


def _dummy_response(intent):
    return ChatResponse(
        intent=intent.intent, message="ok", figure=None,
        data_summary={}, map_data=[],
    )


def _patch_extractor(specs):
    """Patch the routes-level LLMEntityExtractor to return *specs* in order.

    Each spec is returned for one ``extract()`` call (one per turn). This
    emulates the qwen2.5:0.5b model: it echoes context variables / offers a
    year, but reliably DROPS the region (the realistic failure mode that
    forces inheritance to be the source of truth).
    """
    iterator = iter(specs)

    def _factory():
        # Each LLMEntityExtractor() call returns an instance whose .extract
        # pops the next pre-baked spec.
        from unittest.mock import MagicMock
        inst = MagicMock()
        inst.extract.side_effect = lambda **kw: next(iterator, None)
        return inst

    return patch("floatchat.api.routes.LLMEntityExtractor", side_effect=_factory)


def simulate_turn(parser, cm, sid, message, *, pass_message=True):
    """Mirror the fixed chat() DATA_QUERY flow for a single turn.

    parse -> _try_llm_extraction (may reconstruct ParsedIntent) -> merge_context.

    ``pass_message`` toggles whether the raw message is handed to
    merge_context (the fix) vs. omitted (the old buggy contract).
    """
    parsed = parser.parse(message)
    parsed = _try_llm_extraction(message, parsed, sid, cm)
    if pass_message:
        merged = cm.merge_context(sid, parsed, message=message)
    else:
        merged = cm.merge_context(sid, parsed)
    cm.update_context(sid, merged, _dummy_response(merged))
    return merged


# --------------------------------------------------------------------------- #
# (a) "same region" — region must be inherited via the reference phrase even
#     though the LLM extractor reconstructed ParsedIntent (filling variables).
# --------------------------------------------------------------------------- #
def test_same_region_inherits_through_llm_extraction():
    parser = RegexIntentParser()
    cm = InMemoryConversationManager()
    sid = "p0-same-region"

    specs = [
        # Turn 1: year missing -> LLM fires; returns vars echo (already set),
        # no time_filter, so year stays None. No reconstruction.
        QuerySpec(action="region_search", variables=["DOXY"], confidence=0.9),
        # Turn 2: vars missing -> LLM fires; echoes DOXY from context (fills
        # the empty variables slot -> RECONSTRUCTS ParsedIntent) but drops the
        # region. Region must come from the "same region" reference phrase.
        QuerySpec(action="profile_plot", variables=["DOXY"], confidence=0.9),
    ]

    with _patch_extractor(specs):
        t1 = simulate_turn(parser, cm, sid, "oxygen in Bay of Bengal")
        assert t1.variables == ["DOXY"]
        assert t1.region == "bay_of_bengal"
        assert t1.year is None  # Turn 1 leaves year=None -> LLM fires in Turn 2

        t2 = simulate_turn(parser, cm, sid, "same region but in 2023")

    # The reference phrase "same region" + explicit year must win.
    assert t2.variables == ["DOXY"]
    assert t2.region == "bay_of_bengal", (
        "region must be inherited via 'same region' despite LLM reconstruction"
    )
    assert t2.year == 2023


# --------------------------------------------------------------------------- #
# (b) "that float" — float_id must be inherited via the reference phrase even
#     though the LLM extractor reconstructed ParsedIntent (filling variables).
# --------------------------------------------------------------------------- #
def test_that_float_inherits_through_llm_extraction():
    parser = RegexIntentParser()
    cm = InMemoryConversationManager()
    sid = "p0-that-float"

    specs = [
        # Turn 1: "oxygen for float 2902403" — vars+float already present, LLM
        # echoes vars (skipped). year stays None.
        QuerySpec(action="profile_plot", variables=["DOXY"], confidence=0.9),
        # Turn 2: vars missing -> LLM echoes DOXY (reconstruction trigger), but
        # does NOT return a float_id. float_id must be inherited via "that float".
        QuerySpec(action="profile_plot", variables=["DOXY"], confidence=0.9),
    ]

    with _patch_extractor(specs):
        t1 = simulate_turn(parser, cm, sid, "oxygen for float 2902403")
        assert t1.variables == ["DOXY"]
        assert t1.float_id == "2902403"
        assert t1.year is None

        t2 = simulate_turn(parser, cm, sid, "that float in 2023")

    # Phase 1/2: LLM variables are now IGNORED. "that float" inherits
    # float_id but NOT variables (no variable reference phrase).
    assert t2.variables == []
    assert t2.float_id == "2902403", (
        "float_id must be inherited via 'that float' despite LLM reconstruction"
    )
    assert t2.year == 2023


# --------------------------------------------------------------------------- #
# (c) "there" — region must be inherited via the spatial reference phrase even
#     though the LLM extractor reconstructed ParsedIntent (filling the year).
# --------------------------------------------------------------------------- #
def test_there_spatial_inherits_through_llm_extraction():
    parser = RegexIntentParser()
    cm = InMemoryConversationManager()
    sid = "p0-there"

    specs = [
        # Turn 1: "oxygen in Arabian Sea" — vars+region present. LLM echoes
        # vars (skipped), no time_filter, so year stays None.
        QuerySpec(action="region_search", variables=["DOXY"], confidence=0.9),
        # Turn 2: "chlorophyll there" — vars present (CHLA), region & year
        # missing -> LLM offers a year (time_filter="2024") which RECONSTRUCTS
        # ParsedIntent. Region must be inherited via the "there" reference.
        QuerySpec(action="profile_plot", time_filter="2024", confidence=0.9),
    ]

    with _patch_extractor(specs):
        t1 = simulate_turn(parser, cm, sid, "oxygen in Arabian Sea")
        assert t1.variables == ["DOXY"]
        assert t1.region == "arabian_sea"
        assert t1.year is None

        t2 = simulate_turn(parser, cm, sid, "chlorophyll there")

    assert t2.variables == ["CHLA"]
    assert t2.region == "arabian_sea", (
        "region must be inherited via 'there' despite LLM reconstruction"
    )
    # Year was filled by the LLM (proves reconstruction happened).
    assert t2.year == 2024


# --------------------------------------------------------------------------- #
# (d) Guard: the explicit message param is REQUIRED. If the reconstructed
#     intent carries no message (the old buggy contract), inheritance is lost.
#     This documents why the fix exists and protects the contract.
# --------------------------------------------------------------------------- #
def test_message_param_is_required_after_reconstruction():
    parser = RegexIntentParser()
    cm = InMemoryConversationManager()
    sid = "p0-guard"

    specs = [
        QuerySpec(action="region_search", variables=["DOXY"], confidence=0.9),
        # Turn 2 reconstruction trigger: fills variables, drops region.
        QuerySpec(action="profile_plot", variables=["DOXY"], confidence=0.9),
    ]

    with _patch_extractor(specs):
        t1 = simulate_turn(parser, cm, sid, "oxygen in Bay of Bengal",
                           pass_message=True)
        assert t1.region == "bay_of_bengal"

        # OLD contract: do NOT pass message -> merge_context cannot see the
        # reference phrase (reconstructed intent has no _original_message).
        t2 = simulate_turn(parser, cm, sid, "same region but in 2023",
                           pass_message=False)

    # Without the message param, the reference phrase is invisible and region
    # is NOT inherited — this is the exact bug the P0 fix eliminates.
    assert t2.region is None
    # Phase 1/2: LLM variables are now IGNORED, so without the message param
    # (no reference detection → no inheritance), variables stay empty.
    assert t2.variables == []
    assert t2.year == 2023


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
