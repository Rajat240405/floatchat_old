"""Tests for conversation context preservation across general/data queries.

Priority 2 update: Context inheritance now requires reference phrases.
Tests updated to include reference phrases where inheritance is expected.
"""

from floatchat.conversation.memory import InMemoryConversationManager
from floatchat.models import ChatResponse, ParsedIntent


class TestContextPreservation:
    def test_general_query_preserves_data_context(self) -> None:
        mgr = InMemoryConversationManager()

        # First: DATA_QUERY stores variables, region, float, year
        mgr.update_context(
            "sess-1",
            ParsedIntent(
                intent="profile_plot",
                variables=["DOXY"],
                region="arabian_sea",
                float_id="3902490",
                year=2024,
            ),
            ChatResponse(intent="profile_plot", message="ok"),
        )

        # Second: a non-data turn (general/knowledge chat) must NOT erase the
        # stored data context. ("general_chat" is just the label used by
        # general/knowledge-style responses; the rule is label-agnostic:
        # update_context only overwrites fields the new intent actually sets.)
        mgr.update_context(
            "sess-1",
            ParsedIntent(intent="general_chat"),
            ChatResponse(intent="general_chat", message="Explanation."),
        )

        ctx = mgr.get_context("sess-1")
        assert ctx is not None
        assert ctx.last_variables == ["DOXY"]
        assert ctx.last_region == "arabian_sea"
        assert ctx.last_float_id == "3902490"
        assert ctx.last_year == 2024

    def test_data_query_overrides_explicitly(self) -> None:
        mgr = InMemoryConversationManager()

        mgr.update_context(
            "sess-1",
            ParsedIntent(
                intent="profile_plot",
                variables=["DOXY"],
                region="arabian_sea",
            ),
            ChatResponse(intent="profile_plot", message="ok"),
        )

        # Follow-up explicitly changes variable and region
        mgr.update_context(
            "sess-1",
            ParsedIntent(
                intent="profile_plot",
                variables=["CHLA"],
                region="bay_of_bengal",
            ),
            ChatResponse(intent="profile_plot", message="ok"),
        )

        ctx = mgr.get_context("sess-1")
        assert ctx.last_variables == ["CHLA"]
        assert ctx.last_region == "bay_of_bengal"

    def test_merge_after_general_query_uses_preserved_context(self) -> None:
        """Priority 2: Context preserved after general query, inherited with reference."""
        mgr = InMemoryConversationManager()

        # Data query
        mgr.update_context(
            "sess-1",
            ParsedIntent(
                intent="profile_plot",
                variables=["DOXY"],
                region="arabian_sea",
                float_id="3902490",
            ),
            ChatResponse(intent="profile_plot", message="ok"),
        )

        # General query (preserves context)
        mgr.update_context(
            "sess-1",
            ParsedIntent(intent="general_chat"),
            ChatResponse(intent="general_chat", message="Explanation."),
        )

        # New data query with "same" reference → inherits from preserved context
        minimal = ParsedIntent(intent="profile_plot", variables=["CHLA"])
        minimal.__dict__["_original_message"] = "chlorophyll in the same region"
        merged = mgr.merge_context("sess-1", minimal)

        assert merged.variables == ["CHLA"]
        assert merged.region == "arabian_sea"  # inherited via "same region"

    def test_conversational_recovery_uses_context_with_reference(self) -> None:
        """Priority 2: Recovery only works with reference phrases."""
        mgr = InMemoryConversationManager()

        mgr.update_context(
            "sess-1",
            ParsedIntent(
                intent="profile_plot",
                variables=["DOXY"],
                region="arabian_sea",
            ),
            ChatResponse(intent="profile_plot", message="ok"),
        )

        # Empty follow-up WITH reference → context inherited
        empty = ParsedIntent(intent="profile_plot")
        empty.__dict__["_original_message"] = "same"
        merged = mgr.merge_context("sess-1", empty)

        assert merged.variables == ["DOXY"]
        assert merged.region == "arabian_sea"

    def test_conversational_recovery_without_reference_no_inheritance(self) -> None:
        """Priority 2: Without reference phrase, no inheritance even after context set."""
        mgr = InMemoryConversationManager()

        mgr.update_context(
            "sess-1",
            ParsedIntent(
                intent="profile_plot",
                variables=["DOXY"],
                region="arabian_sea",
            ),
            ChatResponse(intent="profile_plot", message="ok"),
        )

        # Empty follow-up WITHOUT reference → no inheritance
        empty = ParsedIntent(intent="profile_plot")
        merged = mgr.merge_context("sess-1", empty)

        assert merged.variables == []
        assert merged.region is None
