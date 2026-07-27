# FloatChat 2.0 — Phase 2.1: Semantic Stabilization (Report)

**Date:** 2026-07-26 · **Branch:** `main` · **State:** staged, not committed.
**Scope:** stabilization pass over Phase 2 only — fix live-testing issues,
raise the share of requests completing through the Semantic Understanding
pipeline, add observability. **No redesign, no Phase 3 features, no behavior
change to the execution engine.**

---

## 1. What Was Fixed

### Issue 1 — SemanticUnderstanding model was too strict (root cause of the fallback storm)

**Live-log symptom:** repeated validation failures with `temporal = None`,
`depth = None`, `spatial = None`, `comparison = None`,
`follow_up_reference = None`.

**Root cause (actually read in code, not inferred):** the schema declared
those fields as non-Optional sub-models with eager defaults
(`temporal: TemporalMention = Field(default_factory=...)`) and non-Optional
booleans. A model emitting an *explicit* null — the natural way to say "this
concept does not exist in the request" — hit pydantic's `TemporalMention`
validation of `None` → ValidationError → `SemanticUnavailableError` → regex
fallback. Nothing was wrong with the request; the schema mistook "absent"
for "broken".

**Fix (`understanding/models.py`):** the schema now mirrors natural language:

- `temporal / depth / spatial / comparison` are `X | None = None` — **None
  means "not mentioned"**. No empty objects are fabricated: an absent concept
  stays absent (asserted by tests), it is simply not a validation failure.
- Tolerant `mode="before"` coercion for the whole failure family: explicit
  `null`, and prose-ish junk (`"none"`, `"n/a"`, `"null"`, `"not applicable"`)
  for structured concepts → "absent"; `"yes"/"no"/"false"` strings for
  booleans → real booleans; digit strings for `profile_number` → int;
  non-list `ambiguities` → `[]`; null `intent_name` → `"unknown"`.
- Tolerance has a floor: genuinely un-coercible content (e.g. an ambiguity
  record missing its required `description`) still fails validation and
  falls back **with a reason** (see Issue 3).

**Converter (`understanding/converter.py`):** treats `None` sub-concepts as
"not mentioned" everywhere (guards in comparison routing, floats, spatial,
temporal, depth grounding). Nothing else changed — same grounding tables,
same ParsedIntent rules, same no-invention policy.

### Issue 1b — Prompt guidance (your recommendation, adopted verbatim)

The system prompt previously *showed* null-filled shapes
(`{"year": int|null, ...}`), implicitly teaching models to emit nulls.
Now (`understanding/prompt.py`):

- Explicit rule: **"Only include fields that are actually present in the
  user's request. Omit fields that are not applicable — a missing field means
  'not mentioned'. Do NOT emit null values."**
- Schema lines reworded to "omit if none" per field; all four examples are
  null-free (verified by a test asserting no `null` literals in the EXAMPLES
  section), including a new "plot dissolved oxygen" example showing a
  scope-free query that omits temporal/spatial/comparison entirely.
- A stray character typo in the `variable_mentions` schema line was fixed.

### Issue 2 — Unnecessary fallback eliminated where it didn't belong

With Issue 1 fixed, null-laden (or omission-style) responses now complete
through the semantic pipeline. The five success-criteria queries are pinned
as automated tests asserting **0 regex calls and exactly 1 LLM call** each
(battery in `tests/test_understanding/test_stabilization.py`):

`Plot oxygen profile for float 1902190` · `Show oxygen for float 5906969
profile 142` · `Plot O2 profile 5906969` · `Plot dissolved oxygen` ·
`Show salinity profile` — all resolve SemanticUnderstanding → Converter →
ParsedIntent with no fallback.

Fallback now occurs **only** for the sanctioned classes, each with a
machine-readable reason code: `disabled`, `no_provider`, `llm_error`,
`empty_output`, `not_json`, `schema_invalid`, `conversion_invalid`.
(Ungrounded ontology mentions were already clarification/drop — never
fallback — and remain so.)

### Issue 3 — Instrumentation (one structured line per request)

`SemanticUnderstandingService.resolve()` now emits exactly one
grep/awk-friendly line per request covering every requested field:

```
SEMANTIC_UNDERSTANDING outcome=intent intent=profile_plot confidence=0.95
reason=ok fallback=false semantic_ms=812.3 convert_ms=0.4 total_ms=812.7
msg='Plot oxygen profile for float 1902190'
```

- `outcome=` intent | clarification | failure  → *Success/Failure*
- `reason=` ok | disabled | no_provider | llm_error | empty_output |
  not_json | schema_invalid | conversion_invalid     → *Reason*
- `semantic_ms=` → *Latencia of the understanding (LLM) stage*
- `convert_ms=` → *Converter latency*
- `fallback=` true|false   → *Fallback used?* (clarifications are
  **not** fallbacks)
- `total_ms=` → *Total understanding latency*

The resolver adds one marker line when it switches to the legacy path:
`UNDERSTANDING fallback used=true reason=llm_error message='…'`.
`SemanticUnavailableError` now carries a machine-readable `.reason`
(also copied into `details`) so logs/benches can group causes.

### Issue 4 — One understanding LLM call (verified, no change needed)

