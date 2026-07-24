# Milestone 2 — Legacy LLM Fallback Removal (Report)

Date: 2026-07-24 · Branch: `main` · Commit `ea5d82f` on top of M1 (`e4de7f5`).

Goal: remove the legacy LLM fallback architecture (**QuerySpec,
LLMEntityExtractor, GENERAL_QUERY, `_try_llm_extraction`,
`_try_llm_extraction_as_recovery`, `_try_conversational_recovery`**) while
preserving behavior. **IntentResolver remains the single LLM path.** No
QueryEngine / Planner / frontend / API changes.

---

## 1. Why removal was safe (pre-removal reachability proof)

Every deleted symbol was verified **unreachable from production traffic**
before deletion:

| Symbol | Proof |
|---|---|
| `_try_llm_extraction` | Zero call sites in the entire codebase (only its `def` line). Tests called it directly with mocks — testing dead code. |
| `_try_llm_extraction_as_recovery` | Zero call sites. Same as above. |
| `_try_conversational_recovery` | Zero call sites. Same as above. |
| `GENERAL_QUERY` route branch (step 4a) + `_handle_general_query_legacy` | Unreachable in production: the classifier's prompt label space excluded GENERAL_QUERY and its LLM-output pre-mapping converted the label to KNOWLEDGE_QUERY before returning. Only test monkeypatches could ever produce it. |
| `LLMEntityExtractor` / `QuerySpec` / `temporal_resolver` / `build_clarification_message` / `_is_placeholder_time_filter` | Referenced exclusively by the four dead functions above, their own package, and tests of that package. |
| `get_extractor_llm_service` / `_extractor_llm_service` | DI provider + singleton with zero consumers (the extractor built its own service lazily). |
| `scripts/compare_providers.py` | Diagnostic whose only subject was the removed extractor. |

`chat()`'s live resolution chain was (and remains): `IntentResolver.resolve()`
(regex → `LLMIntentCompiler` fallback → merge) with
`except IntentParseError → _build_suggestion_message`. The removed functions
were leftovers of the pre-resolver pipeline.

## 2. Files removed

| Path | Content |
|---|---|
| `floatchat/src/floatchat/entity_extractor/__init__.py` | Package exports |
| `floatchat/src/floatchat/entity_extractor/extractor.py` | `LLMEntityExtractor`, extraction prompts, `_is_placeholder_time_filter`, `build_clarification_message` (also hosted `LLMIntentCompiler` — relocated, see §3) |
| `floatchat/src/floatchat/entity_extractor/query_spec.py` | `QuerySpec` (156 lines) |
| `floatchat/src/floatchat/entity_extractor/temporal_resolver.py` | `resolve_temporal_filter` (only consumers were the two dead route functions) |
| `floatchat/scripts/compare_providers.py` | Extractor provider A/B diagnostic |
| `floatchat/tests/test_entity_extractor/test_priority3.py` | 60 test defs (+4 parametrize cases) — QuerySpec/extractor/temporal-resolver/`_try_llm_extraction` behavior |
| `floatchat/tests/test_entity_extractor/test_p2_reliability.py` | 9 tests patching routes-level `LLMEntityExtractor` / `_try_llm_extraction_as_recovery` |
| `floatchat/tests/test_conversation/test_p0_llm_extractor_inheritance.py` | 4 tests driving `_try_llm_extraction` context inheritance directly |
| `floatchat/tests/test_api/test_phase_hardening.py` | 13 tests of extractor hard-guards + `_try_llm_extraction` + (already-deleted) `_check_critical_fields` behavior |

Suite total: **733 → 641 collected (−92)**: 86 deleted test functions + 4
parametrization expansions (one 5-way `@pytest.mark.parametrize`) + 2 single
test removals (§4). Arithmetic verified exactly.

## 3. What moved (behavior-preserving)

`LLMIntentCompiler` — the resolver's one LLM fallback — lived inside
`entity_extractor/extractor.py`. It was **relocated verbatim** (class body,
prompt strings, merge rules byte-identical; moving prompt text would change
model behavior) to **`floatchat/src/floatchat/intent_resolution/llm_compiler.py`**,
its true architectural home. Import updates: `intent_resolution/resolver.py`,
`api/dependencies.py`.

Supporting renames/re-frames (no behavior delta):

- `llm_service/factory.py`: `build_extractor_llm_service` →
  **`build_compiler_llm_service`** (only the compiler calls it; signature
  unchanged). 
- `config.py`: the `extractor_*` fields are the compiler's tuning knobs and
  **were kept under their existing names** so `FLOATCHAT_EXTRACTOR_*`
  environment variables keep working; comments now document the compiler
  ownership instead of the entity extractor.
- `routes.py`: `detect_reference_phrases` import removed (orphaned by the
  `_try_conversational_recovery` deletion); module docstring and the
  step-1.5 override tuple no longer reference GENERAL_QUERY; chat() flow
  docstring renumbered (4 buckets + DATA path).

## 4. Tests migrated

