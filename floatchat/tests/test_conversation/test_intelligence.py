"""Phase 4 — Conversation Intelligence: deterministic multi-turn context.

Coverage:
  * reference resolution into grounded facts (complete) — inheritance gates,
    subordination, comparison anchoring, ambiguous-referent clarification;
  * scientific focus tracking (update) — slot lifetimes, replacement, expiry;
  * conversation control commands ("Clear context.") — session management;
  * the required conversational battery end-to-end through the real semantic
    pipeline (LLM transport stubbed only);
  * parity: fully explicit requests are byte-identical with CI active;
  * purity: no LLM/SQL/DuckDB/planner/executor imports in the layer.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from floatchat.conversation.intelligence import (
    ContextResolution,
    ConversationFocus,
    ConversationIntelligence,
)
from floatchat.understanding.reasoner import GroundedUtterance, SemanticReasoner
from floatchat.understanding.service import SemanticUnderstandingService


# --------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------- #
def utter(**over) -> GroundedUtterance:
    base = dict(
        intent_hint="unknown",
        variables=(),
        regions=(),
        comparison_regions=(),
        float_ids=(),
        lat=None,
        lon=None,
        radius_km=None,
        place_mentioned=False,
        profile_number=None,
        existence_check=False,
        operational_filter=None,
        temporal_fields={},
        depth_min=None,
        depth_max=None,
        existence_comparison_hint=False,
        follow_up_reference=False,
    )
    base.update(over)
    return GroundedUtterance(**base)


def understanding(**over) -> SimpleNamespace:
    base = dict(concept_mentions=[])
    base.update(over)
    return SimpleNamespace(**base)


class CannedLLM:
    """Deterministic AbstractLLMService double (transport stub only)."""

    def __init__(self, routes: dict[str, object]):
        self._routes = dict(routes)
        self.calls: list[str] = []

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        import json

        self.calls.append(prompt)
        for needle, payload in self._routes.items():
            if needle in prompt:
                if isinstance(payload, Exception):
                    raise payload
                return json.dumps(payload) if isinstance(payload, dict) else payload
        raise AssertionError(f"CannedLLM: no route for prompt: {prompt[:80]}")


def make_ci() -> ConversationIntelligence:
    return ConversationIntelligence(max_turns=10)


def seed_float_focus(
    ci: ConversationIntelligence,
    session: str,
    *,
    float_id: str = "5906969",
    profile: int | None = None,
    variables: tuple[str, ...] = (),
    region: str | None = None,
    comparison_kind: str | None = None,
    comparison_members: tuple[str, ...] = (),
) -> ConversationFocus:
    focus = ConversationFocus(
        session_id=session,
        float_id=float_id,
        profile_number=profile,
        variables=variables,
        region=region,
        comparison_kind=comparison_kind,
        comparison_members=comparison_members,
    )
    ci._store[session] = focus
    return focus


# --------------------------------------------------------------------- #
# Reference resolution gates
# --------------------------------------------------------------------- #
class TestInheritanceGates:
    def test_no_followup_signal_means_no_inheritance(self):
        """Fully explicit/standalone requests are never altered by memory
        (the semantic analog of the legacy reference-phrase gate)."""
        ci = make_ci()
        seed_float_focus(ci, "s", float_id="5906969", profile=142, variables=("PSAL",))
        g = utter(follow_up_reference=False)
        out = ci.complete("s", g, understanding())
        assert out.utterance is g
        assert out.resolutions == ()

    def test_followup_with_no_memory_inherits_nothing_but_traces(self):
        ci = make_ci()
        out = ci.complete("s", utter(follow_up_reference=True), understanding())
        assert out.utterance.float_ids == ()
        assert any("no active context" in r for r in out.resolutions)

    def test_expired_focus_inherits_nothing(self):
        ci = make_ci()
        focus = seed_float_focus(ci, "s", float_id="5906969")
        focus.turn_count = ci._max_turns  # expiry boundary
        out = ci.complete("s", utter(follow_up_reference=True), understanding())
        assert out.utterance.float_ids == ()
        assert any("expired" in r for r in out.resolutions)
        assert ci.focus("s") is None  # lazily cleared

    def test_explicit_facts_always_win(self):
        """An explicit grounded float is never overwritten by memory."""
        ci = make_ci()
        seed_float_focus(ci, "s", float_id="5906969", profile=142)
        g = utter(follow_up_reference=True, float_ids=("1902190",))
        out = ci.complete("s", g, understanding())
        assert out.utterance.float_ids == ("1902190",)
        # …and the active profile of the OTHER float is not inherited
        assert out.utterance.profile_number is None


# --------------------------------------------------------------------- #
# Context inheritance + replacement
# --------------------------------------------------------------------- #
class TestInheritance:
    def test_variable_only_followup_inherits_float_and_profile(self):
        ci = make_ci()
        seed_float_focus(ci, "s", float_id="5906969", profile=142, variables=("DOXY",))
        g = utter(follow_up_reference=True, intent_hint="profile_plot", variables=("PSAL",))
        out = ci.complete("s", g, understanding())
        assert out.utterance.float_ids == ("5906969",)
        assert out.utterance.profile_number == 142
        assert out.utterance.variables == ("PSAL",)  # explicit variable wins
        joined = " ".join(out.resolutions)
        assert "float_id=5906969" in joined and "profile=142" in joined

    def test_float_only_followup_inherits_active_variables(self):
        ci = make_ci()
        seed_float_focus(ci, "s", float_id="5906969", variables=("PSAL",))
        g = utter(follow_up_reference=True, intent_hint="profile_plot")
        out = ci.complete("s", g, understanding())
        assert out.utterance.variables == ("PSAL",)

    def test_metadata_followup_inherits_float_only(self):
        """'What sensors does it carry?' → inherit float; never variables
        (metadata is about the float, not a measurement)."""
        ci = make_ci()
        seed_float_focus(ci, "s", float_id="5906969", variables=("PSAL",), profile=142)
        g = utter(follow_up_reference=True, intent_hint="unknown")
        out = ci.complete("s", g, understanding(concept_mentions=["sensors"]))
        assert out.utterance.float_ids == ("5906969",)
        assert out.utterance.variables == ()
        assert out.utterance.profile_number is None

    def test_region_scoped_followup_does_not_inherit_float(self):
        ci = make_ci()
        seed_float_focus(ci, "s", float_id="5906969")
        g = utter(follow_up_reference=True, regions=("bay_of_bengal",))
        out = ci.complete("s", g, understanding())
        assert out.utterance.float_ids == ()
        assert out.utterance.regions == ("bay_of_bengal",)

    def test_trajectory_followup_inherits_active_float_only(self):
        """Trajectory consumes exactly one float (engine contract) — the
        comparison's second float is never smuggled in."""
        ci = make_ci()
        seed_float_focus(
            ci, "s", float_id="5906969",
            comparison_kind="floats", comparison_members=("1902190", "5906969"),
        )
        g = utter(follow_up_reference=True, intent_hint="trajectory")
        out = ci.complete("s", g, understanding())
        assert out.utterance.float_ids == ("5906969",)
        assert out.utterance.comparison_regions == ()


