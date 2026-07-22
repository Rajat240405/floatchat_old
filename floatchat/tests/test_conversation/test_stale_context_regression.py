"""Regression tests for the Phase 25 'No Argo profiles matched' bug.

Priority 2 update: Context inheritance now requires reference phrases.
Tests updated to include reference phrases where inheritance is expected.

The original Phase 25 guards (float_id NOT inherited into region-scoped follow-ups,
profile_number NOT inherited without float_id) are still enforced, but now
additionally gated by the reference phrase system.
"""

from floatchat.conversation.memory import InMemoryConversationManager
from floatchat.models import ChatResponse, ParsedIntent


def _seed(mgr, session, **fields):
    """Helper: write one prior turn into ctx with the given intent fields."""
    intent = ParsedIntent(intent=fields.pop("intent", "profile_plot"), **fields)
    mgr.update_context(
        session, intent, ChatResponse(intent=intent.intent, message="ok")
    )


def _merge_with_msg(mgr, session, message, **intent_fields):
    """Helper: merge with _original_message for reference phrase detection."""
    intent = ParsedIntent(**intent_fields)
    intent.__dict__["_original_message"] = message
    return mgr.merge_context(session, intent)


class TestStaleFloatIdRegression:
    """Bug #1: float_id must not leak into a region-scoped follow-up."""

    def test_float_then_named_region_drops_float(self) -> None:
        mgr = InMemoryConversationManager()
        _seed(mgr, "s", variables=["DOXY"], float_id="7902250")

        # Even with reference, a region-scoped follow-up drops float_id
        follow_up = ParsedIntent(
            intent="profile_plot", variables=["DOXY"], region="arabian_sea"
        )
        follow_up.__dict__["_original_message"] = "oxygen in Arabian Sea"
        merged = mgr.merge_context("s", follow_up)

        assert merged.region == "arabian_sea"
        assert merged.float_id is None, (
            "float_id from a previous turn must not poison a region-scoped query"
        )

    def test_float_then_bbox_drops_float(self) -> None:
        mgr = InMemoryConversationManager()
        _seed(mgr, "s", variables=["DOXY"], float_id="7902250")

        follow_up = ParsedIntent(
            intent="profile_plot",
            variables=["DOXY"],
            lat_min=0.0,
            lat_max=30.0,
            lon_min=45.0,
            lon_max=80.0,
        )
        follow_up.__dict__["_original_message"] = "oxygen in that bbox"
        merged = mgr.merge_context("s", follow_up)
        assert merged.float_id is None

    def test_float_then_variable_only_with_same_float(self) -> None:
        """The 'same float, different variable' case MUST work with reference."""
        mgr = InMemoryConversationManager()
        _seed(mgr, "s", variables=["DOXY"], float_id="7902250")

        follow_up = ParsedIntent(intent="profile_plot", variables=["CHLA"])
        follow_up.__dict__["_original_message"] = "chlorophyll for the same float"
        merged = mgr.merge_context("s", follow_up)
        assert merged.float_id == "7902250"

    def test_float_then_variable_only_no_reference_no_inherit(self) -> None:
        """Priority 2: Without reference phrase, float_id NOT inherited."""
        mgr = InMemoryConversationManager()
        _seed(mgr, "s", variables=["DOXY"], float_id="7902250")

        follow_up = ParsedIntent(intent="profile_plot", variables=["CHLA"])
        follow_up.__dict__["_original_message"] = "chlorophyll"
        merged = mgr.merge_context("s", follow_up)
        assert merged.float_id is None  # No reference → no inheritance

    def test_float_then_float_new_float_wins(self) -> None:
        mgr = InMemoryConversationManager()
        _seed(mgr, "s", variables=["DOXY"], float_id="7902250")

        follow_up = ParsedIntent(
            intent="profile_plot", variables=["DOXY"], float_id="1901234"
        )
        follow_up.__dict__["_original_message"] = "oxygen for float 1901234"
        merged = mgr.merge_context("s", follow_up)
        assert merged.float_id == "1901234"

    def test_explicit_float_and_region_together_are_preserved(self) -> None:
        mgr = InMemoryConversationManager()
        _seed(mgr, "s", variables=["DOXY"], float_id="7902250")

        follow_up = ParsedIntent(
            intent="profile_plot",
            variables=["DOXY"],
            region="arabian_sea",
            float_id="1901234",
        )
        follow_up.__dict__["_original_message"] = "oxygen for float 1901234 in Arabian Sea"
        merged = mgr.merge_context("s", follow_up)

        assert merged.region == "arabian_sea"
        assert merged.float_id == "1901234"


