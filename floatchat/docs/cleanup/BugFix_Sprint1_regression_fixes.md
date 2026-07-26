# Bug Fix Sprint 1 — Post-Cleanup Functional Regression Fixes

**Date:** 2026-07-26 · **Branch:** `main` · **Base:** `b3f65f6` (post-M5 cleanup state)
**Scope:** 8 user-facing bugs on the frozen Milestone-1–5 architecture. Behavioral defect
fixes only — no redesign, no refactors, no layer moves, no ParsedIntent contract changes,
no Planner/QueryEngine rewrites. All changes confined to the existing layers
(API Services, Intent Parser heuristic rules, Executor internals, DataLake internals,
Visualization internals).

---

## 1. Executive Summary

**All 8/8 bugs fixed and validated.** Each fix is a surgical behavioral correction inside
an existing layer; the frozen architecture (layers, contracts, signatures, OpenAPI,
data-intent vocabulary) is provably unchanged.

| # | Bug (user symptom) | Status |
|---|--------------------|--------|
| 1 | `Tell me about float 1902190` → profile plot | ✅ routes to `metadata_lookup` (metadata card) |
| 2 | `What plots are available for float 2903467?` → profile plot → Plotly crash | ✅ deterministic `available_plots` answer, no rendering |
| 3 | `Show oxygen profile for 4902623` ignores the id, wrong float | ✅ `float_id=4902623` populated, query scoped |
| 4 | `Show temperature profiles in Arabian Sea` → 1 float | ✅ `region_search`; every matching float + all map markers |
| 5 | `Nearest float to Chennai` → map shows no markers | ✅ markers carry `region_tag`/`network`/`wmo_id` |
| 6 | `How many floats are in Arabian Sea?` → 0 | ✅ schema-verified count path + `pytz` declared |
| 7 | `Compare temperature of floats A and B` → only one float apparent | ✅ both floats retrieved/plotted; message names all + discloses missing |
| 8 | Plotly `Vertical spacing cannot be greater than …` | ✅ spacing clamped per grid; junk columns excluded |

**Validation summary** (details in §4–§5): the 12-query success matrix passes; test suite
grows **668 → 715** (+47 new tests) with zero regressions from both launch roots; a 16-case
deterministic engine smoke diff against the pre-sprint snapshot shows **exactly** the 83
intended leaf deltas and nothing else; the public API's OpenAPI document and all frozen
signatures are byte-identical.

---

## 2. Root Cause Analysis

### Bug 1 — Metadata routing (`Tell me about float 1902190`)

- **Where:** `floatchat/src/floatchat/intent_parser/regex.py :: RegexIntentParser.parse`
  (+ `_detect_intent`).
- **Root cause:** `_detect_intent` has no linguistic rule for "tell me about float X".
  The query matches no keyword family (not metadata, not trajectory, not spatial, …),
  so it falls through to the catch-all `return "profile_plot"`. The QueryEngine then
  executes the profile pipeline and the user gets a plot instead of the metadata card
  (sensors, latest-profile summary).
- **Why this fix:** a deterministic post-classification override in `parse()`:
  `intent == "profile_plot" ∧ float_id ∧ no variables ∧ phrase matches
  ("tell me about" | "show/display/describe/give [me] float") ∧ no visualization
  keyword` → `metadata_lookup`. The guards keep measurement requests ("tell me about the
  oxygen of float X", variables extracted) and explicit visualization requests ("show
  trajectory of float X") on their legacy routes. The override site mirrors the existing
  radius→profile routing override — a semantic routing decision after pure linguistic
  classification — so parser architecture is untouched.

### Bug 2 — Available-plots routing (`What plots are available for float 2903467?`)

- **Where:** `regex.py` (routing) + `floatchat/src/floatchat/api/services/chat_service.py`
  (deterministic interception).
- **Root cause:** two-layer.
  1. The parser had no rule for capability phrasing → same fallthrough to `profile_plot`.
  2. Downstream, a `profile_plot` intent with **empty `variables`** made the visualization
     engine's fallback treat *every numeric column* as a variable (including identifiers —
     see Bug 8), producing a ~20-row subplot grid that Plotly cannot lay out → the crash
     the user saw. ("available_plots" is not in the frozen ParsedIntent literal, so no new
     intent was introduced — the contract is untouched.)