# --------------------------------------------------------------------- #
# Comparison context
# --------------------------------------------------------------------- #
class TestComparisonContext:
    def test_compare_with_explicit_float_completes_partner(self):
        """'Compare with float 1902190.' → partner is the active float."""
        ci = make_ci()
        seed_float_focus(ci, "s", float_id="5906969", variables=("PSAL",))
        g = utter(
            follow_up_reference=True,
            intent_hint="comparison_plot",
            float_ids=("1902190",),
            existence_comparison_hint=True,
        )
        out = ci.complete("s", g, understanding())
        assert out.utterance.float_ids == ("1902190", "5906969")
        assert out.utterance.variables == ("PSAL",)
        assert any("partner" in r for r in out.resolutions)

    def test_ongoing_comparison_participants_are_inherited(self):
        """'Now compare salinity.' after a comparison → same participants."""
        ci = make_ci()
        seed_float_focus(
            ci, "s",
            comparison_kind="regions",
            comparison_members=("arabian_sea", "bay_of_bengal"),
        )
        g = utter(
            follow_up_reference=True,
            intent_hint="comparison_plot",
            existence_comparison_hint=True,
        )
        out = ci.complete("s", g, understanding())
        assert out.utterance.comparison_regions == ("arabian_sea", "bay_of_bengal")

    def test_compare_without_context_passes_through_for_the_reasoner(self):
        """Responsibility 6: 'Compare oxygen.' with no comparison context at
        all — CI has nothing to anchor, leaves the one-sided comparison
        untouched (never guesses participants); the reasoner's
        `comparison_incomplete` rule asks. CI's own clarifications are
        reserved for memory-created ambiguity."""
        ci = make_ci()
        g = utter(
            follow_up_reference=True,
            intent_hint="comparison_plot",
            variables=("DOXY",),
            existence_comparison_hint=True,
        )
        out = ci.complete("s", g, understanding())
        assert out.clarification is None
        assert out.utterance.float_ids == ()
        assert any("no active context" in r for r in out.resolutions)

    def test_compare_without_context_clarifies_end_to_end(self, monkeypatch):
        """Pipeline-level: the user is ASKED, never guessed — the reasoner's
        comparison_incomplete clarification surfaces unchanged."""
        from floatchat.config import settings

        monkeypatch.setattr(settings, "semantic_understanding_enabled", True)
        monkeypatch.setattr(settings, "llm_enabled", True)
        monkeypatch.setattr(settings, "semantic_model", "test-model")
        svc = SemanticUnderstandingService(
            service=CannedLLM(
                {
                    "Compare oxygen.": {
                        "intent_name": "comparison_plot", "confidence": 0.75,
                        "variable_mentions": ["oxygen"],
                        "comparison": {"is_comparison": True},
                        "follow_up_reference": True,
                    }
                }
            ),
            conversation_intelligence=make_ci(),
        )
        outcome = svc.resolve("Compare oxygen.", session_id="fresh")
        assert outcome.parsed_intent is None
        assert outcome.clarification is not None
        assert outcome.clarification.field == "comparison"
        assert outcome.reasoning_rule == "comparison_incomplete"

    def test_single_float_reference_with_only_comparison_memory_clarifies(self):
        """'Plot the deepest one.' with two candidate floats → ask."""
        ci = make_ci()
        ci._store["s"] = ConversationFocus(
            session_id="s",
            comparison_kind="floats",
            comparison_members=("1902190", "5906969"),
        )
        g = utter(follow_up_reference=True, intent_hint="profile_plot")
        out = ci.complete("s", g, understanding())
        assert out.clarification is not None
        assert set(out.clarification.candidates) == {"1902190", "5906969"}


