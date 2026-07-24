# FloatChat Architecture

**Status:** Finalized and frozen by cleanup Milestone 5 (M1–M5 reports in
[`floatchat/docs/cleanup/`](floatchat/docs/cleanup)). This document describes the
codebase **exactly as it exists today**. Historical audits and investigations
under `floatchat/docs/{architecture,investigations,scientific}/` predate the
cleanup and are retained for reference only — they are marked as historical
and do not describe the current system.

---

## 1. System overview

FloatChat converts natural-language Argo ocean-data questions into validated,
visualized answers. All data queries execute against a local DuckDB/Parquet
data lake; live GDAC downloads exist only as an explicitly gated legacy
fallback.

```
Client (Next.js frontend)
    ↓ HTTP/JSON
FastAPI Routes                 floatchat/api/routes/{chat,floats,health}.py
    ↓ thin HTTP layer (schemas in floatchat/api/schemas.py)
API Services                   floatchat/api/services/{chat,floats,health}_service.py
    ↓ classification → parsing → intent resolution
Planner                        floatchat/retrieval_planner/
    ↓
QueryEngine.execute(intent)    floatchat/query_engine/engine.py
    ↓ dispatch.route(intent)   floatchat/query_engine/dispatch.py
Executors                      floatchat/query_engine/executors/*.py
    ↓
DuckDB / Legacy GDAC           floatchat/data_lake/  (primary)
                               floatchat/metadata_service + repository_service
                               + netcdf_reader        (gated legacy fallback)
    ↓
Scientific Narration           floatchat/scientific_explanation/
```

This pipeline is **frozen**. Changes must not move responsibilities between
layers; new features plug into the documented contracts below.

---

## 2. Layers and contracts

| Layer | Modules | Contract |
|---|---|---|
| **Routes** | `api/routes/chat.py`, `api/routes/floats.py`, `api/routes/health.py`, `api/main.py` | Thin FastAPI routers. No business logic; parse HTTP, delegate to services, serialize. Request/response models live in `api/schemas.py`. |
| **API services** | `api/services/chat_service.py`, `floats_service.py`, `health_service.py` | Orchestration only. `handle_chat(request, classifier, llm_service, intent_parser, intent_resolver, query_engine, conversation_manager, knowledge_base)` is the chat entry point. Float services build deterministic (no-LLM) responses and invoke the engine only through `QueryEngine.execute`. |
| **Dependency wiring** | `api/dependencies.py` | Composition root: lazily builds and caches every service singleton; `initialize_runtime_services()` runs at startup; tests override via `app.dependency_overrides`. |
| **Intent pipeline** | `llm_service/classifier.py`, `intent_parser/*`, `intent_resolution/resolver.py` | Classify → parse → resolve into a `ParsedIntent`. Owned by the chat pipeline; not part of the engine contract. |
| **Planner** | `retrieval_planner/operation_planner.py`, `retrieval_planner/planner.py` | See §3. No planner code executes inside `QueryEngine.execute` on the lake path. |
| **QueryEngine** | `query_engine/engine.py` | **Public interface:** constructor DI — `QueryEngine(metadata_service, repository_service, netcdf_reader, visualization_engine, explanation_engine=None, data_lake=None)` — and `execute(intent: ParsedIntent) -> ChatResponse`. Responsibilities: deployment gate, data-intent validation (`_DATA_INTENTS`), routing via `dispatch.route`, lazy lake lifecycle (`_get_data_lake`, phase-2 → phase-1 fallback). Everything else lives in modules below. |
| **Dispatch** | `query_engine/dispatch.py` | `_DATA_INTENTS` — the data-intent vocabulary, **derived** from the `ParsedIntent.intent` Literal minus `_NON_DATA_INTENTS` (single-sourced, M5). `ExecutionDeps` — frozen dataclass bundling the typed collaborators every executor receives. Route table + default route. |
| **Executors** | `executors/spatial.py` (nearest_float, radius_search), `executors/metadata.py` (metadata_lookup, count_aggregate), `executors/trajectory.py`, `executors/profile.py` (region_search, profile_plot, time_series, hovmoller, ts_diagram, comparison/_plot), `executors/legacy.py` (gated GDAC pipeline) | Uniform protocol: `execute_<kind>(deps: ExecutionDeps, intent: ParsedIntent, pipeline_t0: float) -> ChatResponse`. Executors never construct services and never read globals beyond `settings`. |
| **Helpers / response building** | `query_engine/helpers.py`, `query_engine/response_builder.py` | Engine-internal utilities (alive-window, manufacturer map, path/cycle extraction, variable filter, figure metrics) and all `ChatResponse` payload construction. Internal — see §5. |
| **Data access (primary)** | `data_lake/duckdb_lake.py` | `DuckDBDataLake` over Parquet (phase-1 tree or phase-2 ETL layout). All executors receive the already-resolved instance; SQL is out of cleanup scope and unchanged. |
| **Data access (legacy)** | `metadata_service/`, `repository_service/`, `netcdf_reader/` | Live GDAC HTTP pipeline. Reachable only when **both** `FLOATCHAT_ALLOW_REMOTE_GDAC_FALLBACK=True` and `FLOATCHAT_ENABLE_GDAC_RUNTIME=True` (defaults: False). Retained for the offline phase-2 builder; `executors/legacy.py` owns it inside the engine. |
| **Scientific narration** | `scientific_explanation/engine.py` | Injected into the engine; produces deterministic, verification-guarded explanations and degrades gracefully without an LLM. Behavior frozen. |

