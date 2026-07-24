# Milestone 1 — Repository Hygiene & Test Integrity (Report)

Date: 2026-07-24 · Branch: `main` · Commits `e7c7370` (hygiene changes) and
`4608de9` (documentation corrections) on top of `66a00be`.

Scope constraints honored: **no architectural redesign, no feature changes, no
API changes, no frontend behavior changes, no QueryEngine / Planner /
IntentResolver logic changes.** Runtime behavior is unchanged; only repo health
and developer reliability were improved.

---

## 1. Executive Summary

Before this milestone the repository was not a reliable foundation:

- The test suite **passed only by accident** — it silently depended on the
  process working directory (`settings.data_lake_root` was a cwd-relative path)
  and, from the repository root, on a **hardcoded Windows path**
  (`E:\floatchat_data_lake\`) baked into `config.py`. Running the suite from
  the repo root produced 2 failures that did not reproduce from `floatchat/`.
- One test (`test_general_query_uses_context_hint`) failed even in the
  "working" directory because it asserted a routing branch that the current
  architecture no longer exercises.
- Config leaked one developer's machine layout into version control, and two
  imported packages were not declared as dependencies.
- Committed build artifacts, runtime caches, stub datasets, duplicate test
  files, and one-developer tool config were tracked in git.
- READMEs described an older generation of the system (real-time GDAC, React
  Leaflet, Next.js proxy rewrites) matched by nothing in the code.

After this milestone:

- **733 / 733 tests pass deterministically from both supported working
  directories** (repo root and `floatchat/`), with **zero network, zero env
  vars, zero machine-specific paths required**, on Linux and Windows alike.
- Configuration is portable by default and machine-specific values live
  outside version control (`FLOATCHAT_*` env / git-ignored `.env`).
- Every declared dependency is imported and every imported package is declared
  (backend and frontend).
- The tracked tree contains no runtime caches, build artifacts, or duplicate
  test files; the READMEs match the implementation.

## 2. Files Modified

### Test integrity

| File | Change |
|---|---|
| `floatchat/tests/conftest.py` | Pins the shared settings singleton to the **committed fixture lake** (`tests/fixtures/lake_parquet`), disables Phase 2 lookup, fails loudly if the fixture is missing; adds the reusable session-scoped `fixture_lake_root` fixture. |
| `floatchat/.data_lake/parquet/**` → `floatchat/tests/fixtures/lake_parquet/**` | Moved (12 parquet files, `git mv`) the small sample lake that tests already relied on, from a hidden cwd-dependent location into an explicit per-suite fixture. |
| `pytest.ini` (new, repo root) | Root-level pytest config (`testpaths`, `pythonpath = floatchat/src`, `asyncio_mode`, warnings filter) so `pytest` from the repo root behaves byte-identically to running inside `floatchat/`. |
| `floatchat/pyproject.toml` | Added `pythonpath = ["src"]` to `[tool.pytest.ini_options]` so the suite also runs without an installed package (no `pip install -e .` prerequisite). |
| `floatchat/tests/test_api/test_routes.py` | **Migrated** `test_general_query_uses_context_hint` → `test_scientific_followup_overrides_classifier_result` (rationale in §3). |
| `floatchat/tests/test_deployment_mode.py` | Added autouse `_restore_deployment_mode` fixture restoring `settings.deployment_mode` after each test — closes a cross-test mutation leak through the global settings singleton. |

### Configuration

| File | Change |
|---|---|
| `floatchat/src/floatchat/config.py` | Removed the hardcoded Windows default `E:\floatchat_data_lake\` (now `""` by design); enabled optional `.env` loading (`env_file=".env"`); documented both in comments. |
| `floatchat/src/floatchat/api/dependencies.py` | `get_data_lake()` only attempts the Phase 2 lake when it is **explicitly configured** (`data_lake_dir` non-empty) **and** populated on disk; otherwise falls back to the Phase 1 path. No behavior change for configured deployments. |
| `floatchat/.env.example` (new) | Documented template for per-machine settings (data-lake paths, LLM provider, API keys); `.env` itself stays git-ignored. |

### Dependency audit

| File | Change |
|---|---|
| `floatchat/pyproject.toml` | Added undeclared runtime deps `python-dateutil>=2.8.0` (imported by `query_engine/engine.py`) and `rapidfuzz>=3.0.0` (imported by `query_normalizer/fallback.py` — previously an undeclared optional import whose difflib fallback behaved differently, making behavior env-dependent). Removed unused `respx` (zero imports in the suite) and duplicated `httpx` from the `dev` extra (still a runtime dependency, required by FastAPI's `TestClient`). |
| `frontend/package.json` | Removed 5 dependencies with **zero imports** anywhere in `app/`, `components/`, `hooks/`, `services/`, `types/`, `lib/`: `@deck.gl/core`, `@deck.gl/layers`, `@deck.gl/react`, `@deck.gl/widgets`, `class-variance-authority`. |
| `frontend/package-lock.json` | Regenerated lockfile (378 removed entries); verified with `tsc --noEmit` (exit 0) and a full `next build` (success). |

### Repository hygiene

| File / Path | Change |
|---|---|
| `floatchat/src/check_duckdb.py`, `check_schema.py` (repo root), `floatchat/rebuild_float_registry.py`, `floatchat/package.py` | Moved to `floatchat/scripts/` and rewritten with `argparse`/env-based CLIs — no hardcoded machine paths, in-memory DuckDB connections, explicit `--lake-root`. |
| `.config/nextjs-nodejs/config.json` | Deleted — one-developer-machine tool config. |
| `.data_lake/.gazetteer_cache/nominatim_cache.json` | Deleted — runtime geocoding cache (regenerated on demand). |
| `floatchat/.cache_stream_verify/*.txt.gz` (~70 MB) | Deleted — stale GDAC index download caches. |
| `all_variables_summary.csv` | Deleted — 512-byte header-only stub dataset, unreferenced by code. |
| `frontend/tsconfig.tsbuildinfo` | Deleted — TypeScript incremental build artifact. |
| `floatchat/src/floatchat/intent_resolution/test_variable_integration.py` | Deleted — exact 58-line duplicate of the maintained `floatchat/tests/test_variable_integration.py`, sitting inside the shipped package. |
| `floatchat/src/floatchat/scientific_explanation/test_features.py` | Deleted — empty 0-byte file inside the shipped package. |
| `.gitignore` | Added `**/.data_lake/`, `**/.cache_stream_verify/`, `*.tsbuildinfo`, `*.egg-info/`, `floatchat-v*.zip`, and `!.env.example` (template stays checkable). |

### Documentation accuracy

| File | Change |
|---|---|
| `floatchat/README.md` | Corrected the false "queries GDAC in real time — no cache, no database" claim (chat traffic reads the local DuckDB/Parquet lake; live GDAC is flag-gated & ETL-only); current architecture diagram; refreshed project-structure tree; added `FLOATCHAT_DATA_LAKE_DIR` / `_ROOT`, `ALLOW_REMOTE_GDAC_FALLBACK`, `LLM_PROVIDER` rows; documented `.env` usage and cwd-independent tests. |
| `floatchat/ARCHITECTURE.md` | Dated accuracy banner marking the file as the Phase 1 design record and listing where the current runtime differs; original text retained verbatim (no wholesale rewrite, per scope). |
| `frontend/README.md` | Replaced every Leaflet reference with MapLibre GL (`react-map-gl` + `maplibre-gl` CSS in `components/Map/MapPanel.tsx`); removed all Next.js proxy/rewrite claims (the app calls the backend **directly**; CORS is handled server-side); corrected the `next.config.js` description; documented `NEXT_PUBLIC_BACKEND_URL`; fixed the `/health` example payload. |

## 3. Test Issues Resolved

### 3.1 cwd-dependent results (root cause and fix)

**Symptom:** `pytest` from `floatchat/` → 732 passed / 1 failed; from the repo
root → 731 passed / 2 failed.

**Root cause:** two independent environment couplings.

1. `settings.data_lake_root = ".data_lake/parquet"` is **relative to the
   process cwd**. From `floatchat/`, it resolved to a sample lake that had
   been committed at `floatchat/.data_lake/parquet`; from the repo root it
   resolved to a nonexistent `<root>/.data_lake/parquet`, so DuckDB readiness
   checks failed and `test_health_endpoint` (expects `status == "ok"`) broke.
2. `settings.data_lake_dir` defaulted to the Windows path
   `E:\floatchat_data_lake\`. With `data_lake_phase2_enabled=True` (the
   default), the API layer first probed that path — machine-specific and
   meaningless on any other checkout.

**Fix (no code-path redesign):** `conftest.py` now pins the settings singleton
to an **absolute path inside the repo** (`tests/fixtures/lake_parquet` — the
same sample lake, relocated), disables the Phase 2 lookup during tests, and
raises a clear error at collection time if the fixture is deleted. A
session-scoped `fixture_lake_root` fixture exposes the path for future tests.
`test_data_lake/test_duckdb_lake.py` was already cwd-safe (synthetic
`tmp_path` parquets) and needed no change. A new repo-root `pytest.ini` plus
`pythonpath` entries make discovery and imports identical in both supported
working directories.

**Result:** identical `733 passed` from `$REPO_ROOT` and from
`$REPO_ROOT/floatchat`, with no env vars, no network, and no OS assumptions.

### 3.2 Obsolete-behavior failure: `test_general_query_uses_context_hint`

**What the old test asserted:** that a follow-up classified as `GENERAL_QUERY`
("Explain this graph" after a data query) is answered by the legacy
`_handle_general_query_legacy` path — a direct LLM call whose prompt embeds a
"Conversation Context" hint.

**Why that behavior is obsolete (not a regression):**

1. The production classifier **never emits `GENERAL_QUERY`** — it is a legacy
   alias kept only for backward compatibility; the classifier's LLM fallback
   maps it to `KNOWLEDGE_QUERY`.
2. Even when a classifier does produce `GENERAL_QUERY` for a deictic
   follow-up during an active scientific conversation,
   `_is_active_scientific_followup` in `routes.py` (definition keyword +
   deictic reference over a live profile context) **overrides it to
   `DATA_QUERY`**, so the follow-up stays on the data pipeline and the legacy
   LLM branch never runs in production.

**Action taken:** the test was **migrated, not suppressed** —
`test_scientific_followup_overrides_classifier_result` drives the identical
conversation, forces the legacy `GENERAL_QUERY` classification on turn 2, and
asserts the *current* architecture: the classifier override wins, canonical
resolution declines gracefully (`intent == "unknown"`), the reply is a
context-aware suggestion message that still references the turn-1 scientific
context (`DOXY`, `Arabian Sea`), and the LLM is **never called**. The full
rationale is recorded in the test docstring for future maintainers.

### 3.3 Cross-test state leak (latent)

`test_deployment_mode.py` mutated the global `settings.deployment_mode`
without restoring it — a seed-order-dependent hazard under a shared process.
Fixed with a module-local autouse fixture that snapshots and restores the
value. Failure was latent (no observed breakage) but the fix is zero-cost
insurance for future suite reordering.

## 4. Configuration Improvements

| Before | After | Why |
|---|---|---|
| `data_lake_dir = "E:\\floatchat_data_lake\\"` (one developer's machine, in git) | `data_lake_dir = ""`; set via `FLOATCHAT_DATA_LAKE_DIR` (env or `.env`) | Portable default; machine paths must not live in version control. |
| Phase 2 lake probed whenever the toggle was on, even with the empty/foreign path | `get_data_lake()` requires phase-2 enabled **and** a configured, populated directory; otherwise falls back to the Phase 1 path | Deterministic startup on any machine; no silent probing of foreign paths. |
| No `.env` support (env-only configuration) | `env_file=".env"` in pydantic-settings, plus a documented git-ignored-safe `.env.example` | Standard developer workflow without leaking machine paths or API keys. |
| Tests inherited ambient env (`FLOATCHAT_*` could silently change results) | Suite pins the three lake-related settings to the committed fixture | Determinism regardless of the developer's shell. |
| `rapidfuzz` imported opportunistically with a behavioral difflib fallback | Declared as a runtime dependency (matches what the test suite had been asserting against) | Same behavior in every environment. |
| `python-dateutil` used but undeclared (relied on pandas' transitive dep) | Declared explicitly | Install correctness independent of pandas' internals. |

**Intentional, documented DX change:** the sample lake used to double as an
implicit dev lake under `floatchat/.data_lake/parquet`. Running `uvicorn` from
`floatchat/` *without* configuration now reports `/health = "degraded"`
(app starts and answers normally; data queries honestly report "no data")
until `FLOATCHAT_DATA_LAKE_DIR` (real lake) or `FLOATCHAT_DATA_LAKE_ROOT`
(e.g. the fixture lake) is set. This is deliberate — a lake location is a
per-machine fact and is documented in `README.md` + `.env.example`.

## 5. Repository Cleanup Performed

See the table in §2 ("Repository hygiene"). Summary: 8 artifact/duplicate
paths deleted (runtime caches, ~70 MB of stale GDAC index downloads, a
tsbuildinfo, a one-developer tool config, a header-only stub CSV, an
in-package duplicate test, an empty in-package test file), 4 maintenance
scripts relocated from importable package/root space into
`floatchat/scripts/` with machine-independent CLIs, `.gitignore` extended so
whole categories of artifacts cannot be re-committed accidentally.

**Preserved deliberately (still part of the app):** `intent_parser/` legacy
parsers (unit-tested, used by tooling/tests), `repository_service/` +
`metadata_service/` (offline ETL + explicit export path), the committed
fixture lake, all docs under `floatchat/docs/`.

## 6. Validation Evidence

| Check | Command | Result |
|---|---|---|
| Suite from backend dir | `cd floatchat && python3 -m pytest tests/ -q` | **733 passed** (25.9 s) |
| Suite from repo root | `cd <root> && python3 -m pytest -q` | **733 passed** (24.7 s) |
| Import validity | `from floatchat.api.main import app` (+ suite collection) | OK |
| App starts (no config, neutral cwd) | `uvicorn floatchat.api.main:app` from `/tmp` | `GET /health` → 200 `degraded`; `POST /api/v1/chat` → 200 |
| Env-driven config | `FLOATCHAT_DATA_LAKE_ROOT=<fixture>` | `GET /health` → `{"status": "ok", "levels_ready": true, ...}` |
| Frontend types | `npx tsc --noEmit` | exit 0 |
| Frontend build | `npx next build` | success (4/4 pages prerendered) |

Environment note: `npm` prints a pre-existing `EBADENGINE` warning
(a transitive dev dependency prefers Node ≥ 22; the verified toolchain here
was Node 20.20.2). Unrelated to these changes; recorded for M2.

## 7. Remaining Work for Milestone 2

Per the architecture assessment (`floatchat_cleanup_assessment.md`, roadmap
steps deferred by M1 scope):

1. **LLM-fallback consolidation (roadmap step 5):** delete the dead
   GENERAL_QUERY legacy branch, `LLMEntityExtractor` / `QuerySpec` /
   `_try_llm_extraction*` once the IntentResolver LLM-compiler path is
   confirmed equivalent; also unblocks removing the `entity_extractor/`
   package and `routes.py` lines 351+.
2. **ParsedIntent tightening (step 12):** split the god-model into
   use-case-specific shapes now that tests are trustworthy.
3. **`routes.py` decomposition (step 7):** extract `floats_service` and move
   route-local helpers (`_build_context_prompt`, suggestion building,
   narration plumbing) out of the 1,974-line module.
4. **`query_engine/engine.py` split (step 9):** separate region resolution,
   alive-window computation, and lake-vs-legacy selection.
5. **Planner decision (step 11):** keep + test or retire
   `retrieval_planner/` — decide with deterministic tests as the safety net.
6. **Node toolchain pin (new):** add an `.nvmrc` / `engines` entry and fix
   the `EBADENGINE` warning source.
7. **Dev-dependency posture (new):** consider `pip-audit`/`npm audit` in CI
   once CI exists.

**Maintainer action required after pulling these commits:**

```bash
cd floatchat
cp .env.example .env    # then set FLOATCHAT_DATA_LAKE_DIR to your lake root
pip install -e ".[dev]" # refreshed declarations (dateutil, rapidfuzz)
cd ../frontend && npm install   # prunes removed @deck.gl/* and cva packages
```

Nothing in these commits changes runtime behavior for a correctly configured
deployment; the only visible difference without configuration is the now-honest
`degraded` health status instead of probing a foreign hardcoded path.