# --------------------------------------------------------------------- #
# Focus updates + lifetime
# --------------------------------------------------------------------- #
class TestFocusUpdates:
    def _decision(self, **kw):
        base = dict(
            intent="profile_plot", variables=(), region=None, float_id=None,
            comparison_float_ids=(), comparison_regions=(), clarification=None,
        )
        base.update(kw)
        return SimpleNamespace(**base)

    def test_new_float_replaces_and_clears_profile(self):
        """Responsibility 4: 'Now show float 1902190' → active float becomes
        1902190, profile of the old float is dropped."""
        ci = make_ci()
        focus = seed_float_focus(ci, "s", float_id="5906969", profile=142)
        ci.update("s", self._decision(float_id="1902190"))
        assert focus.float_id == "1902190"
        assert focus.profile_number is None

    def test_comparison_decision_creates_comparison_slot_not_float(self):
        ci = make_ci()
        focus = seed_float_focus(ci, "s", float_id="5906969")
        ci.update(
            "s",
            self._decision(
                intent="comparison_plot",
                variables=("PSAL",),
                comparison_float_ids=("1902190", "5906969"),
            ),
        )
        assert focus.comparison_kind == "floats"
        assert focus.comparison_members == ("1902190", "5906969")
        assert focus.float_id == "5906969"  # float slot untouched
        assert focus.variables == ("PSAL",)

    def test_clarification_turn_counts_but_changes_no_slots(self):
        ci = make_ci()
        focus = seed_float_focus(ci, "s", float_id="5906969", variables=("DOXY",))
        turns_before = focus.turn_count
        ci.update("s", None)
        assert focus.turn_count == turns_before + 1
        assert focus.float_id == "5906969"
        assert focus.variables == ("DOXY",)

    def test_profile_slot_updates_with_float_match_only(self):
        ci = make_ci()
        focus = seed_float_focus(ci, "s", float_id="5906969")
        decision = self._decision(float_id="5906969")
        ci.update("s", decision, utter(float_ids=("5906969",), profile_number=142))
        assert focus.profile_number == 142


