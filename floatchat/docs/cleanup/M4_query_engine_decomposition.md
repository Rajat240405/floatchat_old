# Milestone 4 — QueryEngine Decomposition Report

**Commit:** `3faeb75` (`Cleanup M4: decompose QueryEngine into orchestrator + executors`)
**Scope:** `query_engine/` only. API routes/services, Planner, IntentResolver,
ParsedIntent, narration behavior, and frontend untouched (0 changed lines outside
`query_engine/`, 3 test files migrated in-place, 1 new test file, 1 README tree comment).

---

## 1. Executive Summary

`query_engine/engine.py` (**1,976 → 175 lines, −91.1%**) is now a thin orchestration
shell. It retains exactly the four responsibilities the milestone brief assigned to it:

| Kept in `engine.py` | Role |
|---|---|
| `QueryEngine.__init__` | Dependency injection (metadata / repository / reader / viz / explanation / data_lake) — **verbatim** |
| `QueryEngine.execute(intent)` | Public contract: deployment gate + `_DATA_INTENTS` validation + fallback for non-data intents — **verbatim** |
| `QueryEngine._execute_via_data_lake_or_explain` | Orchestration: resolve the cached lake once, bundle collaborators, dispatch — rewritten thin |
| `QueryEngine._get_data_lake` | Lazy data-lake lifecycle (phase-2 → phase-1 fallback construction) — **verbatim** |

Everything else moved, **verbatim except an explicit substitution table**, into
single-responsibility modules:

```
query_engine/
├── __init__.py            (unchanged — still exports only QueryEngine)
├── engine.py            175 lines   orchestration: validation, dispatch, lake lifecycle
├── dispatch.py           81 lines   _DATA_INTENTS vocabulary, ExecutionDeps, route table
├── helpers.py           245 lines   shared internal utilities
├── response_builder.py  214 lines   all ChatResponse payload construction
└── executors/
    ├── __init__.py       14 lines   documents the uniform executor protocol
    ├── spatial.py       261 lines   nearest_float + radius_search
    ├── metadata.py      363 lines   metadata_lookup + count_aggregate
    ├── trajectory.py    224 lines   trajectory queries
    ├── profile.py       355 lines   lake data queries (profile plots, region search,
    │                                time series, hovmoller, T/S, comparisons) incl.
    │                                visualization + scientific explanation wiring
    └── legacy.py        305 lines   gated GDAC fallback pipeline (+ its 3 support fns)
```

The execution pipeline is unchanged end-to-end:

```
ParsedIntent ─▶ QueryEngine.execute(intent)          [engine.py: gate + vocabulary]
             ─▶ _execute_via_data_lake_or_explain    [engine.py: lake resolve + ExecutionDeps]
             ─▶ dispatch.route(intent.intent)        [dispatch.py: route table]
             ─▶ execute_*(deps, intent, t0)          [executors/*: execution]
             ─▶ ChatResponse                         [payload pieces: response_builder.py]
```

No caller required modification: `api/dependencies.py`, `chat_service`,
`floats_service`, and both route modules call only `engine.execute(intent)` and the
unchanged constructor.

---

## 2. Files Modified

### Modules created (10)

| File | Lines | Contents |
|---|---|---|
| `query_engine/dispatch.py` | 81 | `_DATA_INTENTS` (verbatim), `ExecutionDeps` frozen dataclass, `_EXECUTOR_ROUTES`, `route()` defaulting to the data-query executor |
| `query_engine/helpers.py` | 245 | `_figure_metrics`, `_PROFILER_MFR_MAP`, `_resolve_manufacturer`, `_FLOAT_ID_RE`, `_build_alive_window`, `_extract_float_id_from_path`, `_extract_float_cycle_key`, `_filter_floats_by_variable`, **new** `_extract_cycle_from_filename` |
| `query_engine/response_builder.py` | 214 | `_build_map_data_from_lake`, `_build_lake_summary`, `_build_map_data`, `_build_message`, `_build_summary`, `_get_error_suggestion`, `_generate_suggestions`, `_calculate_derived_insights` |
| `query_engine/executors/__init__.py` | 14 | package docstring: uniform `execute_<kind>(deps, intent, pipeline_t0) -> ChatResponse` protocol |
| `query_engine/executors/spatial.py` | 261 | `execute_nearest_float`, `execute_radius_search` |
| `query_engine/executors/metadata.py` | 363 | `execute_metadata_lookup`, `execute_count_aggregate` |
| `query_engine/executors/trajectory.py` | 224 | `execute_trajectory` |
| `query_engine/executors/profile.py` | 355 | `execute_data_query_via_lake` |
| `query_engine/executors/legacy.py` | 305 | `execute_via_legacy_gdac` + `_intent_to_criteria`, `_search_metadata_groups`, `_pair_by_float_cycle` |
| `tests/test_query_engine/test_dispatch.py` | 40 | **+4 new tests** locking dispatch vocabulary, route table, default route, deps fields |

