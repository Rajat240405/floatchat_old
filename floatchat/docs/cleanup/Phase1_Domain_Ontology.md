# FloatChat 2.0 — Phase 1: Domain Ontology Foundation (Report)

**Date:** 2026-07-26 · **Branch:** `main` · **Base:** `56e8c74` (post Bug Fix Sprint 1 state)
**Scope:** create a single canonical source of truth for all Argo domain knowledge
(variables, regions, sensors, intent vocabulary, scientific concepts) and refactor every
existing consumer to consult it. **Behavior-frozen by design:** no change to ParsedIntent,
Planner behavior, QueryEngine, Executors, DuckDB, Visualization logic, Scientific
Narration, or API contracts. No semantic understanding, no LLM changes, no conversation
memory changes, no execution changes. Only the *location* of domain knowledge changed.

---

## 1. Executive Summary

A new pure-data package, `floatchat/ontology/`, now holds the domain vocabulary that was
previously scattered as hard-coded literals across 23 modules (two independent variable
orderings that genuinely differed, three separate BGC-marker token lists, alias tables
duplicated in parser/fuzzy/normalizer paths, a 275-line region-polygon module, platform
metadata split between the executor and API layer, and so on).

- **23 consumer files refactored** to import from the ontology: **−909 / +238 lines**
  (≈ 671 lines of duplicated knowledge removed with zero behavior change).
- **1,530 new lines** in the ontology package (6 modules) + **560 lines** of new
  contract/pinning tests (`tests/test_ontology/`, 49 tests).
- Test suite: **715 → 764 passed** from both launch roots (zero regressions).
- Engine smoke (16 realistic scenarios end-to-end through the real QueryEngine):
  **12,262 output leaf values compared pre- vs post-refactor — 0 differences.**
- Vocabulary snapshot captured from the live pre-refactor modules (every alias list,
  regex pattern string, ordering, typo-map entry, region polygon, platform code) re-verified
  against the post-refactor ontology: **byte-exact, all OK.**

Phase 2 (semantic understanding) has **not** been started, per instructions. Awaiting
confirmation that Phase 1 has been tested successfully before proceeding.

---

## 2. What Was Created

### `src/floatchat/ontology/` — purity rules

Ontology submodules import **nothing** from the rest of `floatchat`. This is deliberate:
`models.intent` → `variable_registry` → `ontology` would otherwise create circular
imports, and purity guarantees the ontology is a leaf dependency that everything may
safely import. Congruence with the runtime contracts (e.g. the `Intent` `Literal`) is
enforced by **tests**, not by importing the contracts.

### Module inventory

| Module | Contents (ground-truth counts) |
|---|---|
| `variables.py` (432 ln) | `VariableDefinition` (parser_synonyms, plot_title, card_title, prompt_units, sensor_keywords, registered, stored_in_levels, …); 13 `VARIABLES` (10 registered + 3 irradiance variables with `registered=False`, verbatim legacy distinction); ordered tuples `REGISTERED_VARIABLE_ORDER` (PRES,TEMP,PSAL,DOXY,CHLA,BBP700,NITRATE,PH_IN_SITU_TOTAL,DOWNWELLING_PAR,TEMP_DOXY), `PARSER_VARIABLE_ORDER` (11, fuzzy order, NITRATE-before-BBP700, tail of the 3 irradiances), `CATALOGUE_VARIABLE_ORDER` (8, NITRATE-before-BBP700), `LEVELS_VARIABLE_ORDER` (8, BBP700-before-NITRATE — the two 8-item legacy orderings genuinely differed and **both were preserved**); `TYPO_CORRECTIONS` (91 entries); `NORMALIZER_CANONICAL_TERMS` (13) + `NORMALIZER_ABBREVIATIONS` (5); `levels_storage_names()` |
| `regions.py` (407 ln) | 13 `RegionDefinition`s in exact legacy order (order is observable: region extraction is first-match); verbatim polygons, bboxes, aliases, `place_names`; `INDIA_QUERY_REGIONS`; `INDIA_DEPLOYMENT_BBOX`; `OCEAN_REGION_PLACE_NAMES` (14 entries — Tasman Sea / Caribbean Sea deliberately absent, as in legacy); ray-casting `point_in_region`; `tag_india_region` |
| `sensors.py` (247 ln) | 7 `SensorDefinition`s; `NETWORK_CORE`/`NETWORK_BGC` ("Core Argo"/"BGC Argo"); `BGC_VARIABLE_MARKER_TOKENS` (7); 29-code `PLATFORM_MODELS` (float model codes 831–864, non-contiguous; manufacturers with country suffix, e.g. "Teledyne Webb (USA)"); `shortlist` flags for the 10 display codes {836,837,841,842,831,832,845,851,861,862}; `platform_lookup()` / `platform_shortlist()` / `manufacturer_short_lookup()` (country-suffix-stripped, matching legacy helpers) / `sensor_keywords_map()`; `DAC_NAMES` (8 codes) |
| `intents.py` (194 ln) | Canonical intent **vocabulary** (not semantic understanding): 17 `IntentDefinition`s with name, kind, description; `NON_DATA_INTENTS` (5); `SCIENTIFIC_CONTEXT_INTENTS` (7); `SCIENTIFIC_FOLLOWUP_INTENTS` (6); `FLOAT_CENTRIC_INTENTS` (3); `RESPONSE_INTENT_DEFINITIONS` (4 response-only pseudo-intents: available_plots, clarification, mixed_query, error). Congruence with the 17-name `Intent` Literal in `models` is pinned by tests. |
| `concepts.py` (130 ln) | 14 `ScientificConcept` glossary entries (BGC float, Core float, Profile, Cycle, Parking depth, Drift depth, Trajectory, Delayed mode, Real-time mode, …) with `kb_entry_id` links to the (already canonical) knowledge base |
| `__init__.py` (120 ln) | Curated public API — the single import surface |