class TestStaleProfileNumberRegression:
    """Bug #2: profile_number must not leak into follow-ups inappropriately."""

    def test_profile_then_named_region_drops_profile(self) -> None:
        mgr = InMemoryConversationManager()
        _seed(
            mgr,
            "s",
            variables=["DOXY"],
            region="arabian_sea",
            float_id="3902490",
            profile_number=52,
        )

        follow_up = ParsedIntent(
            intent="profile_plot", variables=["PSAL"], region="arabian_sea"
        )
        follow_up.__dict__["_original_message"] = "salinity in Arabian Sea"
        merged = mgr.merge_context("s", follow_up)

        assert merged.region == "arabian_sea"
        assert merged.profile_number is None
        assert merged.float_id is None

    def test_profile_then_variable_only_no_float_drops_profile(self) -> None:
        mgr = InMemoryConversationManager()
        _seed(mgr, "s", variables=["DOXY"])
        stored = mgr.get_context("s")
        stored.last_profile_number = 52

        follow_up = ParsedIntent(intent="profile_plot", variables=["DOXY"])
        follow_up.__dict__["_original_message"] = "same"
        merged = mgr.merge_context("s", follow_up)
        # No float_id in merged intent → profile_number not inherited
        assert merged.profile_number is None

    def test_profile_then_float_reattaches_profile(self) -> None:
        """With reference phrase, float_id + profile_number inherited together."""
        mgr = InMemoryConversationManager()
        _seed(
            mgr,
            "s",
            variables=["DOXY"],
            float_id="3902490",
            profile_number=52,
        )

        follow_up = ParsedIntent(intent="profile_plot", variables=["CHLA"])
        follow_up.__dict__["_original_message"] = "chlorophyll for the same float"
        merged = mgr.merge_context("s", follow_up)
        assert merged.float_id == "3902490"
        assert merged.profile_number == 52

    def test_profile_then_explicit_float_only_no_profile_leak(self) -> None:
        """Follow-up gives a NEW explicit float_id but no profile.
        The old profile_number belongs to the OLD float — must not leak.
        Priority 2: New float_id overrides, profile_number from old float NOT inherited."""
        mgr = InMemoryConversationManager()
        _seed(
            mgr,
            "s",
            variables=["DOXY"],
            float_id="3902490",
            profile_number=52,
        )

        follow_up = ParsedIntent(
            intent="profile_plot", variables=["DOXY"], float_id="1901234"
        )
        follow_up.__dict__["_original_message"] = "oxygen for float 1901234"
        merged = mgr.merge_context("s", follow_up)
        assert merged.float_id == "1901234"
        # Profile_number 52 belonged to float 3902490 — not inherited for new float
        assert merged.profile_number is None


