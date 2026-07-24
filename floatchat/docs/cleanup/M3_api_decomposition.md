# Milestone 3 — API Layer Decomposition (Routes → Services) (Report)

Date: 2026-07-24 · Branch: `main` · Commit `84f74cb` on top of M2 (`a0a52a0`).

Scope constraints honored: QueryEngine, Planner, IntentResolver, Scientific
narration, VariableRegistry, DuckDB SQL behavior, frontend — all untouched.
No response JSON / status-code / path changes. Structural cleanup only.

---

## 1. Executive Summary

`api/routes.py` (1,589 lines) mixed seven HTTP endpoints with ~1,400 lines of
business logic: DuckDB SQL construction, registry metadata formatting, intent
clarification rules, knowledge-base RAG prompting, mixed-plan execution, and
response shaping. This milestone decomposed it to match the frozen
post-M2 architecture:

```
Client → FastAPI Routes (thin: params + DI + delegation)
      → Services (chat_service / floats_service / health_service)
      → Planner → QueryEngine → DuckDB        (unchanged layers)
```

After M3: **`api/routes/*.py` totals 215 lines (−86 %)**, every route body is
a single delegation call, and all business logic lives in
`api/services/*.py` (1,558 lines). HTTP request/response models moved
verbatim to `api/schemas.py`. `GET /health`, previously defined inline in
`api/main.py`, joined the route layer unmodified.

Verification standing: **641/641 tests pass from both working directories**,
the **OpenAPI schema is byte-identical** to a pre-split baseline, and a
**14-case endpoint smoke suite matches the baseline byte-for-byte**.

## 2. Files Modified

**Routes created** (`floatchat/src/floatchat/api/routes/`):

| File | Lines | Content |
|---|---|---|
| `__init__.py` | 35 | Aggregates the `/api/v1` router (`from floatchat.api.routes import router` keeps working); re-exports former module-level schema names for back-compat. |
| `chat.py` | 66 | `POST /chat` — signature, docstring and DI wiring verbatim; calls `chat_service.handle_chat(...)`. |
| `floats.py` | 97 | 6 × `GET /floats/*` — signatures, docstrings, and the 422 variable-validation contract verbatim; call `floats_service.build_*_response(...)`. |
| `health.py` | 17 | `GET /health` (moved from `api/main.py`); payload assembly in the service. |

**Services created** (`floatchat/src/floatchat/api/services/`):

| File | Lines | Content |
|---|---|---|
| `__init__.py` | 5 | Package docstring. |
| `chat_service.py` | 620 | `handle_chat` traffic-cop orchestrator + response helpers. |
| `floats_service.py` | 884 | All DuckDB/Parquet access & formatting behind `/floats/*`. |
| `health_service.py` | 54 | `runtime_lake_readiness` (moved verbatim from `main.py`) + `build_health_payload`. |

**Other files:**

| File | Change |
|---|---|
| `floatchat/src/floatchat/api/schemas.py` | **Created** (65 lines): `ChatRequest`, `FloatRegistryResponse`, `FloatMetadataAPIResponse`, `FloatTrajectoryAPIResponse`, `FloatProfileAPIResponse`, `AvailablePlotItem`, `FloatAvailablePlotsResponse` — moved verbatim. |
| `floatchat/src/floatchat/api/main.py` | Removed inline `_runtime_lake_readiness` and the local `@app.get("/health")`; now includes `health_router` (same prefix-less path). 208 → 176 lines. |
| `floatchat/README.md`, `floatchat/ARCHITECTURE.md` | Structure tree / accuracy banner updated for the new layout. |

**Files removed:** `floatchat/src/floatchat/api/routes.py` (the monolith;
git records the content migration as `routes.py → services/floats_service.py`
rename + new files).

**Files renamed:** none beyond the `routes.py` content migration noted above
(modules were created rather than renamed; the package directory
`api/routes/` assumes the old module path so existing import statements in
`api/main.py` and elsewhere keep working).

## 3. Logic Extracted

From the chat route region into `services/chat_service.py`:

- `handle_chat` — the entire traffic-cop flow (classify → scientific-followup
  override → conversational override → small-talk / out-of-domain hardcoded
  responses → knowledge dispatch → resolver → planner → mixed-plan execution
  → critical-field clarification → engine execution → graceful error
  response). Moved verbatim; the route only binds the HTTP signature.
- `_is_active_scientific_followup`, `_check_critical_fields`,
  `_build_full_context_prompt`, `_build_suggestion_message`,
  `_execute_mixed_plan`, `_handle_knowledge_query`, `_log_response` — moved
  verbatim.

From the floats region into `services/floats_service.py`:

- `build_float_registry_response` — registry aggregation (~285 lines:
  DuckDB path detection, column-name detection, `arg_max` position SQL,
  BGC/Core network derivation, status/sensor formatting, fallback payload).
- `build_float_metadata_response`, `build_float_trajectory_response`
  (cycle-history SQL, per-cycle level stats, haversine distance, map_data
  assembly), `build_latest_profile_response`,
  `build_available_plots_response`, `build_float_plot_response`.