---

## 3. Planner finalization

Two planners exist, with disjoint responsibilities; both are **final**.

| Planner | Used by | Status |
|---|---|---|
| `OperationPlanner` (`plan_from_intent`) | `api/services/chat_service.py` (mixed-operation chat flow) | **Active.** Final architecture: chat-level operation planning stays in the API service layer, upstream of the engine. |
| `RetrievalPlanner` (`plan(variables) -> RetrievalPlan`) | `executors/legacy.py` (via `ExecutionDeps.planner`) and `metadata_service/gdac.py` | **Retained by design.** Its only consumers are the gated legacy GDAC path and the GDAC metadata service, both of which exist to support the offline phase-2 lake builder and the explicit remote-fallback escape hatch. It is intentionally small (core/bio index routing) and will be retired only if the legacy GDAC path is ever removed. No vestigial planner surface remains. |

`QueryEngine.__init__` still constructs `RetrievalPlanner()` (part of the frozen
constructor contract); it is forwarded untouched through `ExecutionDeps`.

---

## 4. ParsedIntent contract

`floatchat/models/intent.py::ParsedIntent` is the single typed object crossing
the NL → backend boundary. The intent vocabulary is the `Literal` below —
partitioned at runtime into data vs non-data intents by `query_engine.dispatch`:

- **Data intents (12):** `profile_plot`, `region_search`, `time_series`,
  `comparison`, `comparison_plot`, `trajectory`, `hovmoller`, `ts_diagram`,
  `nearest_float`, `radius_search`, `metadata_lookup`, `count_aggregate`.
- **Non-data intents (5):** `general_chat`, `unknown`, `small_talk`,
  `out_of_domain`, `knowledge_base`.

Field-level contract (25 fields; all consumers audited in M5):

| Field | Type | Consumed by |
|---|---|---|
| `intent` | Literal (above) | engine gate, dispatch, executors |
| `region` | `str \| None` | executors, lake criteria |
| `variables` | `list[str]` (normalized uppercase by validator) | lake criteria, filters, messages |
| `comparison_float_ids` | `list[str]` | comparison paths (profile executor, legacy groups) |
| `comparison_regions` | `list[str]` | operation planner plan payload |
| `year`, `month`, `day` | `int \| None` | lake criteria / legacy criteria |
| `month_window` | `list[int] \| None` | season filtering (lake criteria, alive window) |
| `lat`, `lon`, `radius_km` | `float \| None` | spatial executors, bbox derivation |
| `lat_min/lat_max/lon_min/lon_max` | `float \| None` | explicit bbox queries |
| `existence_check` | `bool` | count_aggregate messaging, operation planner |
| `depth_min`, `depth_max` | `float \| None` | lake criteria |
| `float_id` | `str \| None` | scoped queries |
| `profile_number` | `int \| None` (≥1) | **the** cycle selector |
| `operational_filter` | `str \| None` (`"alive"`) | radius alive-window, operation planner |
| `temporal_date_start/end` | `str \| None` | alive-window priority 1 |
| `limit` | `int` (1–20) | query caps |