### Engine changes

- Removed from the class (all moved to modules; mapping in §3): `_execute_nearest_float`,
  `_execute_radius_search`, `_execute_metadata_lookup`, `_execute_count_aggregate`,
  `_execute_trajectory`, `_execute_data_query_via_lake`, `_execute_via_legacy_gdac`,
  `_intent_to_criteria`, `_search_metadata_groups`, `_pair_by_float_cycle`,
  `_build_map_data_from_lake`, `_build_lake_summary`, `_build_map_data`, `_build_message`,
  `_build_summary`, `_get_error_suggestion`, `_generate_suggestions`,
  `_calculate_derived_insights`.
- Nothing added to the class. `__init__`, `execute`, `_get_data_lake` are byte-verbatim;
  `_execute_via_data_lake_or_explain` shrank from a 5-branch if-chain to deps-bundle +
  `dispatch.route()` (routing semantics identical — see §4).
- Module docstring updated to document the layer structure; the `Priority 1A` behavioral
  notes are preserved.

### Helpers extracted

See `helpers.py` / `response_builder.py` rows above. One genuine deduplication
(authorized by task 3, "consolidate only where output remains identical"):

- **Cycle-from-filename regex** (`re.search(r"_(\d{1,4})[D]?\.nc$", …)` + `int(group(1))`)
  appeared byte-identically in `_execute_trajectory` and in `_build_map_data` →
  extracted to `helpers._extract_cycle_from_filename`. Idempotent regeneration + the
  unit suite + 16-case smoke diff all confirm output equality.

### Files removed

None. (The 1,976-line monolith was decomposed **in place**; no file deletions.)

### Test migrations (behavior-preserving, 3 files)

| File | Change |
|---|---|
| `tests/test_query_engine/test_engine.py` | `test_execute_builds_summary_once…` now wraps `response_builder._build_lake_summary` via `patch.object` (the executor resolves it as a module attribute at call time, preserving the patch seam). Same assertion: summary built exactly once. |
| `tests/test_query_engine/test_p3_depth_alive.py` | import moved: `…query_engine.helpers import _build_alive_window` (name unchanged; 5 call sites untouched). |
| `tests/test_intent_parser/test_phase5.py` | 7 in-test imports moved: `…query_engine.helpers import _resolve_manufacturer` (name unchanged; all 11 assertions untouched). |

### Other

- `floatchat/README.md`: one tree comment line (`query_engine/` now lists its components).

---

## 3. Responsibilities Extracted