# --------------------------------------------------------------------- #
# Conversation control
# --------------------------------------------------------------------- #
class TestControlCommands:
    @pytest.mark.parametrize(
        "message",
        ["Clear context.", "clear context", "Clear the context!", "forget that", "start over"],
    )
    def test_clear_variants_clear_both_layers(self, message):
        ci = make_ci()
        seed_float_focus(ci, "s", float_id="5906969")
        result = ci.handle_control(message, "s")
        assert result is not None and result.action == "clear_context"
        assert ci.focus("s") is None
        assert "cleared" in result.acknowledgment.lower()

    def test_non_control_message_passes_through(self):
        ci = make_ci()
        assert ci.handle_control("show oxygen near goa", "s") is None
        assert ci.handle_control("clearly show me floats", "s") is None

    def test_control_without_session_is_noop(self):
        ci = make_ci()
        assert ci.handle_control("Clear context.", None) is None


# --------------------------------------------------------------------- #
# Purity — the layer never reaches below its boundary
# --------------------------------------------------------------------- #
class TestPurity:
    def test_no_forbidden_imports(self):
        import ast
        import inspect

        from floatchat.conversation import intelligence as mod

        tree = ast.parse(inspect.getsource(mod))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        for forbidden in (
            "floatchat.llm_service",
            "floatchat.data_lake",
            "floatchat.query_engine",
            "floatchat.retrieval_planner",
            "duckdb",
        ):
            assert not any(
                m == forbidden or m.startswith(forbidden + ".") for m in imported
            ), forbidden

    def test_resolution_and_clarification_are_immutable(self):
        ci = make_ci()
        out = ci.complete("s", utter(follow_up_reference=True), understanding())
        assert isinstance(out, ContextResolution)
        with pytest.raises(Exception):
            out.resolutions = ("x",)  # frozen dataclass


