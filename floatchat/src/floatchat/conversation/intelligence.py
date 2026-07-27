"""Conversation Intelligence — deterministic multi-turn scientific context (Phase 4).

Pipeline position (FloatChat 2.0 — Phase 4):

    Conversation Memory (per-session ConversationFocus)
                 │
                 ▼
    Conversation Intelligence  ← this module (deterministic; no LLM, no SQL,
                 │                no DuckDB, no planner/executor access)
                 ▼
    LLM Semantic Understanding → Grounding → GroundedUtterance
                 │
                 ▼
    **complete()** — references resolved into explicit grounded facts
                 │
                 ▼
    Semantic Reasoner (UNCHANGED, Phase 3) → ParsedIntent → Planner → Engine

The layer answers the conversational questions a single request cannot:
*What is "it"? What does "those floats" refer to? Which float/profile/variable
/comparison is currently active?* — and turns the answers into grounded facts
BEFORE the Semantic Reasoner selects an execution intent.

Design contract
---------------
* **Primary gate.** Inheritance happens only when the understanding signals a
  follow-up (``follow_up_reference`` — the semantic analog of the legacy
  keyword reference-phrase gate, without keywords). Fully explicit requests
  are never altered.
* **Explicit always wins.** A grounded fact in the current request replaces
  the memorised focus; it is never overwritten by memory.
* **Subordination.** An active profile belongs to its float: it is inherited
  only alongside that float and is cleared when the float is replaced.
* **Separate focus slots.** float, profile, variables, region and comparison
  are independent slots with their own lifetime rules (created / updated /
  replaced / expired / cleared — see :class:`ConversationFocus`).
* **Ask, never guess.** When a reference needs a single float but memory only
  holds a multi-float comparison (several candidate referents), the layer
  emits a clarification with the candidates.
* **Explainable.** Every inheritance and every focus update is recorded in
  the returned trace and emitted as one ``CONVERSATION_CONTEXT`` log line.

Boundaries: this module operates only on the understanding's structured
signals, the grounded-utterance contract it completes, stored
:class:`ConversationFocus` state, and (for conversation *control* commands
such as "clear context") the raw message text. Control-command detection is
session management, not intent routing — execution-intent selection remains
the Semantic Reasoner's sole authority.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Tuple

from floatchat.config import settings
from floatchat.understanding.reasoner import GroundedUtterance

logger = logging.getLogger(__name__)

#: Hints that read the single-float focus slot when completing a reference.
_COMPARISON_HINTS = ("comparison_plot", "comparison")
_SINGLE_FLOAT_OBJECTIVES = ("trajectory", "metadata_lookup", "profile_plot")


@dataclass
class ConversationFocus:
    """Conversation Memory — the per-session scientific focus.

    Slot lifetimes (deterministic):

    * ``float_id`` — created by the first float-bearing decision; replaced by
      a new explicit float (which also clears ``profile_number``); expired
      with the session; cleared by a control command.
    * ``profile_number`` — created only by an explicit profile on the active
      float; never inherited without its float; cleared on float replacement.
    * ``variables`` — updated by any decision carrying variables; inherited
      by follow-ups that name none.
    * ``region`` — updated by region-bearing decisions; read by follow-ups
      only when no float focus exists (float slot outranks region slot).
    * ``comparison_*`` — created by comparison decisions; members persist
      until replaced by a new comparison or cleared by a control command.
    * ``turn_count`` — every request processed by this layer; the whole
      focus expires at ``settings.conversation_max_turns`` (bounded memory,
      no indefinite growth).
    """

    session_id: str
    turn_count: int = 0
    float_id: str | None = None
    profile_number: int | None = None
    variables: Tuple[str, ...] = ()
    region: str | None = None
    comparison_kind: str | None = None  # "floats" | "regions"
    comparison_members: Tuple[str, ...] = ()
    last_intent: str | None = None
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@dataclass(frozen=True)
class ContextClarification:
    """A reference the layer cannot resolve deterministically — ask, don't guess."""

    question: str
    field: str
    candidates: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ContextResolution:
    """Result of reference resolution: a (possibly completed) utterance + trace."""

    utterance: GroundedUtterance
    resolutions: Tuple[str, ...] = ()
    clarification: ContextClarification | None = None


@dataclass(frozen=True)
class ControlResult:
    """A deterministic conversation-control command (session management)."""

    action: str
    acknowledgment: str