The decomposition maps the engine's real responsibilities, not a speculative template
(sketch → actual mapping is noted where the brief's suggestion differed):

| Module | Responsibility | Why this cohesion |
|---|---|---|
| `dispatch.py` | The routing *vocabulary* (`_DATA_INTENTS`), the collaborator bundle (`ExecutionDeps`), and the intent→executor table | The monolith's dispatch logic was a bare frozenset + an if-chain; making them a first-class module turns routing into data with a tested contract, and `ExecutionDeps` is the single seam through which every executor receives the same injected collaborators. |
| `executors/spatial.py` | `nearest_float`, `radius_search` | Both are point/radius geographic lookups over the lake returning marker lists; they share helpers (`_resolve_manufacturer`, `_build_alive_window`, `_filter_floats_by_variable`). |
| `executors/metadata.py` | `metadata_lookup`, `count_aggregate` | Both answer registry/catalog questions (not measurement payloads): one returns float catalog facts (with the gated GDAC supplement), the other returns profile/float counts. *Covers the brief's suggested "registry" module — the registry-responsibility in this codebase is metadata lookup/aggregation.* |
| `executors/trajectory.py` | `trajectory` | Single owner of coordinate-history assembly incl. the DuckDB schema-sniffing fallback, gated GDAC fallback, haversine totals, per-cycle markers, and tolerant narration append. |
| `executors/profile.py` | All remaining data intents (`region_search`, `profile_plot`, `time_series`, `hovmoller`, `ts_diagram`, `comparison`, `comparison_plot`) | These intents share one pipeline: criteria build (incl. point+radius→bbox), lake query (incl. comparison union), zero-result explanation, dataframe post-processing, map markers, figure render + per-variable drawer figures, verification/trace, explanation, final message. *Covers the brief's "plotting" module: plotting is the injected `visualization_engine`; what remained in the engine was figure orchestration, which lives here with its query.* |
| `executors/legacy.py` | `_execute_via_legacy_gdac` **plus** `_intent_to_criteria`, `_search_metadata_groups`, `_pair_by_float_cycle` | Those three helpers are used **only** by the legacy GDAC pipeline; grouping them with their sole caller removes legacy surface from the mainline modules. Behavior and Planner usage unchanged (see §4). |
| `helpers.py` | Cross-executor pure utilities (alive window, manufacturer map, path/cycle extraction, figure metrics, variable filter) | Verbatim extraction of the monolith's module-level functions — they were already free of class state. |
| `response_builder.py` | All `ChatResponse` payload construction (map markers ×2 shapes, summaries ×2 shapes, message, suggestions, error suggestion, deprecated insights stub) | Task-3 audit found response construction scattered across 8 statics/methods; it now has one home. |

**Duplication audit (task 3) — full inventory and dispositions:**

| Pattern | Disposition |
|---|---|
| Cycle-from-filename regex (trajectory + record map builder) | **Consolidated** → `helpers._extract_cycle_from_filename` (output-identical; verified). |
| Nearest vs radius `MapData` marker loops | Audited, **not merged**: the loops interleave with different surrounding semantics (distance summaries vs alive-window messaging/variable filtering); a merge would couple two executors for cosmetic gain. |
| Records-based vs lake-df map builders (`_build_map_data` vs `_build_map_data_from_lake`) | Audited, **not merged**: different record shapes (GDAC metadata records vs lake DataFrame rows) and different status derivation; now co-located in `response_builder` so any future convergence has one home. |
| `_figure_metrics` (engine) vs `visualization_engine/profile.py::_figure_metrics` | Audited, **different functions** (figure-list metrics vs single-payload metrics) in different layers; no change. |
| Alive-window / float-variable-filter / manufacturer map | Already single-homed in the monolith; now in `helpers.py`. |

**Lake access review (task 4):**

- All executor lake access now flows through **one resolution per request**: the engine
  resolves `self._get_data_lake()` once and hands the instance via `ExecutionDeps.lake`.
  Previously the lake was resolved in the dispatcher *and* re-resolved (from the same
  cache) inside each executor. Because `_get_data_lake()` is idempotent (cached after
  first construction), collapsing these is not observable — same instance, same guards.
- Lazy fallback construction (`_get_data_lake`: phase-2 → phase-1 with the same settings
  keys and logs) is **preserved verbatim** — fallback semantics unchanged.
- `_build_map_data_from_lake` now receives the lake as an explicit parameter instead of
  reading the raw `self._data_lake` field; at the single call site the two are the same
  object (post-resolution), so the registry-status lookup is unchanged, including the
  `if lake else pd.DataFrame()` guard.
- Injection path unchanged: `api/dependencies.py` still constructs the engine with
  `data_lake=get_data_lake()`; no new construction sites were introduced anywhere.

---

## 4. Behavior Preservation

**Mechanism.** All moved code was produced by a deterministic generator
(`build_modules.py`, kept out of the repo) that extracted exact AST segments from the
pre-change engine and applied only an explicit, assertion-checked substitution table
(each substitution must match ≥1 occurrence, and a post-substitution scan rejects any
residual `self`). Re-running the generator against the shipped tree reproduces it
byte-for-byte (**idempotency check executed**), which proves the shipped code contains
*exactly* the monolith's code plus these and only these rewrites:

| Substitution | Count of sites | Substitute |
|---|---|---|
| `lake = self._get_data_lake()` | 6 (one per executor) | `lake = deps.lake` (same instance via cache) |
| `self.metadata` / `self.repository` / `self.reader` / `self.viz` / `self.planner` | 12 | `deps.<same field name>` |
| `self.explanation_engine` | 12 | `deps.explanation_engine` (narration wiring untouched) |
| `self._build_*(`, `self._get_error_suggestion(`, `self._generate_suggestions(` | 8 | `response_builder.<same name>(` (module-attribute lookup preserves the test patch seam) |
| `self._execute_via_legacy_gdac(intent, t0)` | 1 | `execute_via_legacy_gdac(deps, intent, t0)` |
| `self._intent_to_criteria(`, `self._search_metadata_groups(`, `self._pair_by_float_cycle(` | 3 | module-level functions in `legacy.py` (groups takes `deps` as first arg) |
| `self._data_lake` in map builder | 1 line | explicit `lake` parameter |
| method→function `def` lines; `@staticmethod`/`@classmethod` decorators dropped | 20 | name methodology: freed executors get public names (`execute_*`); internal helpers/builders/legacy-support keep their verbatim names |
| cycle-regex idiom | 2 | shared `_extract_cycle_from_filename` (task 3 dedup) |

**Contract checks (measured, not asserted):**

| Contract | Check | Result |
|---|---|---|
| `QueryEngine.execute()` signature | `inspect.signature` dump pre vs post | **Identical**, incl. annotations `(intent: ParsedIntent) -> ChatResponse` |
| Constructor signature | same | **Identical** (`metadata_service, repository_service, netcdf_reader, visualization_engine, explanation_engine=None, data_lake=None`) |
| Package surface | `query_engine.__all__` | **Identical** (`["QueryEngine"]`); `__init__.py` not modified |
| Class surface | attribute inventory pre vs post | 18 private methods moved to modules; **nothing added**; `execute` public contract intact; `_data_lake` attribute (written directly by tests + DI) preserved |
| Execution semantics | 16 deterministic end-to-end smokes (below) | **Byte-identical** payloads |
| Response payloads | same smokes, full `ChatResponse.model_dump()` | **Byte-identical** (only `data_summary.pipeline_trace` timings redacted — volatile wall-clock output, redacted identically pre/post) |
| Routing semantics | route-table vs monolith if-chain, plus 4 new contract tests | 5 named intents → dedicated executors; the other 7 data intents → data-query executor; non-data intents → unchanged warning response |
| Planner integration | `RetrievalPlanner()` still constructed in `__init__`; `deps.planner.plan(...)` used only in `legacy.py`; `retrieval_planner/` has 0 diff lines | **Unchanged** |
| API behavior | `/openapi.json` captured pre vs post (fixture lake pinned) | **Byte-identical** (8 paths); no API file modified |
| Scientific narration | narration code moved with executors (`deps.explanation_engine`, tolerant-trajectory block, verification/trace imports co-located); `scientific_explanation/` has 0 diff lines | **Unchanged** |

**What the 16 engine smokes cover (pre vs post, real fixture lake, production wiring
via `initialize_runtime_services()`):** `profile_plot` latest + explicit cycle +
variable-missing zero path, `region_search`, `time_series`, `hovmoller`,
`comparison` (two floats), zero-result explanation (year with no data), `trajectory`,
`nearest_float`, `radius_search` (+ alive-window + variable filter), `count_aggregate`
(region and spatial), `metadata_lookup`, and the non-data-intent fallthrough.

---

## 5. Validation

| Check | Result |
|---|---|
| Full suite, repository root (`python3 -m pytest -q`) | **645 passed** in ~22s |
| Full suite, package root (`floatchat/`) | **645 passed** in ~22s |
| Test accounting | pre-M4: 641 passed, 0 failed, 0 skipped (both cwd, reproducible). Verbose test-id diff: **exactly +4 new dispatch contract tests; zero removals; zero status flips**; root-vs-package test-id sets identical |
| Coverage | Not decreased: all 641 pre-existing tests still run against the moved code (3 migrated in place, assertions unchanged); +4 added |
| Startup verification | `uvicorn floatchat.api.main:app` boots; `/health` responds (`degraded` without a configured lake — expected since M1); FastAPI TestClient boot also exercised by the API suite |
| Execution smoke tests | 16/16 **byte-identical** post-change (see §4) |
| Legacy GDAC fallback | Gating tests pass unchanged (`test_metadata_lookup_falls_back_to_gdac_when_allowed`, `test_metadata_lookup_no_gdac_fallback_by_default`); the full legacy pipeline remains reachable only behind both settings flags, code moved verbatim |
| Move audit | Generator re-run reproduces shipped modules byte-for-byte (idempotent ⇒ no manual drift from monolith segments + declared substitutions) |
| Import layering | `executors/`, `helpers.py`, `response_builder.py`, `dispatch.py` contain no `self` remnants and no imports of `query_engine.engine` (DAG: helpers → response_builder → executors → dispatch → engine) |
| Performance | Micro-benchmark `engine.execute(profile_plot)` against the real fixture lake, n=30 after 3 warmups, A/B via `git worktree` on identical machine: **pre 83.21 ms mean / 80.15 ms median → post 78.24 ms mean / 76.30 ms median** — no regression (deltas are within run-to-run noise; the decomposition adds one frozen-dataclass construction + one dict lookup per request, ≈µs). Suite wall time: 3 pre-runs 24.9/24.8/22.1s vs 4 post-runs 21.7/21.9/23.0/21.9s — no regression. |

**QueryEngine.execute() signature — pre/post dump (identical):**

```
(self, intent: 'ParsedIntent') -> 'ChatResponse'
```

---

## 6. Remaining Work (Milestone 5)

Strictly the contract-tightening tail; all of it was deliberately excluded from M4's
freeze rules:

1. **Planner finalization** — `RetrievalPlanner` is now called from exactly two places:
   `executors/legacy.py` (gated-off-by-default GDAC path) and
   `metadata_service/gdac.py`. Decide the Planner's end-state (keep as-is while the
   legacy path exists; slim or retire together with the legacy path if/when the remote
   fallback is formally removed). No design work was done on it here, per the freeze.