# --------------------------------------------------------------------- #
# The required conversational battery (through the REAL pipeline)
# --------------------------------------------------------------------- #
class TestConversationalBattery:
    """'Tell me about float 5906969. / Plot oxygen. / Now salinity. /
    Show profile 142. / Compare with float 1902190. / Now chlorophyll. /
    Show trajectories. / Clear context. / Plot oxygen.'

    Driven through SemanticUnderstandingService → grounding → Conversation
    Intelligence → Semantic Reasoner → ParsedIntent; only the LLM transport
    is stubbed.
    """

    PAYLOADS = {
        "Tell me about float 5906969.": {
            "intent_name": "unknown", "confidence": 0.75,
            "float_ids": ["5906969"], "concept_mentions": ["float details"],
        },
        "Plot oxygen.": {
            "intent_name": "profile_plot", "confidence": 0.9,
            "variable_mentions": ["oxygen"], "follow_up_reference": True,
        },
        "Now salinity.": {
            "intent_name": "profile_plot", "confidence": 0.9,
            "variable_mentions": ["salinity"], "follow_up_reference": True,
        },
        "Show profile 142.": {
            "intent_name": "unknown", "confidence": 0.8,
            "profile_number": 142, "follow_up_reference": True,
        },
        "Compare with float 1902190.": {
            "intent_name": "comparison_plot", "confidence": 0.88,
            "comparison": {"is_comparison": True, "float_ids": ["1902190"]},
            "follow_up_reference": True,
        },
        "Now chlorophyll.": {
            "intent_name": "comparison_plot", "confidence": 0.9,
            "variable_mentions": ["chlorophyll"],
            "comparison": {"is_comparison": True},
            "follow_up_reference": True,
        },
        "Show trajectories.": {
            "intent_name": "trajectory", "confidence": 0.87,
            "follow_up_reference": True,
        },
    }

    def _service(self, ci: ConversationIntelligence) -> SemanticUnderstandingService:
        return SemanticUnderstandingService(
            service=CannedLLM(self.PAYLOADS),
            conversation_intelligence=ci,
        )

    def test_battery(self, monkeypatch, caplog):
        from floatchat.config import settings

        monkeypatch.setattr(settings, "semantic_understanding_enabled", True)
        monkeypatch.setattr(settings, "llm_enabled", True)
        monkeypatch.setattr(settings, "semantic_model", "test-model")

        ci = make_ci()
        svc = self._service(ci)
        session = "battery"

        with caplog.at_level(logging.INFO):
            # 1 — metadata objective establishes the float focus
            o = svc.resolve("Tell me about float 5906969.", session_id=session)
            assert o.parsed_intent.intent == "metadata_lookup"
            assert o.parsed_intent.float_id == "5906969"
            assert ci.focus(session).float_id == "5906969"

            # 2 — follow-up inherits the active float
            o = svc.resolve("Plot oxygen.", session_id=session)
            assert o.parsed_intent.intent == "profile_plot"
            assert o.parsed_intent.variables == ["DOXY"]
            assert o.parsed_intent.float_id == "5906969"  # INHERITED
            assert any("float_id=5906969" in r for r in o.context_resolutions)
            assert ci.focus(session).variables == ("DOXY",)  # UPDATED

            # 3 — variable switch, float + profile still inherited
            o = svc.resolve("Now salinity.", session_id=session)
            assert o.parsed_intent.variables == ["PSAL"]
            assert o.parsed_intent.float_id == "5906969"
            assert ci.focus(session).variables == ("PSAL",)

            # 4 — explicit new profile on the inherited float; vars inherited
            o = svc.resolve("Show profile 142.", session_id=session)
            assert o.parsed_intent.intent == "profile_plot"
            assert o.parsed_intent.float_id == "5906969"
            assert o.parsed_intent.profile_number == 142
            assert o.parsed_intent.variables == ["PSAL"]  # inherited
            assert ci.focus(session).profile_number == 142  # UPDATED

            # 5 — comparison partner anchored by the active float
            o = svc.resolve("Compare with float 1902190.", session_id=session)
            assert o.parsed_intent.intent == "comparison_plot"
            assert o.parsed_intent.comparison_float_ids == ["1902190", "5906969"]
            assert o.parsed_intent.variables == ["PSAL"]  # inherited variable
            assert any("partner" in r for r in o.context_resolutions)
            assert ci.focus(session).comparison_members == ("1902190", "5906969")

            # 6 — ongoing comparison: participants stay active
            o = svc.resolve("Now chlorophyll.", session_id=session)
            assert o.parsed_intent.intent == "comparison_plot"
            assert o.parsed_intent.comparison_float_ids == ["1902190", "5906969"]
            assert o.parsed_intent.variables == ["CHLA"]
            assert any("ongoing comparison" in r for r in o.context_resolutions)

            # 7 — trajectory follows the active float slot (single float)
            o = svc.resolve("Show trajectories.", session_id=session)
            assert o.parsed_intent.intent == "trajectory"
            assert o.parsed_intent.float_id == "5906969"
            assert not o.parsed_intent.comparison_float_ids

            # 8 — control command clears the memory
            result = ci.handle_control("Clear context.", session)
            assert result is not None
            assert ci.focus(session) is None

            # 9 — after clearing, nothing is inherited
            o = svc.resolve("Plot oxygen.", session_id=session)
            assert o.parsed_intent.intent == "profile_plot"
            assert o.parsed_intent.variables == ["DOXY"]
            assert o.parsed_intent.float_id is None  # NOT inherited
            assert any("no active context" in r for r in o.context_resolutions)

        ctx_lines = [r.getMessage() for r in caplog.records if "CONVERSATION_CONTEXT" in r.getMessage()]
        assert any('reason=\'follow-up request\'' in line for line in ctx_lines)
        assert any('reason=\'objective update\'' in line for line in ctx_lines)


