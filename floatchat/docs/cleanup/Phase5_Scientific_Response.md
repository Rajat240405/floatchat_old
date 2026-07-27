# Phase 5 — Scientific Response & User Experience

**FloatChat 2.0 principle:** *The LLM understands. Deterministic software executes.*
Phase 5's corollary: *facts come from the engine; prose only describes them.*

Phases 1–4 built the understanding and reasoning architecture. Phase 5 adds
a deterministic **Scientific Response Layer** that converts execution results
into clear, explainable scientific communication — strictly **after**
execution, with zero changes to anything before or inside it.

```
… Planner → Execution Engine → Execution Result (ChatResponse — FROZEN)
                                   │
                                   ▼
            ┌──────────────────────────────────────────────┐
            │        SCIENTIFIC RESPONSE LAYER (Phase 5)    │
            │  ├─ Scientific Narration (natural opening)    │
            │  ├─ Scientific Summary (facts only)           │
            │  ├─ Context Explanation (only if inherited)   │
            │  ├─ Assumption Explanation (only if used)     │
            │  ├─ Follow-up Suggestions (deterministic)     │
            │  └─ Reasoning Explanation (optional, off)     │
            └──────────────────────────────────────────────┘
                                   │
                                   ▼
                          Chat Response (same schema)
```

---

## 1. Architecture Summary

### What the layer is

A new package, `floatchat/scientific_response/`, with one orchestrator and
three single-responsibility modules:

| Module | Responsibility |
|---|---|
| `narration.py` | One natural scientific opening line per intent class, templated from ontology display labels (variables → "temperature", "dissolved oxygen"; regions → "Arabian Sea") and result counts. Plus one static, honest clause about the visualization form — no data claims. |
| `summary.py` | **Facts only.** Three kinds, in order: (1) the engine's own interpretation carried forward verbatim (the frozen executors' deterministic explanation tail); (2) statements **computed from the returned payload** — profile ranges/extremes and, for temperature, surface-vs-deep means with the strongest-gradient depth (documented 0.02 °C/dbar threshold); comparison surface means per named group; time-series quarter-mean trends with a noise threshold; trajectory displacement/compass bearing from map markers (haversine + 8-wind compass); (3) coverage counts straight from `data_summary`. Thin data ⇒ the statement is **omitted**, never invented. |
| `suggestions.py` | 3–5 follow-up questions derived from the intent's grounded entities + ontology variable vocabulary. Questions, never claims. |
| `layer.py` | Gating + composition: builds `ComposedSections`, renders the message, preserves the payload. |

### Why it belongs after execution

The layer's inputs exist only *after* execution: result statistics, map
markers, figure traces, counts. Placing it upstream would force the
understanding architecture to know presentation concerns; placing it inside
the executors would entangle proven query/viz code with UX. The seam — one
line in `handle_chat` *after* `query_engine.execute(intent)` — is provably
the only modification point: the engine smoke, which captures `execute()`
output directly, stays frozen; the suite's engine-level message tests
(deployment gates, comparison naming, zero-result probes) are untouched
because they never pass through the seam.

### Facts vs generated prose (the mandated separation)

* **Facts** — every number, date, count, position, direction, default, and
  reasoning/context line — originate in the execution engine's payload or in
  upstream *metadata* (Phase-3 reasoning trace, Phase-4 context trace).
* **Narrative** — templates that merely describe those facts. No sentence
  asserts a scientific observation that is not either engine-produced or
  deterministically computed from the returned data (`test_response_layer.py::
  test_thin_data_produces_no_invented_observations` locks this).
* The original engine message is preserved verbatim under
  `data_summary["engine_message"]`; the composed sections are also exposed
  structurally under `data_summary["scientific_response"]` (additive keys;
  schema unchanged — OpenAPI verified identical).

### Behavior boundaries (all test-locked)

* **Never**: calls an LLM, executes SQL, queries DuckDB, modifies execution
  results, modifies plots, alters planner behavior (AST import-purity test).
* **Pass-through cases**: disabled flag (`scientific_response_enabled=false`),
  non-data intents, and zero-content responses (matched_records=0, no figure,
  no map markers — e.g. availability probes, deployment gates): byte-identical.