2. **ParsedIntent tightening** — the intent vocabulary now lives in two places that must
   agree by convention: the `Literal[...]` on `ParsedIntent.intent` and
   `dispatch._DATA_INTENTS`. Candidates: derive/pin the data-intent set from a single
   source; prune genuinely impossible intents from the Literal; resolve the
   `profile_number` vs `cycle_number` duality; document which fields each executor
   actually consumes.
3. **Remaining contract cleanup** —
   - Publicize the underscore-prefixed helper/builder names moved verbatim this
     milestone (`helpers._*`, `response_builder._*`) or explicitly bless them as
     internal-by-convention (they were kept verbatim to make M4 byte-provable).
   - Type the API-layer chat signature properly (`intent_resolver: object` →
     `IntentResolver` — carried over from the M3 report; API layer was frozen in M4).
   - Restore the `_check_critical_fields` unit coverage lost with the M2 test
     deletions (noted in the M3 report).
   - Decide whether `QueryEngine._get_data_lake`'s lazy-construction fallback remains
     engine-owned once the composition root is the only production constructor.

---

## Appendix — environment note

All M4 analysis, baselines, and validation were performed fresh against current
`main` (`1573f78`) on-disk sources during this milestone. The pre-change engine was
the 1,976-line monolith described in §1; two earlier-session environment ambiguities
(a stale import resolution and a one-off suite count) were investigated and resolved
by re-baselining from git-verified content before any code was touched.
