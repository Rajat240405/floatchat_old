# Milestone 5 — Contract Tightening & Architecture Finalization Report

**Commit:** `1026180` (`Cleanup M5: contract tightening & architecture finalization`)
**Nature:** not a refactoring milestone. No modules were split, no code blocks moved,
no responsibilities relocated. Diff size: **+408 / −28 lines across 14 files**.

---

## 1. Executive Summary

M5 took the M4-decomposed architecture and made its contracts explicit, type-safe,
single-sourced, and documented — without touching execution behavior:

1. **Planner finalized** — both planners audited, responsibilities documented, no
   vestigial surface found to remove.
2. **ParsedIntent tightened** — the stale `cycle_number` alias removed (write-only
   field, zero consumers); the duplicated data-intent vocabulary eliminated by
   deriving `dispatch._DATA_INTENTS` from the `ParsedIntent.intent` Literal.
3. **Weak typing replaced** — `intent_resolver: IntentResolver` in the chat service
   signature, `ExecutionDeps` fields typed against abstract contracts,
   `QueryEngine._get_data_lake` return typed, `dependencies._knowledge_base` typed.
4. **Visibility convention formalized** — public / package-internal / module-internal
   tiers documented in `ARCHITECTURE.md` §5.
5. **Deferred tests restored** — `_check_critical_fields` (17 tests from the M2-deferred
   item), plus new contract tests for the vocabulary single-sourcing and the intent model.
6. **One authoritative architecture document** — new `/ARCHITECTURE.md`; all four
   pre-cleanup docs banner-marked as historical.

The architecture is internally consistent: every layer has a stated contract, every
contract has a test, and the documentation now describes the code exactly as it exists.

---

## 2. Files Modified

**Code (6):**

| File | Change | Type |
|---|---|---|
| `models/intent.py` | Removed write-only `cycle_number` field (+ comment explaining removal & parser-payload compatibility) | contract |
| `query_engine/dispatch.py` | `_DATA_INTENTS` derived from the `ParsedIntent.intent` Literal (identical set); added `_NON_DATA_INTENTS`; `ExecutionDeps` fields typed against `AbstractDataLake`, `AbstractMetadataService`, `AbstractRepositoryService`, `AbstractNetCDFReader`, `AbstractVisualizationEngine`, `ScientificExplanationEngine`, `RetrievalPlanner` (TYPE_CHECKING, zero runtime cost) | contract |
| `query_engine/engine.py` | `_get_data_lake()` return annotation `Any` → `AbstractDataLake \| None`; dropped now-unused `Any` import | typing |
| `api/services/chat_service.py` | `intent_resolver` parameter annotated `IntentResolver` (+ import; no import cycle — resolver has no API imports) | typing |
| `api/dependencies.py` | `_knowledge_base: "KnowledgeBase | None"` (was `object`) | typing |

**Tests (3):** `tests/test_api/test_chat_service_critical_fields.py` (**new**, 17),
`tests/test_models_intent_contract.py` (**new**, 4),
`tests/test_query_engine/test_dispatch.py` (+2 vocabulary single-sourcing tests).

**Documentation (6):** `/ARCHITECTURE.md` (**new**, authoritative), `floatchat/README.md`
(+architecture pointer), banner headers marking historical status in
`docs/architecture/{argo_data_model,phase1_audit}.md`,
`docs/investigations/temp_query_root_cause.md`, `docs/scientific/argo_scientific_audit.md`.

---

## 3. Contract Improvements

### Planner
Full caller audit. `OperationPlanner.plan_from_intent` is the **active** chat-level
operation planner (used by `chat_service`), and `RetrievalPlanner.plan` serves exactly
two consumers: `executors/legacy.py` (gated-off GDAC path) and `metadata_service/gdac.py`
(the service that also feeds the offline lake builder). Decision per the task:
**both remain, by design**, now documented in `ARCHITECTURE.md` §3 including the
retirement condition (RetrievalPlanner goes away only if the legacy GDAC path is ever
removed). Nothing vestigial found; no redesign performed; public interface untouched
(verified by signature dumps).

### ParsedIntent
Complete 26-field audit: every field's producer and consumers were traced by grep +
reading. **25 fields have live consumers** (including non-obvious ones like
`comparison_regions` → operation planner payload, `day` → legacy criteria). The only
dead contract was `cycle_number` — accepted (e.g. via `ParsedIntent.model_validate` of
LLM JSON) but **never read anywhere** (executors use `profile_number` exclusively;
zero test references). Removed. This is behavior-neutral: the key is now ignored by
pydantic's default extra policy, which is effectively what already happened downstream,
and a contract test (`test_parser_payload_mentioning_cycle_number_still_validates`)
locks that compatibility.

**Vocabulary de-duplication:** the data-intent set existed twice — once in the
`Literal` on `ParsedIntent.intent` (17 values) and once hand-maintained in
`dispatch._DATA_INTENTS` (12 values). `_DATA_INTENTS` is now derived
(`Literal − _NON_DATA_INTENTS`): provably the same `frozenset` (asserted before the
edit, locked by two new tests afterward). A future intent added to the Literal can no
longer silently desynchronize the engine gate.

### Typing
- `handle_chat(..., intent_resolver: IntentResolver, ...)`: the parameter was entirely
  un-annotated — the exact M4 follow-up item.
- `ExecutionDeps`: the M4 bundle moved from seven `Any` fields to the seven abstract
  service contracts — executors now nominally depend on interfaces.