- **Why this fix:** (a) module-level `is_available_plots_query()` (narrow pattern:
  `plot(s) … available` adjacency only — bare "show plot" is not captured); the parser
  routes it to `metadata_lookup`, a safe engine fallback. (b) In `handle_chat`'s
  DATA_QUERY path, after the mixed-plan branch and before execution, a deterministic
  interception calls the existing `build_available_plots_response(float_id)` (already used
  by `GET /floats/{id}/available-plots`) and returns `ChatResponse(intent="available_plots",
  figure=None, map_data=[], data_summary.available_plots=[…])`. Only variables with ≥1
  profile are listed (TEMP/PSAL/DOXY/CHLA/… order). `available_plots` is a response label
  (free string on ChatResponse), not a ParsedIntent change. Placing the interception after
  the mixed-plan check preserves mixed knowledge+data queries ("… and explain X").

### Bug 3 — Float-ID parsing (`Show oxygen profile for 4902623`)

- **Where:** `regex.py :: _extract_float_id`.
- **Root cause:** the bare-7-digit fallback (`_BARE_FLOAT_RE = \b(\d{7})\b`) was gated on
  metadata or trajectory keywords only. With profile/plot phrasing the id was discarded,
  `float_id=None`, the engine ran an unscoped latest-profile query and returned an
  arbitrary float's data.
- **Why this fix:** add `_INTENT_PROFILE` to the gate. A profile/plot verb plus a bare
  7-digit run is sufficient evidence the number is a WMO id (years are 4 digits; cycle
  numbers are labelled and < 7 digits). The Planner receives `float_id` on ParsedIntent and
  preserves it (`Plan[profile_plot]: … → filter_float(float_id=4902623) → plot_profile`,
  verified in pipeline logs). Guard test pins that "Show oxygen profile in 2024" does not
  fabricate an id.

### Bug 4 — Region search collapsing to one float (`Show temperature profiles in Arabian Sea`)

- **Where:** (a) `regex.py :: _detect_intent` region branch; (b)
  `floatchat/src/floatchat/query_engine/executors/profile.py` map construction (+ message).
- **Root cause:** two-layer.
  1. **Parser:** the region rule required `not _INTENT_PROFILE.search(text)`. The plural
     "profile**s**" matches `_INTENT_PROFILE`, so the discovery phrasing routed to
     `profile_plot`, whose executor caps `query_limit = 1` → one float, one profile.
  2. **Map payload:** even with `region_search` routing, markers were built only from the
     profile-capped DataFrame (`data_lake_max_profiles`, default 100), so regions with more
     floats than the cap would still lose markers.
- **Why this fix:** (a) a plural exception in `_detect_intent`: plural "profiles" over a
  region with no explicit `float_id` → `region_search` (discovery semantics); singular
  "profile"/"plot" and float-scoped queries keep legacy routing. (b) `region_search`
  responses now union the uncapped `lake.get_map_markers(criteria)` set (dedicated SQL,
  GROUP BY float, LIMIT 5000) into `map_data`; the DataFrame stays capped so the figure
  stays plottable. Additionally the response message for multi-float region results names
  the match set ("… 30 floats in Arabian Sea (45 profiles total)") instead of a single
  float — the "latest profile reduction" only applies when explicitly requested
  (profile-number / single-float queries), per the bug spec.

### Bug 5 — Nearest-float map rendering (`Nearest float to Chennai`)

- **Where:** `floatchat/src/floatchat/query_engine/executors/spatial.py` (nearest + both
  radius branches), `executors/metadata.py` (lookup marker), new helpers in
  `query_engine/helpers.py`.
- **Root cause:** **backend payload inconsistency.** Trajectory and data-query markers set
  `wmo_id`, `network`, and (indirectly) region information, but spatial-metadata markers
  set none of them. The frontend's `applyFilters` (`frontend/lib/utils.ts`) drops markers
  whose `region_tag` is empty while a sidebar region filter is active — so spatial results
  vanished from the map even though the payload contained five valid markers. (With empty
  default filters the markers did render — the failure required an active filter, matching
  the observed map state.)