* **Configuration**: `FLOATCHAT_SCIENTIFIC_RESPONSE_ENABLED` (default on) and
  `FLOATCHAT_SCIENTIFIC_REASONING_EXPLANATION_ENABLED` (default off; optional
  "Request interpretation" transparency section).

---

## 2. Response Flow

```
Execution Result (ChatResponse; figure / map_data / data_summary frozen)
      │
      ▼
gate: enabled? data intent? content present?   ── no ──▶ pass through
      │ yes
      ▼
Scientific Narration         intent + ontology labels + counts
      +
Scientific Summary           engine interpretation → computed facts → coverage
      +
Context Used                 ONLY from Conversation Intelligence trace
      +
Assumptions Used             ONLY actually-applied defaults (intent + trace)
      +
Request interpretation       ONLY when reasoning flag enabled
      +
Suggested follow-ups         deterministic templates from intent/variables
      │
      ▼
Chat Response — message recomposed; figure/map_data/keys byte-identical;
engine_message preserved
```

Example (real battery, fixture lake):

```
Showing the temperature profile for **Float 2902270** (the available cycle).
The visualization shows how the measurements change with depth and highlights
the vertical structure of the water column.

**Scientific summary**
- Surface Temperature (°C): 28.3°C
- Thermocline: 60 dbar

**Context used**                       ← only when inherited
- Continuing within the Arabian Sea.

**Assumptions used**
- Latest available profile selected (no cycle specified).
- No depth range specified — the full water column is shown.
- No time range specified — all available dates are included.

**Suggested follow-ups**
- Compare this profile with an earlier cycle of Float 2902270.
- Plot salinity alongside temperature for Float 2902270.
- Show the trajectory of Float 2902270.
- Explain the thermocline in more detail.
```

Sections appear only when they contain useful information (structure-order
and omission tests).

---

## 3. Modified Files

| File | Change | Why |
|---|---|---|
| `src/floatchat/scientific_response/{__init__,layer,narration,summary,suggestions}.py` | **NEW** (the entire layer) | Only new architectural component. Imports: stdlib, config, models, ontology vocabulary. Nothing below the boundary. |
| `src/floatchat/api/services/chat_service.py` | kw-only `response_layer` param; compose at the single post-execute line (imports `ScientificResponseLayer`) | The one seam after execution. Mixed-plan, available-plots, clarification and error paths deliberately untouched. |
| `src/floatchat/api/routes/chat.py` | inject `get_scientific_response_layer` and forward | DI wiring only; OpenAPI unchanged. |
| `src/floatchat/api/dependencies.py` | `get_scientific_response_layer()` provider (always built; flag checked at compose time) | Flag flips need no DI rebuild. |
| `src/floatchat/config.py` | +2 additive settings (`scientific_response_enabled` default on; `scientific_reasoning_explanation_enabled` default off) | Layer + transparency section toggles. |
| `src/floatchat/intent_resolution/resolver.py` | **6-line additive, read-only** thread-local `last_semantic_outcome` (set where the outcome already exists; plus a property) | The response layer needs the Phase-3/4 traces for Context Used / Request interpretation **without touching the semantic pipeline**. Thread-local ⇒ no cross-request bleed; never feeds parsing, routing, or merging. Pipeline behavior unchanged (suite + smokes prove). |
| `tests/test_scientific_response/{__init__,test_response_layer}.py` | **NEW** — 25 tests: narration, computed-summary correctness, context/assumption honesty, structure & omission, flags, pass-through byte-identity, purity, handle_chat wiring | Locks every responsibility and the facts-vs-prose boundary. |

**Explicitly NOT modified**: Conversation Intelligence, Semantic Understanding,
Semantic Reasoner, Planner, Query Engine, Executors, DuckDB, Visualization,
Scientific Narrator (the executor-internal explanation engine), API contracts.

---

## 4. Manual Testing — real pipeline over the fixture lake

Script: `/home/user/m4_baseline/phase5_response_battery.py`; evidence:
`phase5_battery_evidence.txt`. Real DI runtime (fixture lake pins identical to
the engine smoke), real executors/viz; only the LLM transport is stubbed and
the classifier is patched to DATA_QUERY so every message reaches the
canonical path. **Multi-turn context explanation verified: True.**

