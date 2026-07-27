# Phase 4 — Conversation Intelligence & Context Reasoning

**FloatChat 2.0 principle:** *The LLM understands. Deterministic software executes.*

Phases 1–3 taught FloatChat to understand **requests**. Phase 4 teaches it to
understand **conversations**: a deterministic **Conversation Intelligence**
layer maintains the active scientific focus across turns and resolves
follow-up references into explicit grounded facts **before** the Semantic
Reasoner runs.

```
Scientist
   │
   ▼
Conversation Memory            ← bounded per-session ConversationFocus
   │
   ▼
Conversation Intelligence      ← NEW (Phase 4) — deterministic; no LLM,
   │                               no SQL, no DuckDB, no planner/executor
   ▼
Ontology → LLM Semantic Understanding → SemanticUnderstanding → Grounding
   │
   ▼
GroundedUtterance
   │
   ▼
┌───────────────────────────────────────────┐
│ CONVERSATION INTELLIGENCE (complete)      │  references → grounded facts:
│ • What is "it"? / "those floats"?         │  "Now salinity." + memory ⇒
│ • active float/profile/variable/region    │  float_ids=(5906969,),
│ • ongoing comparison participants         │  profile=142, variables=(PSAL,)
└───────────────────────────────────────────┘
   │
   ▼
Semantic Reasoner (UNCHANGED, Phase 3) → ParsedIntent → Planner → Engine
   │
   ▼
Conversation Intelligence (update)     ← focus refreshes deterministically
                                         after each successful request
```

---

## 1. Architecture Summary

### What the layer is

`floatchat/conversation/intelligence.py` — one stateless collaborator class
(`ConversationIntelligence`) holding bounded per-session **Conversation
Memory** (`ConversationFocus`), with four deterministic operations:

| Operation | When it runs | What it does |
|---|---|---|
| `handle_control(message, session_id)` | start of every chat turn (route level) | Detects conversation **control** commands ("Clear context.", "start over", …) — session management, *not* intent routing. |
| `complete(session_id, utterance, understanding)` | between grounding and the reasoner (converter step 5a) | Resolves conversational references into grounded facts. Only gaps are filled; explicit facts always win. |
| `update(session_id, decision, utterance)` | after each successful reasoning step | Advances turn count; updates/replaces/clears focus slots deterministically. |
| `focus` / `clear` | internal + control | Expiry-aware memory access; control-command erasure. |

### Why it belongs *before* semantic reasoning

The Phase 3 reasoner is the single authority for execution-intent selection,
and it is deliberately **frozen** in Phase 4. For it to decide correctly on a
follow-up, the *facts* must already be complete: "Compare with float 1902190."
is a one-sided comparison *until* memory supplies the partner — after CI
completion the reasoner sees a fully grounded two-float comparison and its
normal rules select `comparison_plot`. If references were resolved *after* the
reasoner (the Phase-≤3 approach: keyword-gated merging of `ParsedIntent`
fields), routing itself would be decided on incomplete information and patched
post-hoc — exactly the keyword-chain fragility Phase 3 removed from intent
selection. Reference resolution is **fact completion**, not intent selection,
so it runs on the `GroundedUtterance` — the last moment before reasoning.

### What it replaces on the semantic path (and what it does not touch)

Until Phase 4, semantic output flowed through the legacy keyword-gated tail
(`detect_reference_phrases` overrides, `_context_dependent` enrichment,
`merge_context`) *after* conversion. In
`intent_resolution/resolver.py` those blocks are now guarded with
`not from_semantic` — on the semantic path, CI is the single authority for
conversational context; on the legacy path everything is byte-identical
(proven by the frozen engine smoke, §5).

Not touched: Ontology, `SemanticUnderstanding` (contract), the Semantic
Reasoner (rules, files), Planner, Query Engine, DuckDB, Visualization,
Scientific Narration, API schemas/contracts.

### Determinism guarantees (test-enforced)

CI **never** calls an LLM, executes SQL, queries DuckDB, or inspects
planners/executors (AST-import purity test). It operates on the understanding's
structured signals, the grounded-utterance contract, stored focus state, and —
for control commands only — the raw message. Its *primary inheritance gate* is
the LLM's own structured `follow_up_reference` signal (Phase 2 contract), the
semantic analog of the legacy keyword reference-phrase gate — without keywords.

---

## 2. Context Flow

### Reference-resolution rules (`complete`) — applied only when `follow_up_reference` is true