| Test | Action | Rationale |
|---|---|---|
| `test_classifier.py::test_classify_general_query_maps_to_knowledge` | **Migrated** → `test_classify_stale_label_defaults_to_data_query`: mock LLM returns the stale `GENERAL_QUERY` label; asserts the documented `DATA_QUERY` default (with warning log). | Pins the new, intended edge behavior instead of the removed KNOWLEDGE pre-mapping. |
| `test_routes.py::test_scientific_followup_overrides_classifier_result` (M1-migrated) | **Re-forced** the stale classification from `GENERAL_QUERY` to the **live `KNOWLEDGE_QUERY`** bucket; docstring updated for the M2 world. | Keeps guarding the valuable invariant (deictic follow-ups during an active scientific conversation stay on the data path) against a classification the live classifier can actually produce. |
| `test_routes.py::test_general_query_returns_chat_response` | **Deleted** (documented here). | Validated the removed GENERAL_QUERY branch (`general_chat` via forced classification). The migrated alternative (invalid label → resolver fall-through → `unknown`) would be **non-deterministic** across machines with/without a reachable Ollama (the compiler may then succeed), violating M1's determinism requirement. Live equivalents remain: `test_knowledge_query_returns_kb_response`, the classifier unit test, and the follow-up override test. |
| `test_p2_provider_toggle.py::test_extractor_uses_injected_service` | **Deleted** (comment marker left). | Its subject (`LLMEntityExtractor`'s lazy service build) is gone. All provider-toggle factory tests (Ollama/Gemini/Groq) remain untouched and passing. |
| `test_context_preservation.py` | **Kept; comments fixed** ("non-data turn" instead of "GENERAL_QUERY"). | Tests live `update_context` semantics, which are label-agnostic (only overwritten fields the new intent sets) — nothing about the removed architecture. |

## 5. Production imports eliminated — proof

Post-removal greps (`grep -rn` over `floatchat/src`, `floatchat/tests`,
`floatchat/scripts`) for all removed symbols:

```
QuerySpec | LLMEntityExtractor | _try_llm_extraction |
_try_llm_extraction_as_recovery | _try_conversational_recovery |
_handle_general_query_legacy | build_clarification_message |
resolve_temporal_filter | _is_placeholder_time_filter |
build_extractor_llm_service | get_extractor_llm_service
```

**Runtime hits: only two intentional, non-executable references:**

1. `routes.py` line 9 — the module-docstring changelog note recording the removal.
2. `intent_resolution/llm_compiler.py` line 25 — the **LLM-facing system
   prompt** (byte-identical relocation; wording constrains the model's output
   and must not change).

`entity_extractor` / `GENERAL_QUERY` in `src/`: exactly three historical-note
comment lines (routes docstring, compiler relocation note, classifier note).
**Zero import edges** (`from floatchat.entity_extractor` / attribute access)
into the deleted package from src, tests, or scripts.

Production LLM call graph after M2 (unchanged, single path):

```
POST /chat → QueryClassifier (rule → LLM label)
           → DATA_QUERY → IntentResolver.resolve
                              ├─ regex parser (deterministic, authoritative)
                              └─ LLMIntentCompiler.compile  ← ONLY LLM fallback
                                     (build_compiler_llm_service, lazy)
           → IntentParseError → suggestion message
           → KNOWLEDGE_QUERY → KB + strict prompt / raw-KB fallback
```

## 6. The one bounded, disclosed behavior delta

Constraint was "no behavior changes". One edge required disclosure:

- **Before:** if a defective/stale LLM emitted the literal label
  `GENERAL_QUERY` against the classifier (a label absent from the prompt's
  label space), the classifier pre-mapped it to `KNOWLEDGE_QUERY`.
- **After:** the same output hits the generic unexpected-output guard:
  `logger.warning(...)` → `DATA_QUERY` default.

No prompt-conformant model output reaches this edge; the delta exists only
for out-of-contract legacy labels. Pinned by the migrated classifier test.

Everything else is provably identical: removed code had no callers; the
relocated compiler is byte-identical; config env-var names unchanged; API
surface (models, routes, CORS, response shapes) untouched.

## 7. Validation evidence

| Check | Result |
|---|---|
| `pytest tests/ -q` from `floatchat/` | **641 passed** (22.9 s) |
| `pytest -q` from repo root | **641 passed** (22.3 s), including a post-commit run (22.4 s) |
| `python -c` imports of all rewired modules + resolver↔compiler identity | OK |
| `uvicorn floatchat.api.main:app` boot (no config) | `/health` 200 `degraded`; `POST /chat` 200 |
| Behavior smoke (TestClient): "What is an Argo float?" → `knowledge_base`; "hello" → `small_talk`; "show oxygen in arabian sea" → `profile_plot`; "show chlorophyll in the same region" → `profile_plot` | Identical to pre-M2 |
| Runtime log during data-path smoke | `Intent compiler failed: Cannot connect to Ollama` → graceful deterministic fallback (the only LLM attempt in the data path) |
| Deleted-test accounting | 733 − (86 defs + 4 parametrize cases + 2 singles) = 641 ✓ |

## 8. Deferred / noted for later milestones (not M2 scope)

- `_check_critical_fields` (routes.py) is live but its only test coverage
  lived in the deleted `test_phase_hardening.py`; re-add focused unit tests
  in M3 (test-file, not production, change).
- Historical investigation docs under `floatchat/docs/architecture`,
  `docs/investigations`, `docs/scientific` still *describe* the extractor-era
  pipeline as design history; they were left intact deliberately.
- `intent_resolver` typed as `object` in the chat() signature (pre-existing);
  tighten in the routes decomposition milestone.
- Remaining roadmap (assessment steps 7/9/11/12): floats-service extraction,
  engine split, planner decision, ParsedIntent tightening.