**Removed in M5:** `cycle_number` — a stale alias of `profile_number` that was
accepted but never read. Parser payloads that still include the key remain
valid (pydantic ignores unknown keys); see `tests/test_models_intent_contract.py`.

---

## 5. Visibility convention (public vs internal)

Applied consistently since M4, formalized in M5:

1. **Public API** — `floatchat.query_engine.QueryEngine` (constructor +
   `execute`), service entry points (`handle_chat`, `build_*_response`),
   models. Callers may rely on these.
2. **Package-internal** — `query_engine.dispatch`, `query_engine.executors.*`,
   `ExecutionDeps`. Stable within the package; the uniform executor protocol is
   documented, but applications should not import executors directly.
3. **Module-internal** — underscore-prefixed names (`helpers._*`,
   `response_builder._*`, `dispatch._DATA_INTENTS`/`_NON_DATA_INTENTS`,
   `QueryEngine._get_data_lake`). Private implementation that tests may pin but
   application code must not use. Names were deliberately kept verbatim through
   the M4 decomposition to keep every move byte-provable; they are blessed
   as the internal-by-convention style of this codebase.

---

## 6. Configuration and runtime flags

Defined in `floatchat/config.py` (`FLOATCHAT_*` env vars / `.env`):

| Flag | Default | Effect |
|---|---|---|
| `DATA_LAKE_ROOT` | repo-relative default | phase-1 Parquet lake |
| `DATA_LAKE_DIR` / `DATA_LAKE_PHASE2_ENABLED` | unset / False | phase-2 ETL lake root |
| `ALLOW_REMOTE_GDAC_FALLBACK` | False | unlocks legacy GDAC executor paths |
| `ENABLE_GDAC_RUNTIME` | False | master switch for GDAC HTTP at runtime |
| `DEPLOYMENT_MODE` | open | `INDIA_ONLY` gates non-Indian regions in `execute()` |
| `SCI_NARRATOR_ENABLED` | True | master switch for LLM narration (deterministic paths force it off) |
| `DATA_LAKE_MAX_PROFILES` | — | lake query cap (profile-aware requests use 1) |
| `ALIVE_RECENT_MONTHS` | — | "currently alive" window |

The app boots without any lake configured and reports `degraded` on `/health`
— this is expected, not an error.

---

## 7. Testing strategy

- Suite is **hermetic and cwd-independent**: `floatchat/tests/conftest.py`
  pins settings to the committed fixture lake
  (`floatchat/tests/fixtures/lake_parquet`) before anything builds the runtime
  graph; identical results from repo root (`pytest.ini`,
  `pythonpath=floatchat/src`) and `floatchat/` (`pyproject.toml`,
  `pythonpath=["src"]`).
- No network: Ollama/GDAC absence is exercised as graceful degradation; GDAC
  fallback tests use mocks.
- Contract tests: `test_query_engine/test_dispatch.py` (routing + vocabulary),
  `test_models_intent_contract.py` (ParsedIntent), plus service/engine unit
  tests per layer.

---

## 8. Documentation map

| Doc | Role |
|---|---|
| `ARCHITECTURE.md` (this file) | **Authoritative** architecture contract. |
| `floatchat/README.md`, `frontend/README.md` | Setup/run guides + source tree. |
| `floatchat/docs/cleanup/M1–M5` | Cleanup milestone reports (what/why/evidence). |
| `floatchat/docs/architecture/*`, `docs/investigations/*`, `docs/scientific/*` | Historical audits/investigations (banner-marked; superseded where they describe architecture). |