- **Why this fix:** enrich at the backend — the authoritative place where lat/lon and
  sensor evidence already exist — with pure, deterministic derivations mirroring the
  trajectory executor's semantics: `region_tag = build_region_tag(lat, lon)` (existing
  pure function in `data_lake/duckdb_lake.py`), `network = "BGC Argo"` iff any BGC
  sensor/variable token in the float's sensor list else "Core Argo", `wmo_id = float_id`.
  Frontend untouched (MapPanel renders any marker with valid coordinates; `useChat`
  queryMapData → baseMapData → applyFilters path unchanged).

### Bug 6 — Count query returns 0 (`How many floats are in Arabian Sea?`)

- **Where:** `floatchat/pyproject.toml`; `floatchat/src/floatchat/data_lake/duckdb_lake.py
  :: query_count_aggregate`.
- **Root cause:** two independent failures compounded, both visible in the user's logs.
  1. **Dependency:** `pytz` was never declared (only transitively present on some
     machines). duckdb-python needs it to convert TIMESTAMPTZ (the phase-2 parquet stores
     tz-aware profile dates); `MIN/MAX(date)` aggregates then raised
     `ModuleNotFoundError: pytz`, which the broad `except` swallowed → zeros.
  2. **Schema assumption:** the `region_month_stats` fast path blind-referenced
     `profile_count`/`float_count`. On lakes whose aggregate table uses different column
     names, DuckDB raised a binder error ("Referenced column profile_count not found"),
     again swallowed, so execution depended on the (pytz-broken) fallback.
- **Why this fix:** declare `pytz>=2024.1` (duckdb TIMESTAMPTZ conversion), and
  schema-verify the fast path before use: `DESCRIBE SELECT * FROM read_parquet(…)` (reads
  parquet metadata only — no row values, hence no timestamp conversion and no pytz
  dependency) and require `{profile_count, float_count, region_tag, year, month}` to be
  present, else skip to the profile_index fallback deterministically. SQL structure,
  layer placement, and the fallback itself are unchanged.

### Bug 7 — Comparison shows only one float

- **Where:** `executors/profile.py` message block (lines ~318–336).
- **Root cause:** the deterministic chain was **verified healthy**: the parser preserves
  both ids in `comparison_float_ids`; the executor unions per-float lake queries
  (`dataclasses.replace(criteria, float_id=fid)` for each id); the visualization overlays
  both (2 traces / 2 markers / 2 unique floats with the fixture floats 1901514+1901897).
  The user-visible defect was (i) the message anchored on `intent.float_id` (the parser's
  primary id) and named only that float, and (ii) when one requested float has no matching
  data, the response never said so — looking identical to a single-float answer.
- **Why this fix:** for comparison intents with ≥2 ids, the message lists every float
  actually returned (`Floats A, B`) and appends a disclosure for requested-but-empty floats
  ("No matching TEMP data was found for: …"). Data retrieval, planner, and figure code are
  untouched (already correct).

### Bug 8 — Plotly subplot spacing crash

- **Where:** `floatchat/src/floatchat/visualization_engine/profile.py` (both
  `make_subplots` sites; the empty-variables column fallback).
- **Root cause:** geometric. The main grid uses `vertical_spacing=0.18` with
  `cols=min(3, n_vars)`; Plotly requires `spacing ≤ 1/(rows−1)`, which fails at
  `rows ≥ 7` (i.e. ≥19 variables). The empty-`variables` fallback made this reachable: it
  plotted every numeric column except PRES/profile_idx/level_idx — including float_id,
  cycle_number, year, month, lat, lon — inflating n_vars to ~20.
- **Why this fix:** clamp per grid: `vertical_spacing = min(nominal, 0.9/(rows−1))` (0.9
  keeps a safety margin) at both construction sites, so the grid renders at **any**
  variable count; and extend the fallback exclusion set with identifier/coordinate/time
  columns (float_id, cycle_number, year, month, date, lat, lon, latitude, longitude) so
  storage columns are never plotted as science variables.

---

## 3. Files Modified