### `tests/test_ontology/` (560 ln, 49 tests)

`test_ontology_contract.py` — pinning tests so any *future* divergence from the frozen
legacy vocabulary fails loudly: byte-exact synonyms/alias/pattern/order checks,
registry ↔ ontology congruence, intent-vocabulary ↔ `Literal` congruence, region
polygon/alias checks, platform table checks, and end-to-end behaviour probes (parser
extraction, fuzzy typo correction, region tagging, BGC/Core classification).

---

## 3. Why This Improves the Architecture

1. **One source of truth where there were N.** Before Phase 1 the same fact existed in
   several places, e.g.: BGC-marker token lists lived in `duckdb_lake.py` (16 tokens),
   `floats_service.py` (13 tokens) and `helpers.py`; variable synonyms were duplicated
   between `regex.py`, `fuzzy.py` and `fallback.py`; the region catalog was split
   between `metadata_service/regions.py` and `metadata_service/polygons.py`. Each copy
   was a drift hazard. Now each fact has exactly one home.
2. **Adding domain knowledge is now an ontology edit, not a code change** — the stated
   goal (`future regions should only require ontology additions`). A new variable: one
   `VariableDefinition`. A new region: one `RegionDefinition`. A new float model: one
   dict entry. Consumers pick it up without touching parser/viz/API code.
3. **Consumer modules shrink and get simpler.** −909/+238 across 23 files; the worst
   offenders (`polygons.py` −263, `fuzzy.py` −123, `regex.py` −94, `regions.py` −76)
   are now thin shims over data they used to embed.
4. **The ontology is a leaf in the dependency graph** (imports nothing from floatchat),
   which is exactly the Phase 2+ prerequisite: the semantic layer will generate queries
   *against* this vocabulary, so it must be importable from anywhere without cycles.
5. **The frozen legacy vocabulary is now *pinned by tests*, not by convention.** The
   49 contract tests turn "behavior must not change" from a hope into a CI-checked fact,
   including subtle observables the runtime tests never covered (e.g. the two differing
   8-item variable orderings, region first-match ordering).

---

## 4. Deliberately NOT Merged (similar ≠ same)

Merged only where copies were **provably identical**. The following look alike but
differ observably; merging them would have changed behavior, and each now carries a
documented note in its module/consumer instead of a hand-waved dedup:

- `LEVELS_VARIABLE_ORDER` vs `CATALOGUE_VARIABLE_ORDER` — both exist; NITRATE/BBP700
  positions differ between them (verified pre-refactor). Both preserved verbatim.
- LLM classifier keyword regexes — prompt-shaping vocabulary, not identical to parser
  synonyms; documented as such, left in `llm_service/classifier.py` (LLM changes were
  out of scope; Phase 2 may revisit).
- `_CONVERSATIONAL_VARIABLE` (resolver) and `_INTENT_REGION_SEARCH` (dispatch) —
  intent-specific vocabularies with different membership; documented, left in place.
- verification_guard alias table — guards scientific-narration claims, not query parsing.
- `floats_service` inline sensor-if chain and its 13-token `_BGC_MARKERS` vs duckdb's
  16-token `_BGC_MARKERS` — different purposes (display heuristics vs storage-time
  network classification); duckdb now derives from `BGC_VARIABLE_MARKER_TOKENS` per its
  legacy 16-token expansion, floats_service keeps its own (13) documented list.
- `seasons.py` / `_MONTH_MAP` — parser-scoped provisional vocabulary, not Argo domain
  ontology; left in the parser.
