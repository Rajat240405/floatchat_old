# Phase 3 — Semantic Reasoning & Planning

**FloatChat 2.0 principle:** *The LLM understands. Deterministic software executes.*

Phase 3 inserts a deterministic **Semantic Reasoner** between the
understanding layer and the execution pipeline. The LLM still does exactly
one thing — produce a `SemanticUnderstanding` (grounded concepts). The
reasoner now answers a question no keyword chain ever could: **what is the
scientist actually trying to do?**

```
Scientist
   │
   ▼
Conversation Context ──▶ Ontology ──▶ LLM Semantic Understanding  (1 LLM call)
                                          │
                                          ▼
                                SemanticUnderstanding            (unchanged, Phase 2)
                                          │
                                          ▼
                            Grounding — vocabulary/ontology only (unchanged, Phase 2)
                                          │  GroundedUtterance (facts)
                                          ▼
                        ┌──────────────────────────────────┐
                        │   SEMANTIC REASONER  (Phase 3)   │
                        │  single authority for execution- │
                        │  intent selection                │
                        └──────────────────────────────────┘
                                          │  ReasoningDecision (intent + rule + resolutions)
                                          ▼
                            Assembly → ParsedIntent              (unchanged contract)
                                          │
                                          ▼
                            Planner → Execution Engine           (UNCHANGED)
```

---

## 1. Architecture Summary

### What the reasoner is

`floatchat/understanding/reasoner.py` defines three small frozen dataclasses
and one stateless class:

| Type | Role |
|---|---|
| `GroundedUtterance` | The **facts** of one request after grounding: canonical variables, all ontology regions (mention order), comparison regions, float ids, coordinates + radius, place/season/depth/profile facts, and the *intent hint* with semantic signals (`existence_check`, `follow_up_reference`, `comparison.is_comparison`). No raw text. |
| `SemanticReasoner.reason()` | Interprets a `GroundedUtterance` into a `ReasoningDecision` via an ordered rule table (R0–R9). Deterministic, pure, no I/O. |
| `ReasoningDecision` | The selected execution intent **plus** `rule` (which rule fired) and `resolutions` (human-readable trace of every conflict/default it resolved). |
| `ReasonedClarification` | Structured "ask, don't guess" the reasoner emits when no ranking can separate competing objectives. |

### Hard guarantees (enforced and tested)

The reasoner **never**: calls an LLM, generates SQL, touches DuckDB, runs a
planner/executor, or inspects implementation details. It sees only grounded
facts. `reason()` rejects anything that is not a `GroundedUtterance` with a
hard `TypeError` — it cannot be fed a raw `SemanticUnderstanding`, let alone
the scientist's words. (`tests/test_understanding/test_reasoner.py::
TestReasonerPurity` verifies both the AST-level import purity — no
`llm_service` / `query_engine` / `data_lake` / `duckdb` imports — and the
input-type guard.)

Every value it emits is either a grounded fact or an established,
engine-compatible default (the same defaults the legacy parser used — e.g.
radius_search's 500 km fallback, ts_diagram's TEMP+PSAL form default,
comparison's full core+BGC variable set). Nothing is invented.

### Why this improves understanding (not just routing)

Phase 2 proved the LLM can reliably extract *concepts*. But concept extraction
is not objective interpretation. The pre-Phase-3 converter still contained the
last vestiges of imperative routing (comparison upgrades, sorted float lists,
default fills) — and the legacy fallback still routes by keyword priority:

* **Keyword chains can't rank specificity.** The legacy parser's `\bfloats?\b`
  discovery pattern matches the word "float" in *"Show salinity near Goa for
  float 1902190 profile 284"* and wins over the variable chain — so a
  float-284 salinity-profile request is executed as a Goa-area **radius
  search** (verified live on the legacy parser, see §4). The reasoner ranks by
  scientific specificity: a concrete float (+ profile + variable) is the most
  specific objective; place-derived coordinates lose and are dropped, with the
  decision recorded in `resolutions`.
* **Hints are advisory, not binding.** If the LLM mislabels "Show oxygen near
  Goa" as `radius_search`, the reasoner sees *variables at a location* — a
  measurement objective — and reinterprets to `profile_plot` with a logged
  resolution. Objective beats hint; concepts beat keywords.
* **Ambiguity is ranked deterministically, clarified only when unrankable.**
  "Compare oxygen" grounds only one side — no rule can choose between
  float-vs-region, so the reasoner asks (candidates included) instead of
  guessing. Every conflict that *can* be ranked (discovery-vs-measurement,
  metadata-vs-data, specificity) is resolved and traced — never silently.

---

## 2. Reasoning Flow

### Per-request flow (production path)

```
resolve(message, context)                        SemanticUnderstandingService
  └─ understand()  (1 LLM call, json_mode)  → SemanticUnderstanding
  └─ SemanticConverter.convert(understanding):
       1) requires_clarification gate            (unchanged)
       2) confidence gate (< 0.4 → ask)          (unchanged)
       3) ground intent name + variables +
          regions + comparison regions + float ids  (ontology only)
       4) spatial grounding (gazetteer, offline-first)
          4b) region-unresolved-without-scope → clarification
       5) GroundedUtterance ──▶ SemanticReasoner.reason()
                              ──▶ ReasoningDecision
               • decision.clarification   → ConversionOutcome(clarification)
               • place-unresolved discovery → ConversionOutcome(clarification)
       6) assemble ParsedIntent from decision fields (existing validators)