# --------------------------------------------------------------------- #
# Resolver-level integration: CI owns semantic-path context
# --------------------------------------------------------------------- #
class TestResolverIntegration:
    def test_semantic_path_inherits_through_resolver(self, monkeypatch):
        """resolver → understanding.resolve(session_id=…) → CI completes the
        reference before the reasoner; the legacy merge is not involved."""
        from floatchat.config import settings
        from floatchat.conversation.memory import InMemoryConversationManager
        from floatchat.intent_parser.regex import RegexIntentParser
        from floatchat.intent_resolution.resolver import IntentResolver

        monkeypatch.setattr(settings, "semantic_understanding_enabled", True)
        monkeypatch.setattr(settings, "llm_enabled", True)
        monkeypatch.setattr(settings, "semantic_model", "test-model")

        routes = {
            "Tell me about float 5906969.": {
                "intent_name": "unknown", "confidence": 0.75,
                "float_ids": ["5906969"], "concept_mentions": ["info"],
            },
            "Now plot salinity.": {
                "intent_name": "profile_plot", "confidence": 0.9,
                "variable_mentions": ["salinity"], "follow_up_reference": True,
            },
        }
        svc = SemanticUnderstandingService(
            service=CannedLLM(routes), conversation_intelligence=make_ci()
        )
        manager = InMemoryConversationManager()
        resolver = IntentResolver(
            parser=RegexIntentParser(),
            compiler=None,
            conversation_manager=manager,
            understanding=svc,
        )
        first = resolver.resolve("Tell me about float 5906969.", session_id="r1")
        assert first.intent == "metadata_lookup"

        follow = resolver.resolve("Now plot salinity.", session_id="r1")
        assert follow.intent == "profile_plot"
        assert follow.variables == ["PSAL"]
        assert follow.float_id == "5906969"  # inherited by CI, pre-reasoner


# --------------------------------------------------------------------- #
# API-level conversation control: one command clears BOTH context layers
# --------------------------------------------------------------------- #
class TestChatControlCommand:
    def test_clear_context_shortcircuits_and_clears(self):
        from unittest.mock import MagicMock

        from floatchat.api.schemas import ChatRequest
        from floatchat.api.services.chat_service import handle_chat
        from floatchat.conversation.memory import InMemoryConversationManager
        from floatchat.models import ConversationContext

        ci = make_ci()
        seed_float_focus(ci, "chat-s", float_id="5906969")
        manager = InMemoryConversationManager()
        manager._store["chat-s"] = ConversationContext(
            session_id="chat-s", last_float_id="5906969"
        )
        response = handle_chat(
            ChatRequest(message="Clear context.", session_id="chat-s"),
            MagicMock(),  # classifier — must not be reached
            MagicMock(),  # llm_service
            MagicMock(),  # intent_parser
            MagicMock(),  # intent_resolver
            MagicMock(),  # query_engine
            manager,
            MagicMock(),  # knowledge_base
            conversation_intelligence=ci,
        )
        assert response.intent == "general_chat"
        assert "cleared" in response.message.lower()
        assert response.data_summary["action"] == "clear_context"
        assert ci.focus("chat-s") is None  # CI memory cleared
        assert manager.get_context("chat-s") is None  # legacy memory cleared


# --------------------------------------------------------------------- #
# Parity — fully explicit requests are unchanged by CI
# --------------------------------------------------------------------- #
class TestExplicitRequestParity:
    def test_explicit_request_identical_with_and_without_ci(self, monkeypatch):
        from floatchat.config import settings

        monkeypatch.setattr(settings, "semantic_understanding_enabled", True)
        monkeypatch.setattr(settings, "llm_enabled", True)
        monkeypatch.setattr(settings, "semantic_model", "test-model")

        payload = {
            "intent_name": "profile_plot", "confidence": 0.93,
            "variable_mentions": ["salinity"], "float_ids": ["1902190"],
            "profile_number": 284,
        }
        routes = {"Show salinity for float 1902190 profile 284": payload}
        without_ci = SemanticUnderstandingService(service=CannedLLM(routes))
        with_ci = SemanticUnderstandingService(
            service=CannedLLM(routes), conversation_intelligence=make_ci()
        )
        a = without_ci.resolve("Show salinity for float 1902190 profile 284")
        b = with_ci.resolve(
            "Show salinity for float 1902190 profile 284", session_id="s"
        )
        assert a.parsed_intent.model_dump() == b.parsed_intent.model_dump()
        assert b.context_resolutions == []  # nothing inherited, explicit wins