Audit of the semantic pipeline (`service.py`, `converter.py`, `resolver.py`):
the understanding stage makes **exactly one** `generate()` call; conversion
is deterministic; the legacy `LLMIntentCompiler` is hard-guarded off the
semantic path (`from_semantic` flag, plus an explicit test that both
`compiler.compile` and `parser.parse` are never called on success). The
Traffic-Cop *classifier* call that may precede resolution is the unchanged
pre-Phase-2 routing bucket step — a different question (SMALL_TALK /
OUT_OF_DOMAIN / KNOWLEDGE / DATA), not duplicated understanding work; it was
deliberately left alone. Two new tests pin the single-call invariant.

### Issue 5 — Deterministic execution preserved

Re-verified after all edits: engine smoke diff **0 changes across 12,262
leaf values**; OpenAPI document **byte-identical** to the baseline. No
changes to ParsedIntent, Planner, QueryEngine, Executors, DuckDB,
Visualization, Scientific Narration, API contracts.

---

## 2. Modified Files

**Modified (8)**

| File | Why |
|---|---|
| `src/floatchat/understanding/models.py` | Issue 1: optional structured concepts are `X \| None = None` (absent, not fabricated); tolerant coercion for nulls/junk strings/booleans/profile_number/ambiguities/intent_name. |
| `src/floatchat/understanding/converter.py` | Issue 1: None-guards in comparison/spatial/temporal/depth grounding ("not mentioned"); reason-tagged defensive raise. |
| `src/floatchat/understanding/prompt.py` | Issue 1b: "omit, don't null" rule; null-free schema wording and examples; schema-line typo fix. |
| `src/floatchat/understanding/exceptions.py` | Issue 3: machine-readable `reason` (+REASON_* constants) on `SemanticUnavailableError`. |
| `src/floatchat/understanding/service.py` | Issues 3+4: per-request SEMANTIC_UNDERSTANDING instrumentation line (outcome/reason/latencies/fallback/total); reason-coded raises; single-call marker comment. |
| `src/floatchat/intent_resolution/resolver.py` | Issue 3: resolver-level fallback marker line now carries the reason code. |
| `tests/test_understanding/test_semantic_models.py` | Updated the minimal-defaults pin to the new natural-absence contract (None, not empty objects). |
| `tests/test_understanding/test_service.py` | Schema-invalid test retargeted: nulls/junk are now tolerated (tolerance floor test kept on a genuinely-invalid payload). |

**Created (2, outside the runtime)**

| File | Why |
|---|---|
| `tests/test_understanding/test_stabilization.py` | 24 regression tests: null-tolerance repro, 5-query success battery (0 regex / 1 LLM call), instrumentation fields+reasons, single-call invariant, "omit" prompt rules. |
| *(bench, not staged)* `/home/user/m4_baseline/semantic_bench.py` | Offline 32-query metrics harness consuming the real instrumentation lines (rates, latencies, reason/outcome histograms). |

No execution-side files were touched. No ontology files were touched.

---

## 3. Test Results (all actually run)

**Automated suites**

| Check | Result |
|---|---|
| Full suite, repo root (`python3 -m pytest -q`) | **909 passed** (was 885 at Phase 2; +24 stabilization tests) |
| Full suite, package root (`python3 -m pytest tests/ -q`) | **909 passed** |
| Understanding package only | **145/145 passed** |
| Engine smoke leaf-diff vs pre-Phase-1 baseline | **12,262 leaves, 0 diffs** |
| OpenAPI vs baseline | **byte-identical** |

**Offline bench (`semantic_bench.py`, 32-query battery, provider-stubbed;
numbers consume the real instrumentation lines):**

```
queries run                : 32
converted → ParsedIntent   : 24
clarification (no fallback): 3
fallback used              : 5
semantic success rate      : 27/32 = 84.4%
fallback rate              : 5/32 = 15.6%
instrumentation lines      : 32 (1 per query)
avg semantic latency       : 0.02 ms   (stubbed provider; live reports the real provider latency in the same field)
avg converter latency      : 0.01 ms   (deterministic grounding, measured)
avg total understanding    : 0.06 ms
reason histogram           : {'empty_output': 1, 'llm_error': 1, 'not_json': 2, 'ok': 27, 'schema_invalid': 1}
outcome histogram          : {'clarification': 3, 'failure': 5, 'intent': 24}
```

Reading of the numbers: the 5 fallbacks are the battery's **deliberately
injected** provider-side failure cases (the sanctioned classes); every
well-formed scenario completes semantically — **27/27 = 100%** of
non-injected queries. In live runs the same fields carry real provider
latencies, so `success rate` and `avg latencies` can be computed from logs
with a one-liner (`grep SEMANTIC_UNDERSTANDING | awk …`).

**Manual live test to repeat:** rerun queries that logged
`temporal=None …` validation failures before — they should now log
`SEMANTIC_UNDERSTANDING outcome=intent … fallback=false`, and the five
success-criteria queries should complete with figures and no
`fallback used=true` line.

---

## 4. Git Staging

Staged (not committed), exactly the Phase 2.1 surface; `FLOATCHAT_ARCHITECTURE_CONTEXT.md` left untracked as before. Pending your testing/approval. **Phase 3 not started.**