- Gazetteer — map place names, explicit "not the Argo ontology" by design.
- `prompt_units` vs registry `units` — two genuine legacy surfaces ("m^-1" vs "m⁻¹");
  both kept as separate fields on `VariableDefinition` rather than inventing a
  conversion layer.
- Comparison-plot fallback variable list (viz) — UI default ordering, not registry data.

---

## 5. Modified Files (with one-sentence reasons)

**Created**

| File | Reason |
|---|---|
| `src/floatchat/ontology/variables.py` | Canonical variable records: 13 definitions, all legacy orderings, typo map, normalizer terms, storage-name helper |
| `src/floatchat/ontology/regions.py` | Canonical region catalog: 13 polygon definitions, India helpers, place names, point-in-region |
| `src/floatchat/ontology/sensors.py` | Canonical sensor/profiler/DAC metadata: sensor definitions, 29 platform models, network/BGC marker vocabulary |
| `src/floatchat/ontology/intents.py` | Canonical intent vocabulary: 17 data/non-data intent definitions + 4 response-only pseudo-intents |
| `src/floatchat/ontology/concepts.py` | Canonical scientific concept glossary: 14 entries linked to KB entries |
| `src/floatchat/ontology/__init__.py` | Curated single import surface for the ontology |
| `tests/test_ontology/__init__.py` | Test package marker |
| `tests/test_ontology/test_ontology_contract.py` | 49 pinning/contract tests + behaviour probes guarding the frozen legacy vocabulary |

**Modified (23)**

| File | Reason |
|---|---|
| `variable_registry/registry.py` | Now a façade deriving the 10 registered entries from the ontology; public API (`normalize`, `classify_variables`, `get_all_query_names`, …) unchanged, and re-exports `VariableDefinition` for backward compatibility |
| `intent_parser/regex.py` | Variable/region regex patterns now built from ontology synonyms (same legacy `sorted(syns+[canonical], key=len, reverse=True)` construction — byte-identical pattern strings) |
| `intent_parser/fuzzy.py` | 91-entry typo map + fuzzy candidate vocabulary now sourced from `TYPO_CORRECTIONS` / ontology synonyms |
| `query_normalizer/fallback.py` | Canonical terms (13) and abbreviations (5) now imported from `NORMALIZER_*` |
| `visualization_engine/profile.py` | `_VAR_TITLES` (11) now built from ontology `plot_title`s |
| `api/services/floats_service.py` | `_VAR_TITLES` (9), platform table and manufacturer short-map now sourced from ontology sensors module |
| `query_engine/helpers.py` | Variable/network lookups now consult ontology (sensor keywords, marker tokens) |
| `query_engine/executors/trajectory.py` | Region helpers now import the canonical region functions |
| `query_engine/response_builder.py` | Network display names ("Core Argo"/"BGC Argo") now imported |
| `data_lake/duckdb_lake.py` | `_BGC_MARKERS` expansion and levels-storage names now derived from ontology (legacy 16-token expansion preserved) |
| `query_engine/executors/metadata.py` | DAC names and platform metadata now sourced from ontology sensors module |
| `metadata_service/polygons.py` | 275-line embedded catalog replaced by a thin façade re-exporting ontology region data/functions |
| `metadata_service/regions.py` | Region alias/order data now sourced from the ontology region catalog |
| `data_lake/ingest.py` | India region tagging/bbox now imported from ontology |
| `data_lake/phase2_builder.py` | Levels variable ordering now imported from `LEVELS_VARIABLE_ORDER` |
| `query_engine/engine.py` | Knows about ontology-backed helpers only; behavior unchanged |
| `query_engine/executors/profile.py` | Catalogue variable ordering now imported from `CATALOGUE_VARIABLE_ORDER` |
| `query_engine/dispatch.py` | Intent grouping constants now reference the ontology vocabulary (`_DATA_INTENTS` membership unchanged — pinned by `tests/test_query_engine/test_dispatch.py`) |
| `llm_service/classifier.py` | Keyword tables annotated/sourced from ontology where identical; prompt-shaping regexes deliberately kept local (documented) — no LLM behavior change |
| `intent_resolution/resolver.py` | Scientific/follow-up intent groupings now reference ontology intent sets |
| `conversation/memory.py` | Float-centric intent membership now references ontology sets |
| `api/services/chat_service.py` | Same intent-grouping sourcing as the two above |
| `scientific_explanation/features.py` | `_UNITS`: 16 ontology-derived entries + 2 local CDOM entries (18 total, as legacy) |

**Removed:** none (no files deleted; all deletions are in-file deduplication).