| Scenario | Result |
|---|---|
| Float metadata | Narration + fact bullets (status, DAC, network, profile count) from `float_info`; follow-ups grounded in the float id |
| Profile plot ("Show temperature for float 2902270.") | Scientific opening; engine facts (Surface 28.3 °C, Thermocline 60 dbar); honest assumptions incl. latest-cycle; 4 relevant follow-ups |
| Regional search ("Show salinity in the Arabian Sea.") | Narration with real counts (44 profiles, 29 floats); engine interpretation bullets (halocline 103 dbar) |
| Comparison ("Compare oxygen between Arabian Sea and Bay of Bengal.") | Exact requested narration; summary carries engine facts only — the fixture degrades to one float's data, so no two-side stats are invented (honest boundary) |
| Trajectory ("Show the trajectory of float 5906969.") | Computed real direction — "net displacement ≈ 68 km, predominantly **westward**; total path ≈ 68 km" + coverage line |
| Time-series ("Show temperature over time in the Arabian Sea.") | Data-bearing path composed; salinity-for-5906969-style zero-results pass through untouched (availability-probe messages preserved) |
| Multi-turn (salinity-in-AS → "Now show temperature.") | Turn 2 shows **Context used: Continuing within the Arabian Sea.** — inherited-region explanation enabled by the Phase-4 trace |

Presentation swaps confirmed: the log-style line "Showing TEMP profile for
Float 2902270, Cycle 187…" becomes the scientific paragraph above; the
original remains under `engine_message`.

---

## 5. Verification (all executed this phase)

| Check | Method | Result |
|---|---|---|
| Full suite, repo root | `python3 -m pytest -q -p no:cacheprovider` | **1000 passed** (975 + 25 new) |
| Full suite, package root | `cd floatchat && python3 -m pytest tests/ -q -p no:cacheprovider` | **1000 passed** |
| Planner behavior / query outputs / plots | engine smoke `engine_smokes_phase5_post.json` vs `engine_smokes_phase1_pre.json` | 12,262 leaves; all identical **except** a pre-existing nondeterministic tie-order flip (below) |
| API contract | `app.openapi()` vs `openapi_m5_pre.json` | **identical** |
| Benches | `semantic_bench.py`: 27/32, all expectations; Phase-3 battery 11/11; Phase-4 battery green | ✅ |
| Byte-identity of payloads | `test_execution_payload_passes_byte_identical` (figure/map/keys/engine_message) + disabled-flag identity test | ✅ |

### Reported finding: pre-existing engine nondeterminism (NOT from Phase 5)

Two consecutive captures of the **same code** differ in
`region_search.figure.data[0].x.bdata`: decoding the 589-element trace shows
elements 85/86 swapped (22.368 vs 22.3703 °C) — two measurements with an
identical sort key whose order flips run-to-run inside the executor's data
path. Phase 4's capture matched the baseline by chance. Phase 5 changes zero
engine-path code, and the flip is observable with identical code across runs;
it predates this phase. Data *content* is unchanged (same multiset).
Candidate future fix (needs your approval — engine is frozen): a
deterministic secondary sort key (e.g. `ORDER BY pres, float_id`) in that
lake query. I did not change it.

During development, two issues were found and fixed (reported honestly):
a position-bullet ordering bug in metadata summaries and a missing space in
the trajectory sentence; plus one mis-computed *test expectation* (surface
mean 27.4, not 28.0) corrected in the test. Full suites re-run after each.

---

## 6. Git state

All Phase 5 files staged on top of the Phase 1–4 set (`git status` in the
final report). **Not committed.**

## What Phase 5 deliberately did not do

* No LLM anywhere in the layer (deterministic templates + arithmetic only).
* No changes to understanding, reasoning, planning, execution, storage,
  visualization, or schemas.
* The optional reasoning explanation ships **off** by default — presentations
  stay lean; transparency is opt-in for demos/debugging.
* Zero-result and error responses are deliberately NOT re-styled — their
  engine-built availability explanations are already the right UX.