| File | Bug(s) | Change |
|------|--------|--------|
| `floatchat/src/floatchat/intent_parser/regex.py` | 1, 2, 3, 4a | `is_available_plots_query()` + `_is_float_info_request()` helpers & patterns; capability route in `_detect_intent`; plural-"profiles" region rule; profile gate in `_extract_float_id`; float-info override in `parse()` |
| `floatchat/src/floatchat/api/services/chat_service.py` | 2 | deterministic available-plots interception in DATA_QUERY path (after mixed-plan, before execution) |
| `floatchat/src/floatchat/query_engine/executors/profile.py` | 4b, 7 | region_search marker union via `get_map_markers`; region message names match set; comparison message names all floats + missing disclosure |
| `floatchat/src/floatchat/query_engine/executors/spatial.py` | 5 | `region_tag`/`network`/`wmo_id` on nearest + both radius marker builders |
| `floatchat/src/floatchat/query_engine/executors/metadata.py` | 5 | same enrichment on the metadata-lookup marker |
| `floatchat/src/floatchat/query_engine/helpers.py` | 5 | `_derive_marker_network()` + `_marker_region_tag()` shared helpers |
| `floatchat/src/floatchat/data_lake/duckdb_lake.py` | 6 | schema-verified `region_month_stats` fast path (deterministic fallback) |
| `floatchat/pyproject.toml` | 6 | `pytz>=2024.1` declared |
| `floatchat/src/floatchat/visualization_engine/profile.py` | 8 | vertical-spacing clamp at both `make_subplots` sites; junk-column exclusions |

**New tests (47):**
`tests/test_intent_parser/test_sprint1_routing.py` (Bugs 1/2/3/4a + guards),
`tests/test_api/test_chat_service_available_plots.py` (Bug 2),
`tests/test_query_engine/test_sprint1_region_markers.py` (Bug 4b),
`tests/test_query_engine/test_sprint1_marker_enrichment.py` (Bug 5),
`tests/test_query_engine/test_sprint1_comparison_message.py` (Bug 7),
`tests/test_data_lake/test_count_schema_guard.py` (Bug 6),
`tests/test_visualization_engine/test_sprint1_spacing.py` (Bug 8).

No frontend files modified. No deletions. No moved modules. No contract edits.

---

## 4. Behavioral Validation (before → after)

Validated end-to-end: message → production `RegexIntentParser` → IntentResolver → Planner
→ QueryEngine → `ChatResponse`, against the committed fixture lake
(`tests/fixtures/lake_parquet`, phase-2 disabled — the suite-hermetic configuration) plus a
synthetic phase-2 lake for Bug 6. Fixture-lake absences are noted; routing decisions are
what the sprint changes.

| # | Query | Before | After |
|---|-------|--------|-------|
| 1 | `Tell me about float 1902190` | `profile_plot`; plot attempt, no metadata card | `metadata_lookup`, float=1902190; metadata card / structured not-found (fixture lacks it) — verified with fixture float 1901897: registry card + 1 map marker, **no figure** |
| 2 | `Show trajectory of float 1902190` | `trajectory` (correct) | unchanged ✅ |
| 3 | `Show latest temperature profile` | `profile_plot`, latest cycle | unchanged ✅ |
| 4 | `Show oxygen profile` | `profile_plot`, latest DOXY | unchanged ✅ |
| 5 | `Show oxygen profile for 4902623` | `float_id=None` → global query → arbitrary float (2902270) | `float_id=4902623` → scoped query → **Float 4902623** DOXY profile |
| 6 | `What plots are available for float 2903467?` | `profile_plot`, vars=[] → Plotly crash path | `available_plots`, `figure=None`; verified with 1901897: `"Available plots for Float 1901897: TEMP, PSAL."` + `data_summary.available_plots=[{TEMP,1},{PSAL,1}]` (all-null DOXY correctly absent) |
| 7 | `Show temperature profiles in Arabian Sea` | `profile_plot`, limit=1 → **1 float, 1 marker** | `region_search` → **30 floats / 45 profiles / 30 markers**, message: "Showing TEMP profiles for 30 floats in Arabian Sea (45 profiles total)" |
| 8 | `Show floats within 200 km of Goa` | `radius_search` (correct) | unchanged ✅ (0 floats in tiny fixture; radius preserved) |
| 9 | `Nearest float to Chennai` | 5 markers with `region_tag=None, network=None, wmo_id=None` → dropped by active sidebar filters | 5 markers, e.g. `5907082 … region_tag=bay_of_bengal network=Core Argo wmo_id=5907082` — filter-safe |
| 10 | `How many floats are in Arabian Sea?` | 0 (user env: binder error + `ModuleNotFoundError: pytz`, both swallowed) | 33 floats / 103 profiles (fixture); wrong-schema `region_month_stats` now provably falls back (3 profiles/2 floats on synthetic lake); `pytz` declared |
| 11 | `Compare temperature of floats 3902490 and 2903885` | both ids parsed & queried, but message named only `2903885`; a one-float result was indistinguishable | message: "Floats 1901514, 1901897 …" (fixture pair); missing-float disclosure: "No matching TEMP data was found for: 2903885." (unit test); 2 traces / 2 markers verified |
| 12 | `Show float 999999999` | `profile_plot` attempt | `metadata_lookup` → "Float 999999999 was not found in the local data lake." |