**Untouched per constraints:** `models/` (ParsedIntent, Intent Literal), planner,
query-engine control flow, DuckDB schema/queries, visualization rendering logic,
scientific narration logic, API route/contract layer, and the untracked audit note
`FLOATCHAT_ARCHITECTURE_CONTEXT.md` at repo root.

---

## 6. Verification Evidence (all commands actually run)

Pre-refactor baselines captured first: full test suite green (715/715, both roots);
`legacy_vocab_snapshot.json` — every alias list, pattern string, ordering, typo entry,
polygon, platform code dumped from the **live** pre-refactor modules; engine smoke
snapshot `engine_smokes_phase1_pre.json`.

Post-refactor:

| Check | Result |
|---|---|
| Full suite from repo root: `python3 -m pytest -q -p no:cacheprovider` | **764 passed** (`/home/user/floatchat-2`) |
| Full suite from package root: `python3 -m pytest tests/ -q -p no:cacheprovider` | **764 passed** (`/home/user/floatchat-2/floatchat`) |
| New ontology contract tests | **49/49 passed** |
| Engine smoke 16 cases, leaf-diff vs pre-refactor snapshot | **12,262 leaves, 0 diffs** (`engine_smokes_phase1_final.json`) |
| Legacy vocab snapshot re-verification (byte-exact, incl. regex pattern strings) | **ALL OK** |
| Ontology import purity (`grep` for `floatchat.` imports inside `ontology/`) | none |

(715 legacy tests still pass unchanged; the +49 are the new pinning tests. Two drafting
bugs in my new tests — a parser-level typo probe that can't fire at regex level, and a
`get_all_query_names` expectation that omitted PRES — were caught by the suite itself
and corrected; application code was never implicated: the legacy registry function
returns the identical PRES-inclusive 9-name set at HEAD.)

---

## 7. Known Latent Issue (found, NOT fixed — frozen constraint)

`visualization_engine/profile.py::render_per_variable` references an undefined name
`hover` in `hovertext=hover` → a guaranteed `NameError` on that path. It predates
Phase 1, has no test coverage, and fixing it is a visualization-logic change — out of
scope for the behavior freeze. Logged here so it is not lost; candidate for a later
bug-fix sprint.

---

## 8. Manual Testing Checklist (run before approving Phase 2)

The automated evidence is strong, but phase gates deserve human confirmation of the
user-visible surface:

1. **Regression smoke via the UI/API** for the 12-query matrix from Bug Fix Sprint 1
   (metadata card, available-plots answer, float-scoped profiles, region search with
   full marker set, nearest-float map, Arabian Sea count, multi-float comparison,
   profile-plot spacing) — all should behave exactly as post-Sprint-1.
2. **Variable coverage in chat:** ask for at least one query per registered variable
   (temperature, salinity, oxygen, chlorophyll, backscatter, nitrate, pH, PAR) and
   confirm plot titles/units render exactly as before (e.g. "Chlorophyll-A (mg m⁻³)").
3. **Typo tolerance:** `show tembaratre profile for float <id>`, `chlorophyl`, `salinty`
   — should resolve like before (fuzzy path unchanged).
4. **Region extraction:** queries for Arabian Sea / Bay of Bengal / Indian Ocean and a
   first-match boundary case (a region alias that overlaps two catalogs, e.g. "Southern
   Ocean" vs "South Indian Ocean") — ordering is pinned but worth eyeballing once.
5. **BGC vs Core network labels** on float metadata cards and trajectories ("Core
   Argo"/"BGC Argo" strings and marker styling unchanged).
6. **Float model display:** `tell me about float <id>` — manufacturer string
   ("Teledyne Webb (USA)" → country-suffix stripping in the short map) and the 10-code
   shortlist dropdown look unchanged.
7. **Non-data intents still route:** "what variables are available", "list regions",
   "what is a BGC float" (knowledge answers), scientific follow-ups ("why does oxygen
   dip at 500m?") — identical answers to before.
8. **Ingestion path (if a rebuild is planned anyway):** re-run the phase-2 lake builder
   on a small subset and diff row counts / region tags / network classification —
   expected identical (the parquet is produced by the same logic, now sourcing names
   from the ontology).
9. **Developer check:** `python -c "import floatchat.ontology"` standalone — must work
   without importing any service module (purity guarantee for Phase 2).

---

## 9. Out of Scope (explicitly deferred)

- Phase 2: semantic understanding / LLM-generated queries against this vocabulary.
- Conversation memory redesign.
- Any Planner/QueryEngine/Visualization/Narration behavior change.
- Any API contract change (OpenAPI byte-identical, verified in Sprint 1 and still true).
- Fixing the latent `hovertext=hover` NameError (§7).

**Status: Phase 1 complete. Do not proceed to Phase 2 until the user confirms Phase 1
has been tested successfully.**