| Rule | Condition on grounded facts | Result (traced) |
|---|---|---|
| Standalone gate | `follow_up_reference` false | utterance unchanged (`TestInheritanceGates`) |
| No memory | follow-up, no focus | unchanged + trace "no active context — nothing to inherit" |
| Expiry | `turn_count ≥ conversation_max_turns` (10) | focus dropped, trace "context expired after N turns" |
| Single-float objectives | no float, no scope in request, active float | inherit `float_id` |
| Profile subordination | active profile **of the same float** only | inherit `profile` |
| Variables | no variables, active variables | inherit `variables` |
| Region slot | no float focus applies, active region | inherit `region` (float slot outranks region slot) |
| Metadata follow-up | metadata shape (no vars + concepts/hint) | inherit float **only** (never variables/profile) |
| Comparison partner | one explicit float + active float | complete the pair (explicit-first order) |
| Ongoing comparison | no sides + active comparison slot | inherit all participants |
| Ambiguous referent | single-float objective, only a multi-float comparison in memory | **clarify** with candidates ("Plot the deepest one." → which float?) |
| Comparison memory can't anchor | stays one-sided | reasoner's `comparison_incomplete` asks (CI never duplicates its questions) |

### Focus-lifetime rules (`update`) — after each successful decision

| Slot | Created | Updated | Replaced | Expired / cleared |
|---|---|---|---|---|
| `float_id` | first float-bearing decision | — | new explicit float (→ profile slot cleared) | session expiry / control clear |
| `profile_number` | explicit profile on active float | new explicit profile | with float replacement | never inherited without its float |
| `variables` | first variable-bearing decision | any variable-bearing decision | newest variables win | — |
| `region` | first region-bearing decision | region-bearing decisions | newest region wins | — |
| `comparison` | comparison decision (≥2 sides) | refreshed on same members | new comparison only | control clear; *not* auto-cleared by other objectives ("remain active until replaced or cleared") |
| `turn_count` | first CI-processed request | +1 per processed request (incl. clarifications; slots unchanged on clarification) | — | at `max_turns` the focus expires |

Memory is bounded: per-session fields only, turn-based expiry, explicit clear
— no indefinite growth.

### Explainability

Every turn emits traceable lines (live-captured in the battery evidence):

```
CONVERSATION_CONTEXT session=… reason='follow-up request' inherited=inherited float_id=5906969 (active float),inherited profile=142 (…)
CONVERSATION_CONTEXT session=… reason='objective update'   updated=variable=PSAL
CONVERSATION_CONTEXT session=… reason='control command'    action=clear_context
```

The same trace rides on `ConversionOutcome.context_resolutions` (additive
field; empty when CI is inactive), next to Phase 3's `reasoning_rule` /
`reasoning_resolutions`.

---

## 3. Modified Files

| File | Change | Why |
|---|---|---|
| `src/floatchat/conversation/intelligence.py` | **NEW** (≈430 lines): `ConversationFocus`, `ContextResolution`, `ContextClarification`, `ControlResult`, `ConversationIntelligence` | The entire Phase-4 layer. Imports: `logging`, `re`, `dataclasses`, `datetime`, `settings` (turn bound), and the `GroundedUtterance` contract it completes. Nothing below the boundary. |
| `src/floatchat/conversation/__init__.py` | exports + docstring | Public API surface of the conversation package. |
| `src/floatchat/understanding/converter.py` | ctor param `conversation_intelligence`; `convert(…, session_id=…)`; step **5a** CI completion before `self._reasoner.reason`; CI clarification mapping; focus `update()` on success/clarification; `ConversionOutcome.context_resolutions` (additive) | The one seam where references become grounded facts *before* the reasoner. `session_id=None`/CI `None` ⇒ Phase-3 behavior bit-for-bit. |
| `src/floatchat/understanding/service.py` | ctor param `conversation_intelligence` (wired into the default converter); `resolve(…, session_id=…)` thread-through; session-less callers and pre-Phase-4 converter doubles keep the old call shape | Derives the CI session key for every semantic request. |
| `src/floatchat/intent_resolution/resolver.py` | passes `session_id` to `understanding.resolve`; legacy keyword-gated tail (metadata override, context enrichment, `merge_context`, unknown-intent reuse) guarded with `not from_semantic` | Makes CI the **single authority** for context on the semantic path; legacy path untouched. |
| `src/floatchat/api/services/chat_service.py` | `handle_chat(…, *, conversation_intelligence=None)`; Step 0: control-command short-circuit (clears CI focus **and** legacy context, answers with `intent="general_chat"` — schema unchanged) | "Clear context." must work regardless of how the message would have classified. |
| `src/floatchat/api/routes/chat.py` | one extra `Depends` injected and forwarded | DI wiring only; OpenAPI unchanged (verified §5). |
| `src/floatchat/api/dependencies.py` | `get_conversation_intelligence()` (built only when the semantic flag is on); `get_semantic_understanding()` wires it in | Flag-off ⇒ `None` ⇒ legacy behavior end-to-end. |
| `tests/test_understanding/test_resolver_integration.py` | **documented contract update**: two tests re-expressed for Phase 4 (metadata-vs-data decided by reasoner; legacy merge skipped on semantic path); module docstring updated | These Phase-2 tests encoded "keyword tail applies to semantic output" — the exact behavior Phase 4 supersedes. Change is explicit, minimal, and justified in the test. |
| `tests/test_conversation/test_intelligence.py` | **NEW** — 31 tests in 9 classes | Gates, inheritance, replacement, comparison anchoring, lifetime/expiry, control commands, purity (AST imports, frozen traces), resolver integration, chat-level clear, explicit-request parity, and the full required battery. |