**12/12 success-matrix queries behave correctly.**

Bug-8 render proof: 22 variables (rows = 8) raised `Vertical spacing cannot be greater
than 1/(rows - 1)` before; now renders (22 subplots). Empty-`variables` request plots only
measurement variables (identifier/coordinate columns excluded).

---

## 5. Regression Validation

| Check | Result |
|-------|--------|
| Full suite from repo root (`python3 -m pytest -q`) | **715 passed** (668 pre-sprint + 47 new), 0 failed |
| Full suite from `floatchat/` (`python3 -m pytest tests/ -q`) | **715 passed**, 0 failed |
| Deterministic 16-case engine smoke vs pre-sprint snapshot (`engine_smokes_m5_pre.json`) | 83 leaf diffs, **all whitelisted**: 2 message texts (Bug 4 region wording, Bug 7 comparison wording) + 81 `map_data[*].region_tag/network/wmo_id` enrichments (nearest, both radius cases, metadata). **0 unplanned deltas.** |
| Frozen contracts (`signatures_m5_pre.json` comparison) | engine `__init__`/`execute`, planner `__init__`/`plan`, `RetrievalPlan` fields, `data_intents`, `intent_literal`, **ParsedIntent fields — all identical**. (The one baseline-file delta, `cycle_number`, pre-dates the sprint: M5 removed it; re-verified by re-running the check with sprint changes stashed.) |
| OpenAPI surface (`openapi_m5_pre.json`) | **byte-identical** |
| Guard rails (must-not-change routings) | pinned by tests: singular "profile" + region → `profile_plot`; "plot temperature profile in Arabian Sea" → `profile_plot`; float-scoped plural → `profile_plot`; "Show profile #12 of float 7901136" unchanged; bare "show plot" not captured by capability pattern; 4-digit year never parsed as float id; "Tell me about oxygen in Arabian Sea" → `region_search` (no float id) |
| Legacy routing snapshot sanity | comparison still yields `comparison_float_ids=['2903885','3902490']`; count/trajectory/radius/nearest/knowledge classifications unchanged |
| Server boot | `uvicorn floatchat.api.main:app` starts clean; `/health` 200; `/api/v1/chat` serves data & unavailable-lake responses |

### Notes / deliberate non-goals

- `region_search` figures keep the profile cap (`data_lake_max_profiles`) for plottability;
  marker completeness is achieved via the uncapped map query. This matches the bug spec
  ("any 'latest profile' reduction should occur only when explicitly requested" — the
  reduction was the limit=1 routing defect, now removed).
- Union-added region markers carry `network=None` (no per-float sensor evidence is
  available without an extra registry join); `region_tag` and `wmo_id` are set. Honest
  absence was preferred over a guessed network label; response-builder markers from the
  DataFrame retain evidence-based networks.
- Data-query (`profile_plot`/`region_search` DataFrame-derived) markers were left without
  `region_tag` — outside the sprint's diagnosed scope (Bug 5 concerns spatial/metadata
  payloads; Bug 4 concerns completeness under default view). Flagged as a possible
  follow-up if sidebar region-filtering should also preserve data-query markers.