- `QueryEngine._get_data_lake` return type now honest: `AbstractDataLake | None`
  (the failure path returns `None` and executors guard it).
- Remaining `object` annotations audited: all others are legitimate generic spots
  (`__exit__(*args: object)`, a `set.add(value: object)` helper, an opaque
  conversation-context dict in the classifier) — documented as intentionally left.

### Helper visibility
Decision: **internal-by-underscore is the blessed convention** (no renames). It keeps
the M4 moves byte-provable, matches where tests already pin internals, and avoids
churn in a non-refactoring milestone. The three-tier convention (public /
package-internal / module-internal) is written down in `ARCHITECTURE.md` §5 with
examples, so the underscore names are now meaningful rather than accidental.

---

## 4. Behavior Preservation

| Evidence | Result |
|---|---|
| Full test suite, repo root **and** package root | **668/668** (before: 645; = 645 untouched + 23 new) |
| 16 deterministic `engine.execute()` smokes (all executor paths, production wiring, real fixture lake) | **byte-identical** pre vs post |
| `/openapi.json` | **byte-identical** (8 paths) |
| `QueryEngine.__init__` / `execute` signatures (+ annotations) | **unchanged** (dump diff) |
| `RetrievalPlanner.__init__` / `plan` signatures, `RetrievalPlan` fields | **unchanged** (dump diff) |
| `dispatch._DATA_INTENTS` value | **unchanged** (same 12 names — derivation verified equal before edit) |
| `ParsedIntent.intent` Literal | **unchanged** (17 values) |
| Field inventory diff | exactly one removal: `cycle_number` (intended, write-only) |
| Startup | `uvicorn floatchat.api.main:app` boots; `/health` OK |
| No-go areas | 0 lines changed in executor logic, DuckDB SQL, narration, IntentResolver logic, frontend |

Mechanism notes: all typing changes are annotations only (zero-cost `TYPE_CHECKING`
imports; no runtime casts/asserts). The vocabulary derivation executes once at import
and yields the identical set. No logic lines were edited in any executor.

---

## 5. Validation

| Item | Result |
|---|---|
| Test count | **668 passed**, both `pytest` from repo root and from `floatchat/` (pre-M5: 645) |
| Restored coverage | `_check_critical_fields`: **17 tests** covering all four rule branches × context exemption (the exact M2-deferred item); +4 ParsedIntent contract tests; +2 vocabulary single-sourcing tests. Coverage increased, nothing removed |
| Startup verification | uvicorn boot + `/health` (`degraded` without a configured lake, as documented since M1) |
| OpenAPI | unchanged (byte-compared) |
| QueryEngine public interface | unchanged (signature + annotation dumps) |
| Planner public interface | unchanged (signature dumps) |
| ParsedIntent contract | documented field-by-field in `ARCHITECTURE.md` §4; locked by `test_models_intent_contract.py` |
| Documentation verification | `ARCHITECTURE.md` written from live code (every module path, flag, and field verified against the tree); all four historical docs carry "historical reference" banners pointing at it; README interlinks resolve |

---

## 6. Final Architecture Assessment

**Architecture maturity.** The system now has: a frozen five-layer pipeline with
documented contracts at every seam (routes → services → planner → engine contract →
executor protocol → data access); a single-sourced intent vocabulary with partition
tests; a fully audited, field-documented boundary model; type-safe collaborator
bundles; deterministic, cwd-independent tests (668) with a committed fixture lake; and
one authoritative architecture document synchronized with the implementation. The
cleanup roadmap (M1 hygiene → M2 legacy LLM removal → M3 API decomposition → M4 engine
decomposition → M5 contract tightening) is **complete**; no further architectural
restructuring is warranted or recommended.

**Remaining technical debt (minor, documented, none blocking):**
- The Ollama intent-parser's *prompt schema* still advertises a `cycle_number` key;
  it is ignored downstream exactly as before. Retuning LLM prompts was deliberately
  out of cleanup scope (real-world behavior risk); flag for the parser owners.
- The Ollama conversation `context` object crossing into the classifier remains an
  opaque dict; a typed `ConversationContext` model would be a good feature-time task.
- The legacy GDAC path (RetrievalPlanner, metadata/repository/reader services,
  `executors/legacy.py`) remains by design for the offline lake builder + explicit
  fallback; it can only be retired after the builder is decoupled from those services.
- Historical investigation docs are retained with banners rather than deleted —
  a deliberate provenance choice; delete them if the team prefers a leaner tree.
- Frontend tooling warning: `next build` on Node 20 prints an `EBADENGINE` notice
  (upstream wants Node ≥22) — build succeeds; upgrade Node at leisure.

**Production readiness.** Ready: deterministic startup with graceful degradation
(no lake → `degraded` health, no LLM → fallback explanations, no remote calls by
default), configuration fully env-driven and documented, failure modes tested.

**Recommendations for future feature development (outside cleanup scope):**
1. New query kinds: add the intent to the `ParsedIntent` Literal, an executor
   implementing `(deps, intent, t0) -> ChatResponse`, and a route-table entry — the
   vocabulary tests will enforce synchronization automatically.
2. Prefer lake-first features; extend `DuckDBDataLake` rather than adding service
   exceptions into executors.
3. Add CI running the suite from both roots plus an OpenAPI diff check to keep the
   frozen architecture frozen.
4. When the phase-2 builder is decoupled from GDAC services, revisit retiring the
   legacy path and `RetrievalPlanner` as a single, cohesive change.