```

The `IntentResolver`, fallback behavior, clarifications plumbing
(`SemanticClarificationNeeded` → `ChatResponse(intent="clarification")`), and
everything below `ParsedIntent` are untouched.

### Rule table (ordered; first match wins)

| # | Rule | Condition (on grounded facts) | Decision |
|---|---|---|---|
| R0 | `comparison_organization` | comparison signal + 2+ floats/regions | `comparison_plot`; organizes axes; default vars = full core+BGC set (skipped for conversational follow-ups); floats sorted (legacy parity, deterministic ordering) |
| R0′ | `comparison_incomplete` | comparison signal, <2 sides grounded | **clarify** (two floats? two regions?) |
| R1 | `metadata_objective` | hint = metadata_lookup | `metadata_lookup` |
| R2 | `named_scientific_form` | hint = ts_diagram / time_series / hovmoller | pass through; default vars TEMP+PSAL (ts) or TEMP (time forms) when unnamed |
| R3 | `trajectory_objective` | hint = trajectory | `trajectory` |
| R4 | `count_objective` | hint = count_aggregate | `count_aggregate` |
| R5 | `discovery_vs_measurement` | discovery hint **+ variables** | **measurement** (`profile_plot`); "oxygen near Goa" is a measurement at a location, not float discovery |
| R5′ | `discovery_objective` | discovery hint, no variables | keep discovery intent; radius_search default 500 km only when no radius grounded |
| R6 | `metadata_vs_data` | no usable hint + float, no vars, no profile | **metadata** ("tell me about float X" is about the float, not its data) |
| R7 | `entity_inference` | no usable hint | float+vars → `profile_plot`; vars+scope → `region_search`; vars only → `profile_plot`; nothing rankable → `unknown` |
| — | `unresolved_hint` | nothing rankable and no entities | `unknown` → legacy fallback semantics |
| R9 | `hint_passthrough` | otherwise | trust the grounded hint |

**Specificity precedence** (applied inside every decision by the
`_DecisionBuilder`): when a concrete `float_id` is present on a non-discovery
intent, place-derived coordinates/radius are dropped and the drop is traced —
*"float 1902190 scope outranks place-derived coordinates (15.3, 73.9)"*.
Named ontology regions are kept alongside floats (engine-supported parity
with the legacy parser).

### Explainability

Every decision carries `rule` + `resolutions`, surfaced in two places
(verified in §5):

* `SEMANTIC_REASONING rule=… intent=… resolutions=…` — INFO when a
  resolution fired, DEBUG for plain passthroughs (`converter.py::_log_reasoning`, L189).
* The per-request `SEMANTIC_UNDERSTANDING` line now ends with `rule=…`
  (`service.py::_log_outcome`, L266), so one log line joins
  understanding → reasoning → latency.

`ConversionOutcome` gained additive fields `reasoning_rule: str | None` and
`reasoning_resolutions: list[str]` (both default empty — fully backward
compatible).

---

## 3. Modified Files

| File | Change | Why |
|---|---|---|
| `src/floatchat/understanding/reasoner.py` | **NEW** (452 lines) | The deterministic Semantic Reasoner: `GroundedUtterance`, `ReasoningDecision`, `ReasonedClarification`, `SemanticReasoner` (rule table R0–R9), `_DecisionBuilder` (shared organizational rules: specificity precedence, default radius, clarification). Imports only `logging`, `dataclasses`, and the ontology's `LEVELS_VARIABLE_ORDER` constant (vocabulary, read-only). |
| `src/floatchat/understanding/converter.py` | Rewired `convert()`; +`reasoner` ctor param (default `SemanticReasoner()`); +`_log_reasoning()`; grounding helpers reshaped to *fact collection* (`_ground_all_regions`, `_ground_comparison_regions`, `_ground_float_ids`); `_essential_clarification` split into gates 4b/5b; `ConversionOutcome` + `reasoning_rule`, `reasoning_resolutions` | The converter stops being a router: grounding now produces **facts**, step 5 hands them to the reasoner, step 6 assembles whatever the reasoner decided. The old inline routing (comparison upgrade, sorted comparison floats, default fills) **moved** into the reasoner — single authority. Clarification gates that are groundedness checks (unknown region name, unlocatable place) stay in the converter; objective selection does not. |
| `src/floatchat/understanding/service.py` | `_log_outcome` gains `rule=` (from `outcome.reasoning_rule`) | Instrumentation joins the reasoner trace to the per-request understanding line. |
| `src/floatchat/understanding/__init__.py` | Export `SemanticReasoner`, `GroundedUtterance`, `ReasoningDecision`, `ReasonedClarification`; docstring updated | Public API surface for the package. |
| `tests/test_understanding/test_reasoner.py` | **NEW** — 35 tests in 7 classes (`TestDiscoveryVsMeasurement`, `TestMetadataVsData`, `TestSpecificityPrecedence`, `TestComparisonOrganization`, `TestAmbiguityResolution`, `TestReasonerPurity`, `TestSingleAuthorityTrace`) | Locks every rule, the determinism/purity guarantees (frozen input, AST import purity, TypeError guard), and the instrumentation trace. |

**Explicitly NOT modified** (Phase 3 constraints): `SemanticUnderstanding`
(models.py), the ontology, the Planner, QueryEngine, Executors, DuckDB,
Visualization, Scientific Narration, API contracts, the regex parser, the
resolver's fallback wiring, settings. `git diff --stat` confirms the only
working-tree changes this phase are the 3 understanding modules + 2 new files.

---

## 4. Manual Testing — the reasoner chooses the execution intent

Battery: `/home/user/m4_baseline/phase3_manual_battery.py`; evidence log:
`/home/user/m4_baseline/phase3_battery_evidence.txt`. Driven through the
**real** pipeline (`SemanticUnderstandingService.resolve` → tolerant
understanding model → ontology grounding → production gazetteer → reasoner →
assembly). Only the LLM *transport* is stubbed (CannedLLM double returns
realistic `SemanticUnderstanding` JSON); every stage under test is production
code. **Result: 11/11 OK.**

### The 6 required queries

| Query | Legacy regex parser (verified live) | Semantic + Reasoner (Phase 3) | Rule |
|---|---|---|---|
| `Show oxygen near Goa` | `profile_plot` DOXY, coords, r=∅ | `profile_plot` DOXY, lat 15.3 lon 73.9, r=100 (gazetteer) | `hint_passthrough` |
| `Show floats near Goa` | `radius_search` r=500 (default) | `radius_search`, coords, r=100 (gazetteer) | `discovery_objective` |
| `Tell me about float 5906969` | `metadata_lookup` | `metadata_lookup`, float 5906969 | `metadata_vs_data` (hint was `unknown`; the **reasoner** inferred metadata from float-with-no-vars) |
| `Plot oxygen for float 5906969` | `profile_plot` | `profile_plot` DOXY, float 5906969 | `hint_passthrough` |
| `Show salinity near Goa for float 1902190 profile 284` | **`radius_search` ← keyword-chain bug** (`\bfloats?\b` matches "float 1902190") | **`profile_plot`** PSAL, float 1902190, profile 284, Goa coords **dropped** | `discovery_vs_measurement` + *specificity precedence* |
| `Compare oxygen between Arabian Sea and Bay of Bengal.` | `comparison_plot` | `comparison_plot` DOXY, regions [arabian_sea, bay_of_bengal] | `comparison_organization` |

### Supporting probes (also green)

| Probe | Result | Demonstrates |
|---|---|---|
| "Show oxygen near Goa" with LLM mis-hint `radius_search` | `profile_plot` DOXY + resolution *"variables ['DOXY'] present: reinterpreting 'radius_search' as a measurement objective"* | Hints are advisory; the reasoner's reading of grounded concepts is binding |
| `Compare float 5906969 with float 1902190` | `comparison_plot`, all 8 core+BGC vars, floats sorted [1902190, 5906969] | Standalone-comparison default + deterministic ordering (legacy parity) |
| `Compare oxygen` | **clarification** (field=comparison, candidates two floats/two regions) | Unrankable ambiguity → ask, never guess |
| `T-S diagram for float 2902403` | `ts_diagram` TEMP+PSAL + default trace | Named scientific form default |
| `Plot salinity during summer near Goa` | `profile_plot` PSAL, month_window [3,4,5], coords | Multi-concept (season × place × variable) |

Each row's `SEMANTIC_REASONING` and `SEMANTIC_UNDERSTANDING … rule=…` log
lines were captured live and are in the evidence file.

### Known nuance (pre-existing since Phase 2, flagged for your decision)

`Show floats near Goa`: semantic path yields **radius 100 km** (the converter
honours the gazetteer's place radius — Phase 2 behavior) vs legacy regex's
**500 km** fallback default. The reasoner only injects the 500 km established
default when *no radius was grounded at all*. This semantic↔legacy divergence
predates Phase 3; I kept Phase 2 behavior. Say the word if you'd rather the
reasoner override gazetteer radii for bare radius_search requests.

---

## 5. Verification (all executed this phase)

| Check | Command | Result |
|---|---|---|
| Understanding suite | `python3 -m pytest tests/test_understanding/ -q -p no:cacheprovider` (at `floatchat/`) | **180 passed** (145 pre-existing + 35 new reasoner tests — zero regressions) |
| Full suite, repo root | `cd /home/user/floatchat-2 && python3 -m pytest -q -p no:cacheprovider` | **944 passed** (909 + 35) |
| Full suite, package root | `cd /home/user/floatchat-2/floatchat && python3 -m pytest tests/ -q -p no:cacheprovider` | **944 passed** |
| Execution engine unchanged | `engine_smoke.py capture engine_smokes_phase3_post.json`, leaf-diff vs `engine_smokes_phase1_pre.json` | **12,262 leaves both sides, 0 diffs** |
| API contract unchanged | `app.openapi()` (fixture lake pinned, phase2+semantic off) vs `openapi_m5_pre.json` | **identical** (8 paths, 11 schemas) |
| Phase 2.1 bench still green | `semantic_bench.py` (32-query battery, real instrumentation) | **27/32 semantic success, 5/32 injected-failure fallbacks, all expectations met** |

(The two initial failures during this phase were in my two new purity tests —
one brittle substring check and one missing TypeError guard, both fixed and
re-run to green; reported here for completeness.)

---

## 6. Git state

All Phase 3 files staged alongside the previously staged Phase 2/2.1 set
(`git status` in final report). **Not committed** — awaiting your approval.

## What Phase 3 deliberately did not do

* No LLM anywhere post-understanding; the reasoner is pure deterministic code.
* No changes to the understanding contract, ontology, or any execution-stage file.
* The legacy regex parser and its fallback wiring are untouched — both paths
  remain available behind `FLOATCHAT_SEMANTIC_UNDERSTANDING_ENABLED`.
* Routing *names* the decision (`rule`), never hides it: every reinterpretation,
  default, or precedence call is in `resolutions` and the logs.