- Helpers: `_get_lake`, `_normalize_float_id`,
  `_count_profiles_with_variable`, `_VAR_TITLES`, `_CORE_PLOT_VARS`.

From `main.py` into `services/health_service.py`: `_runtime_lake_readiness`
(renamed `runtime_lake_readiness` — it is no longer module-private) and the
health payload builder.

**Duplication consolidated (Task 3) — each proven output-identical:**

1. The `.0` float-id normalization was copy-pasted **inside** the metadata
   and trajectory handlers; both now call the existing `_normalize_float_id`
   (same logic, single copy). The trajectory variant's comment line was
   folded in.
2. `ChatResponse → FloatProfileAPIResponse` construction (message
   fallback + trailing-newline strip + map_data coercion) was duplicated in
   latest-profile and plot; now `_profile_api_response(...)` (the second
   function's extra `if msg.endswith("\n\n")` branch was provably dead after
   the while-loop and was dropped).
3. Dead local imports (`ProfileVisualizationEngine`, `GDACMetadataService`,
   `GDACRepositoryService`, `BGCNetCDFReader`) inside the two plot-endpoint
   bodies were removed; `ParsedIntent`/`settings` imports were retained
   because both functions genuinely use them.

**Deliberately NOT consolidated (behavior safety):** the 422 variable
validation stays in `routes/floats.py` (it *is* an HTTP concern); the plot
route passes the validated `var` into the service. The registry endpoint
intentionally still constructs its own `DuckDBDataLake` from settings rather
than the DI singleton — changing that selection logic is behavioral and is
deferred (see §6). `api/dependencies.py` is unchanged; services receive
collaborators as parameters (no new global mutable state).

## 4. Behavior Preservation

Evidence collected against a **pre-split baseline** captured at commit
`a0a52a0` (stored under `/tmp/m3_baseline` during the refactor):

- **OpenAPI schema:** `app.openapi()` serialized with sorted keys is
  **byte-identical** before vs. after (8 paths: `/health`, `/api/v1/chat`,
  6 × `/api/v1/floats/*`). Endpoint function names kept verbatim, so
  `operationId`s, docstring descriptions, tags, and component schema names
  are unchanged.
- **Endpoints:** identical paths + methods (aggregated `APIRouter` includes,
  same prefix; `/health` stays prefix-less via its own router include).
- **Response JSON / status codes:** a 14-case smoke suite diffed
  byte-for-byte — `health`; chat small-talk / out-of-domain / unknown /
  data / clarification; registry; metadata / trajectory / latest-profile /
  available-plots for a missing float; plot `TEMP` 200; plot `NOPE` 422;
  plot `PRES` 422. **ZERO diffs.**
- **API compatibility:** no field/type/default/doc changes in any schema;
  the deprecated back-compat import path `from floatchat.api.routes import
  router` (plus all response models) still works.
- **Boot:** `uvicorn floatchat.api.main:app` starts; `/health` → degraded
  (expected without a configured lake, unchanged semantics);
  `POST /api/v1/chat` → `profile_plot`; `/floats/registry` → 200;
  `/openapi.json` → 200.

## 5. Test Validation

| Check | Result |
|---|---|
| `pytest tests/ -q` from `floatchat/` | **641 passed** (24.6 s) |
| `pytest -q` from repository root | **641 passed** (23.9 s) |
| Test count delta | **0** — no test file changes were required: no test references route-layer internals (they pin behavior over HTTP via `create_app`); verified by grep over `tests/`. Coverage unchanged by construction. |
| Import validity | `from floatchat.api.routes import router, ChatRequest, FloatRegistryResponse`; `routes.chat/.floats/.health`; `services.chat_service/.floats_service/.health_service` — all OK |
| Startup verification | uvicorn boot + 4 live probes (health/chat/registry/openapi) — OK |
| Route smoke tests | 14-case diff vs baseline — all identical |
| OpenAPI diff | byte-identical |

## 6. Remaining Work (Milestone 4)

QueryEngine-decomposition scope only (everything else from the assessment
already closed or out of scope):

1. **Split `query_engine/engine.py`** into cohesive units — region/spatial
   resolution, alive-window computation, variable/profile selection,
   lake-vs-legacy selection, and plotting dispatch — without changing
   `QueryEngine.execute(intent)` semantics (the frozen interface that
   `chat_service.handle_chat` calls).
2. **Unify lake access behind the DI singleton** where safe: the registry
   endpoint currently constructs its own `DuckDBDataLake` from settings while
   the rest of the service layer uses `get_data_lake()`; reconciling this is
   a behavioral question (phase-1 fallback vs phase-2 registry) that belongs
   to M4's lake-interface review, not the API milestone.
3. **Type the resolver in the chat signature** (`intent_resolver: object` →
   `IntentResolver`) as part of tightening cross-layer contracts during the
   engine work.
4. **Optional test gap:** re-add focused unit tests for
   `_check_critical_fields` (now in `chat_service.py`) — its previous
   coverage was deleted with `test_phase_hardening.py` in M2.
5. Registry metadata **formatting deduplication candidate**: `map_data`
   dictionaries are shaped in three places (registry, metadata, trajectory)
   with near-identical keys; a shared builder is only safe after M4
   clarifies the lake-returned field inventory.