class TestRegionAndSequenceBehavior:
    """Cross-cutting sequences that reproduce the exact bug-report flows."""

    def test_region_then_region_preserves_topic_only(self) -> None:
        mgr = InMemoryConversationManager()
        parser_intents = [
            ParsedIntent(
                intent="profile_plot", variables=["DOXY"], region="arabian_sea"
            ),
            ParsedIntent(
                intent="profile_plot", variables=["BBP700"], region="arabian_sea"
            ),
            ParsedIntent(
                intent="profile_plot", variables=["PSAL"], region="arabian_sea"
            ),
        ]
        # Each has its own region, so no float_id/profile leak
        for p in parser_intents:
            p.__dict__["_original_message"] = f"variable in Arabian Sea"
            merged = mgr.merge_context("s", p)
            assert merged.float_id is None
            assert merged.profile_number is None
            mgr.update_context(
                "s", merged, ChatResponse(intent=merged.intent, message="ok")
            )

    def test_region_then_profile_number_only_still_needs_float(self) -> None:
        mgr = InMemoryConversationManager()
        _seed(mgr, "s", variables=["DOXY"], region="arabian_sea")
        stored = mgr.get_context("s")
        stored.last_profile_number = 52

        follow_up = ParsedIntent(
            intent="profile_plot", variables=["PSAL"], region="arabian_sea"
        )
        follow_up.__dict__["_original_message"] = "salinity in Arabian Sea"
        merged = mgr.merge_context("s", follow_up)
        assert merged.profile_number is None

    def test_clean_session_no_inheritance(self) -> None:
        mgr = InMemoryConversationManager()
        p = ParsedIntent(
            intent="profile_plot", variables=["DOXY"], region="arabian_sea"
        )
        merged = mgr.merge_context("s", p)
        assert merged.model_dump() == p.model_dump()

    def test_full_repro_sequence_A(self) -> None:
        mgr = InMemoryConversationManager()
        t1 = ParsedIntent(
            intent="profile_plot", variables=["DOXY"], float_id="7902250"
        )
        t1.__dict__["_original_message"] = "float 7902250 oxygen"
        m1 = mgr.merge_context("s", t1)
        mgr.update_context(
            "s", m1, ChatResponse(intent="profile_plot", message="ok")
        )

        t2 = ParsedIntent(
            intent="profile_plot", variables=["DOXY"], region="arabian_sea"
        )
        t2.__dict__["_original_message"] = "oxygen in Arabian Sea"
        m2 = mgr.merge_context("s", t2)
        assert m2.region == "arabian_sea"
        assert m2.float_id is None

    def test_full_repro_sequence_B(self) -> None:
        mgr = InMemoryConversationManager()
        t1 = ParsedIntent(
            intent="profile_plot",
            variables=["DOXY"],
            region="arabian_sea",
            profile_number=52,
        )
        t1.__dict__["_original_message"] = "oxygen profile 52 in Arabian Sea"
        m1 = mgr.merge_context("s", t1)
        mgr.update_context(
            "s", m1, ChatResponse(intent="profile_plot", message="ok")
        )

        t2 = ParsedIntent(
            intent="profile_plot", variables=["PSAL"], region="arabian_sea"
        )
        t2.__dict__["_original_message"] = "salinity in Arabian Sea"
        m2 = mgr.merge_context("s", t2)
        assert m2.region == "arabian_sea"
        assert m2.profile_number is None
        assert m2.float_id is None

    def test_full_repro_sequence_C_topic_follow_ups(self) -> None:
        """Sequence C: topic-only follow-ups with reference phrases inherit region."""
        mgr = InMemoryConversationManager()
        t1 = ParsedIntent(
            intent="profile_plot", variables=["DOXY"], region="arabian_sea"
        )
        t1.__dict__["_original_message"] = "oxygen in Arabian Sea"
        m1 = mgr.merge_context("s", t1)
        mgr.update_context(
            "s", m1, ChatResponse(intent="profile_plot", message="ok")
        )

        for new_var in ["PSAL", "TEMP", "CHLA"]:
            follow = ParsedIntent(intent="profile_plot", variables=[new_var])
            follow.__dict__["_original_message"] = f"show {new_var.lower()} in the same region"
            m = mgr.merge_context("s", follow)
            assert m.variables == [new_var]
            assert m.region == "arabian_sea"  # inherited via "same region"
            assert m.float_id is None
            assert m.profile_number is None
            mgr.update_context(
                "s", m, ChatResponse(intent="profile_plot", message="ok")
            )

    def test_full_repro_sequence_D_same_region_year_same_float(self) -> None:
        mgr = InMemoryConversationManager()
        t1 = ParsedIntent(
            intent="profile_plot",
            variables=["TEMP", "DOXY"],
            region="arabian_sea",
        )
        t1.__dict__["_original_message"] = "temperature and oxygen in Arabian Sea"
        m1 = mgr.merge_context("s", t1)
        mgr.update_context(
            "s", m1, ChatResponse(intent="profile_plot", message="ok")
        )

        # "same region but in 2024" → general reference inherits all
        t2 = ParsedIntent(intent="profile_plot", variables=[], year=2024)
        t2.__dict__["_original_message"] = "same region but in 2024"
        m2 = mgr.merge_context("s", t2)
        assert m2.region == "arabian_sea"
        assert m2.year == 2024
        assert m2.float_id is None
        assert m2.variables == ["TEMP", "DOXY"]
        mgr.update_context(
            "s", m2, ChatResponse(intent="profile_plot", message="ok")
        )

        # "same float" — but no float in context → nothing to attach
        t3 = ParsedIntent(intent="profile_plot", variables=[])
        t3.__dict__["_original_message"] = "same float"
        m3 = mgr.merge_context("s", t3)
        assert m3.float_id is None

    def test_reload_creates_fresh_session(self) -> None:
        mgr = InMemoryConversationManager()
        _seed(mgr, "old", variables=["DOXY"], float_id="7902250", profile_number=52)

        new_intent = ParsedIntent(
            intent="profile_plot", variables=["DOXY"], region="arabian_sea"
        )
        merged = mgr.merge_context("new-session-after-reload", new_intent)
        assert merged.region == "arabian_sea"
        assert merged.float_id is None
        assert merged.profile_number is None