class ConversationIntelligence:
    """Deterministic Conversation Intelligence layer (Phase 4).

    Stateless-across-requests collaborator holding one bounded
    :class:`ConversationFocus` per session id.
    """

    #: Exact normalised phrases that clear conversational state. Session
    #: control, not intent routing.
    CONTROL_CLEAR_PHRASES = frozenset(
        {
            "clear context",
            "clear the context",
            "reset context",
            "forget context",
            "forget the context",
            "forget that",
            "start over",
            "new conversation",
        }
    )

    CLEAR_ACKNOWLEDGMENT = (
        "Conversation context cleared — I'm starting fresh. "
        "Which float, region, or variable would you like to explore?"
    )

    def __init__(self, max_turns: int | None = None) -> None:
        self._max_turns = max_turns or settings.conversation_max_turns
        self._store: dict[str, ConversationFocus] = {}

    # ------------------------------------------------------------------ #
    # Conversation control commands (session management)                  #
    # ------------------------------------------------------------------ #

    def handle_control(
        self, message: str, session_id: str | None
    ) -> ControlResult | None:
        """Detect a conversation-control command.

        Returns a :class:`ControlResult` when the message is an exact
        control phrase; the caller executes :meth:`clear` and answers with
        ``acknowledgment``. ``None`` means "not a control command — proceed
        through the normal pipeline".
        """
        if not session_id:
            return None
        normalised = re.sub(r"\s+", " ", message.strip().lower()).strip(" .!?")
        if normalised in self.CONTROL_CLEAR_PHRASES:
            self.clear(session_id)
            logger.info(
                "CONVERSATION_CONTEXT session=%s reason=%r action=clear_context",
                session_id,
                "control command",
            )
            return ControlResult(
                action="clear_context", acknowledgment=self.CLEAR_ACKNOWLEDGMENT
            )
        return None

    # ------------------------------------------------------------------ #
    # Memory access                                                       #
    # ------------------------------------------------------------------ #

    def focus(self, session_id: str) -> ConversationFocus | None:
        """Current focus for *session_id*, honouring turn-based expiry."""
        focus = self._store.get(session_id)
        if focus is None:
            return None
        if focus.turn_count >= self._max_turns:
            return None
        return focus

    def clear(self, session_id: str) -> None:
        """Drop all stored focus for *session_id* (control command / expiry)."""
        self._store.pop(session_id, None)

    # ------------------------------------------------------------------ #
    # Reference resolution — grounded facts in, completed utterance out   #
    # ------------------------------------------------------------------ #

    def complete(
        self,
        session_id: str,
        utterance: GroundedUtterance,
        understanding: Any,
    ) -> ContextResolution:
        """Resolve conversational references into explicit grounded facts.

        Runs strictly BEFORE the Semantic Reasoner on the semantic path.
        Only mutates gaps (fields the request left ungrounded); explicit
        grounded facts always win.
        """
        focus = self._store.get(session_id)
        expired = focus is not None and focus.turn_count >= self._max_turns
        if expired:
            # Bounded memory: expire the whole focus deterministically.
            self.clear(session_id)
            trace = [f"context expired after {focus.turn_count} turns"]
            if utterance.follow_up_reference:
                trace.append(
                    "follow-up reference but the active context has expired — "
                    "treating as a new request"
                )
            return ContextResolution(utterance=utterance, resolutions=tuple(trace))
        if focus is None:
            if utterance.follow_up_reference:
                return ContextResolution(
                    utterance=utterance,
                    resolutions=(
                        "follow-up reference but no active context — nothing to inherit",
                    ),
                )
            return ContextResolution(utterance=utterance)

        if not utterance.follow_up_reference:
            # Primary gate: no follow-up signal → the request stands alone.
            return ContextResolution(utterance=utterance)

        g = utterance
        trace: list[str] = []
        comparison_signal = (
            g.existence_comparison_hint or g.intent_hint in _COMPARISON_HINTS
        )
        metadata_followup = g.intent_hint == "metadata_lookup" or (
            not g.variables
            and bool(getattr(understanding, "concept_mentions", None))
        )

        if comparison_signal:
            # Comparison references are anchored from memory where possible.
            # What memory CANNOT anchor stays a one-sided comparison and is
            # clarified by the reasoner's `comparison_incomplete` rule — CI
            # only emits its own clarifications for memory-created ambiguity
            # (several candidate referents).
            g = self._complete_comparison(g, focus, trace)
            # A comparison follow-up inherits the active variable when it
            # names none ("Now compare salinity" / "Now chlorophyll").
            if not g.variables and focus.variables:
                trace.append(
                    f"inherited variable={','.join(focus.variables)} (active variable)"
                )
                g = replace(g, variables=tuple(focus.variables))
        elif metadata_followup:
            # Metadata follow-ups ("what sensors does it carry?") inherit the
            # active float ONLY — never variables/profile (legacy parity:
            # metadata is about the float, not a specific profile).
            if not g.float_ids and focus.float_id and not self._has_scope(g):
                trace.append(
                    f"inherited float_id={focus.float_id} (active float, metadata follow-up)"
                )
                g = replace(g, float_ids=(focus.float_id,))
        else:
            # --- single-objective reference resolution ------------------- #
            if not g.float_ids and not self._has_scope(g):
                if focus.float_id:
                    trace.append(
                        f"inherited float_id={focus.float_id} (active float)"
                    )
                    g = replace(g, float_ids=(focus.float_id,))
                elif (
                    focus.comparison_kind == "floats"
                    and len(focus.comparison_members) >= 2
                    and (g.intent_hint in _SINGLE_FLOAT_OBJECTIVES or g.intent_hint is None)
                ):
                    # "Plot the deepest one." with only a two-float comparison
                    # in memory: several candidate referents — ask, never guess.
                    members = ", ".join(focus.comparison_members)
                    trace.append(
                        f"reference needs one float but the active comparison holds {members}"
                    )
                    return ContextResolution(
                        utterance=g,
                        resolutions=tuple(trace),
                        clarification=ContextClarification(
                            question=(
                                "Which float do you mean — "
                                f"{', or '.join(focus.comparison_members)}?"
                            ),
                            field="float_id",
                            candidates=tuple(focus.comparison_members),
                        ),
                    )
            # Profile is subordinate to its float: inherit only alongside it.
            if (
                g.profile_number is None
                and focus.profile_number is not None
                and focus.float_id is not None
                and tuple(g.float_ids) == (focus.float_id,)
            ):
                trace.append(
                    f"inherited profile={focus.profile_number} (active profile of float {focus.float_id})"
                )
                g = replace(g, profile_number=focus.profile_number)
            # Region slot: read only when no float focus applies (float slot
            # outranks region slot for measurement objectives).
            if (
                not g.float_ids
                and not g.regions
                and not g.comparison_regions
                and g.lat is None
                and not g.place_mentioned
                and focus.region
            ):
                trace.append(f"inherited region={focus.region} (active region)")
                g = replace(g, regions=(focus.region,))
            if not g.variables and focus.variables:
                trace.append(
                    f"inherited variable={','.join(focus.variables)} (active variable)"
                )
                g = replace(g, variables=tuple(focus.variables))

        if trace:
            logger.info(
                "CONVERSATION_CONTEXT session=%s reason=%r inherited=%s",
                session_id,
                "follow-up request",
                ",".join(trace),
            )
        return ContextResolution(utterance=g, resolutions=tuple(trace))

    # ------------------------------------------------------------------ #
    # Focus updates — after each successful decision                      #
    # ------------------------------------------------------------------ #

    def update(
        self,
        session_id: str,
        decision: Any | None,
        utterance: GroundedUtterance | None = None,
    ) -> None:
        """Update the focus deterministically after a successful request.

        *decision* is the Semantic Reasoner's :class:`ReasoningDecision`, or
        ``None`` when the turn ended in clarification (turn counted, slots
        unchanged — an unresolved request changes no scientific focus).
        *utterance* is the completed grounded utterance (post reference
        resolution): the profile number lives there, not on the decision.
        """
        focus = self._store.get(session_id)
        if focus is None:
            focus = ConversationFocus(session_id=session_id)
            self._store[session_id] = focus
        focus.turn_count += 1
        focus.updated_at = datetime.now(timezone.utc)
        if decision is None or getattr(decision, "clarification", None) is not None:
            logger.debug(
                "CONVERSATION_CONTEXT session=%s turn=%d (clarification — focus unchanged)",
                session_id,
                focus.turn_count,
            )
            return

        changes: list[str] = []
        comparison_floats = tuple(getattr(decision, "comparison_float_ids", ()) or ())
        comparison_regions = tuple(getattr(decision, "comparison_regions", ()) or ())
        if len(comparison_floats) >= 2 or len(comparison_regions) >= 2:
            kind = "floats" if len(comparison_floats) >= 2 else "regions"
            members = comparison_floats if kind == "floats" else comparison_regions
            if kind != focus.comparison_kind or members != focus.comparison_members:
                focus.comparison_kind = kind
                focus.comparison_members = members
                changes.append(f"comparison={','.join(members)}")
        else:
            float_id = getattr(decision, "float_id", None)
            if float_id and float_id != focus.float_id:
                replaced = focus.float_id is not None
                focus.float_id = float_id
                focus.profile_number = None  # profile is subordinate to its float
                changes.append(f"float_id={float_id}")
                if replaced:
                    changes.append("profile cleared (float replaced)")
            profile = utterance.profile_number if utterance is not None else None
            utterance_float = (
                utterance.float_ids[0]
                if utterance is not None and len(utterance.float_ids) == 1
                else None
            )
            effective_float = float_id or utterance_float
            if profile is not None and effective_float and effective_float == focus.float_id:
                if profile != focus.profile_number:
                    focus.profile_number = profile
                    changes.append(f"profile={profile}")
        variables = tuple(getattr(decision, "variables", ()) or ())
        if variables and variables != tuple(focus.variables):
            focus.variables = variables
            changes.append(f"variable={','.join(variables)}")
        region = getattr(decision, "region", None)
        if region and region != focus.region:
            focus.region = region
            changes.append(f"region={region}")
        intent = getattr(decision, "intent", None)
        if intent and intent != "unknown":
            focus.last_intent = intent

        if changes:
            logger.info(
                "CONVERSATION_CONTEXT session=%s reason=%r updated=%s",
                session_id,
                "objective update",
                ",".join(changes),
            )
        else:
            logger.debug(
                "CONVERSATION_CONTEXT session=%s turn=%d focus unchanged",
                session_id,
                focus.turn_count,
            )

    # ------------------------------------------------------------------ #
    # Internals                                                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _has_scope(g: GroundedUtterance) -> bool:
        """The request already carries its own spatial/entity scope."""
        return bool(
            g.regions
            or g.comparison_regions
            or g.lat is not None
            or g.place_mentioned
        )

    def _complete_comparison(
        self,
        g: GroundedUtterance,
        focus: ConversationFocus,
        trace: list[str],
    ) -> GroundedUtterance:
        """Complete comparison references ("Compare with float X", "compare them").

        Anchors one or both sides from the active comparison slot / active
        float. Anything memory cannot anchor stays one-sided so the Semantic
        Reasoner's `comparison_incomplete` clarification asks — CI never
        guesses participants and never duplicates the reasoner's questions.
        """
        floats = tuple(g.float_ids)
        regions = tuple(g.comparison_regions) or (
            tuple(g.regions) if g.intent_hint in _COMPARISON_HINTS else ()
        )

        if len(floats) >= 2 or len(regions) >= 2:
            return g  # fully explicit new comparison — replaces slot at update

        if len(floats) == 1 and not regions:
            # One side explicit ("Compare with float 1902190"): the partner is
            # the active float; never the same float twice (that is the
            # reasoner's `comparison_incomplete` case).
            partner = (
                focus.float_id if focus.float_id and focus.float_id != floats[0] else None
            )
            if partner is None and (
                focus.comparison_kind == "floats"
                and floats[0] not in focus.comparison_members
                and focus.comparison_members
            ):
                partner = focus.comparison_members[0]
            if partner:
                trace.append(
                    f"inherited comparison partner float={partner} (active float)"
                )
                return replace(g, float_ids=(floats[0], partner))
            trace.append("comparison partner unresolved — nothing active to compare against")
            return g

        if not floats and not regions:
            # No side explicit ("Now compare oxygen", "compare them"): inherit
            # the ongoing comparison's participants.
            if focus.comparison_members and focus.comparison_kind:
                kind = focus.comparison_kind
                trace.append(
                    f"inherited ongoing comparison ({kind} {','.join(focus.comparison_members)})"
                )
                if kind == "floats":
                    return replace(g, float_ids=tuple(focus.comparison_members))
                return replace(
                    g, comparison_regions=tuple(focus.comparison_members)
                )
            trace.append("no active comparison in memory — nothing to anchor the reference")
            return g

        # One region side or a mixed shape memory cannot complete
        # deterministically.
        trace.append("could not complete the comparison reference deterministically")
        return g