---

## 4. Manual Testing — the required conversational scenario

Script: `/home/user/m4_baseline/phase4_conversation_battery.py`; evidence:
`phase4_battery_evidence.txt`. Driven through the real pipeline (LLM transport
stub only), with live `CONVERSATION_CONTEXT`/`SEMANTIC_REASONING` capture and a
focus snapshot after every turn. All assertions also locked in
`tests/test_conversation/test_intelligence.py::TestConversationalBattery`.

| Turn | Message | Outcome (variables/float/profile/comparison) | Context behavior |
|---|---|---|---|
| 1 | Tell me about float 5906969. | `metadata_lookup` f=5906969 | focus **created**: float=5906969 (`metadata_vs_data` decided by reasoner) |
| 2 | Plot oxygen. | `profile_plot` DOXY f=**5906969** | float **inherited** (traced); vars updated→DOXY |
| 3 | Now salinity. | `profile_plot` PSAL f=5906969 | float inherited; vars updated→PSAL |
| 4 | Show profile 142. | `profile_plot` PSAL f=5906969 **p=142** | float+vars inherited; explicit profile **updates** slot (`entity_inference` → profile_plot) |
| 5 | Compare with float 1902190. | `comparison_plot` PSAL pair **[1902190, 5906969]** | partner 5906969 **anchored from active float**; comparison slot created |
| 6 | Now chlorophyll. | `comparison_plot` CHLA same pair | **ongoing comparison participants inherited**; vars→CHLA |
| 7 | Show trajectories. | `trajectory` f=5906969 | single-float slot read (trajectory consumes one float — engine contract); comparison slot intact |
| 8 | Clear context. | `general_chat` ack + `action=clear_context` | **control command**: CI focus cleared (+ legacy context at route level); focus → empty |
| 9 | Plot oxygen. | `profile_plot` DOXY f=**None** | **no inheritance possible** after clear; trace "no active context"; a fresh conversation starts |

Supporting behaviors locked by tests: "Compare oxygen." with no comparison
context → `comparison_incomplete` **clarification** (ask, never guess);
"Plot the deepest one." with only a two-float comparison in memory →
ambiguous-referent clarification **with candidates**; metadata follow-ups
inherit the float only; region-scoped follow-ups never inherit the float;
expiry at 10 turns; fully explicit requests unchanged (below).

---

## 5. Verification (all executed this phase)

| Check | Command / method | Result |
|---|---|---|
| Full suite, repo root | `cd /home/user/floatchat-2 && python3 -m pytest -q -p no:cacheprovider` | **975 passed** (944 + 31 new) |
| Full suite, package root | `cd /home/user/floatchat-2/floatchat && python3 -m pytest tests/ -q -p no:cacheprovider` | **975 passed** |
| Execution engine unchanged | engine smoke vs `engine_smokes_phase1_pre.json` (`engine_smokes_phase4_post.json`) | **12,262 leaves both sides, 0 diffs** |
| API contract unchanged | `app.openapi()` vs `openapi_m5_pre.json` | **identical** (8 paths, 11 schemas) |
| Phase 2.1 bench | `semantic_bench.py` (32-query battery) | **27/32 success, 5/32 injected fallbacks, all expectations met** |
| Phase 3 battery regression check | `phase3_manual_battery.py` (no CI wired) | **11/11 OK** — Phase 3 single-shot outcomes unchanged |
| **Explicit-context ⇒ unchanged execution** | `TestExplicitRequestParity`: identical `ParsedIntent.model_dump()` with vs without CI on a fully explicit request; plus the frozen smoke/OpenAPI above | **identical** |

During development, two findings were fixed and re-run to green (reported for
honesty): an injected test converter needed the pre-Phase-4 call shape
preserved (service now only passes `session_id` when one exists), and CI's
first design duplicated the reasoner's `comparison_incomplete` question —
refactored so CI clarifies only memory-created ambiguity while incomplete
comparisons stay with the reasoner.

---

## 6. Git state

All Phase 4 files staged on top of the Phase 1–3 set (`git status` in the
final report). **Not committed.**

## Boundaries respected

* No LLM/SQL/DuckDB/planner/executor in the layer (AST-verified).
* Ontology, `SemanticUnderstanding`, Semantic Reasoner, Planner, Query Engine,
  DuckDB, Visualization, Scientific Narration, API contracts: untouched.
* Legacy regex path + its keyword context machinery: byte-identical
  (guarded, not edited); semantic path context is now owned by CI.
* Known honest boundary: references to *result sets* never explicitly
  identified in the conversation ("those floats" after an open discovery with
  no named floats) cannot be resolved without reading engine outputs — CI
  does not read engine responses; such references get a clarification, not
  a guess.
