# FloatChat 2.0 — Phase 2: Semantic Understanding Layer (Report)

**Date:** 2026-07-26 · **Branch:** `main` · **Base:** `5918acf` (Phase 1 complete)
**Scope:** introduce the Semantic Understanding Layer and nothing else. The LLM
understands the scientist; deterministic software continues to execute. The
execution side — ParsedIntent schema, Planner, QueryEngine, Executors, DuckDB,
Visualization, Scientific Narration, API contracts — is untouched.

> Status note: changes are **staged, not committed**, awaiting your testing
> and approval (per Phase 2 instructions). Phase 3 has not been started.

---

## 1. Architecture Summary

### 1.1 New understanding pipeline

Current pipeline (pre-Phase 2):

    User → Regex Parser → (legacy LLM compiler fill) → ParsedIntent → Planner → QueryEngine → Executors → DuckDB

Phase 2 pipeline (feature-flagged at the single NL→backend boundary, `IntentResolver`):

    User
      │
      ▼
    Conversation Context ──┐              (+ legacy validation / reference routing / context merge tail, unchanged)
                           ▼
    Domain Ontology ──► LLM Semantic Understanding  ──► SemanticUnderstanding
      (Phase 1, the ONLY          (exactly ONE LLM call;        (understanding contract:
       domain-knowledge source)    structured JSON only)         natural-language mentions,
                           │                                     ambiguity, confidence,
                           ▼                                     clarification requests)
                   Deterministic Converter
                   • grounds every mention via the ontology (variables, regions, intents)
                   • range-checks every value against ParsedIntent rules before construction
                   • seasons/gazetteer/typo tables reused deterministically (parser's own sources)
                   • grounded? ──► ParsedIntent ──► existing tail ──► Planner → QueryEngine → …
                   • ambiguous/incomplete? ──► structured ClarificationRequest (ask, never guess)
                   • any LLM/validation failure? ──► legacy regex parser (identical to pre-Phase-2)

### 1.2 The semantic representation: `SemanticUnderstanding`

Chosen over `SemanticIntent` / `Comprehension` because the object is more than
an intent: it carries entity *mentions* (variables, regions, places, float
ids), temporal/depth/spatial/comparison structure, concept mentions, an
ambiguity list, a clarification channel and a self-reported confidence. It is
deliberately different from `ParsedIntent`:

| | SemanticUnderstanding (understanding contract) | ParsedIntent (execution contract) |
|---|---|---|
| producer | LLM (structured JSON) | converter (deterministic) / regex parser |
| variables | natural-language mentions ("salt levels") | canonical Argo names (`PSAL`) |
| regions | mentions ("the bay of bengal") | canonical `bay_of_bengal` |
| ambiguity | first-class: `ambiguities[]`, `requires_clarification` | none (incomplete → clarification downstream) |
| consumers | converter only | Planner / QueryEngine / everything downstream |

The LLM **never emits ParsedIntent**. This separation is the phase's core
design requirement: the model cannot inject execution values that the
deterministic converter has not grounded and validated.

### 1.3 Why it is superior to regex-first parsing

1. **Paraphrase/synonym tolerance is systemic, not enumerated.** The regex
   parser only recognises phrasings that were hand-anticipated ("salt levels",
   "how salty is the bay of bengal", "o2 situation in arabian waters" were
   never regexable). The LLM maps arbitrary surface forms onto the ontology
   vocabulary; the deterministic converter pins the execution result — same
   meaning, same ParsedIntent (proven by paraphrase-equivalence tests).
2. **Ambiguity becomes structure, not silent failure.** Regex failure used to
   mean a generic "couldn't understand" suggestion. Now incomplete
   understanding returns a targeted, structured clarification
   (`"I couldn't match 'baltic sea' to a known ocean region. Known regions
   include: …"`); under-confident output asks instead of guessing.
3. **Understanding is vocabulary-driven by construction.** The prompt is
   generated from the Phase 1 ontology at runtime — a new variable/region in
   the ontology automatically becomes understandable (test-pinned by an
   ontology-mutation test). No alias list is duplicated.
4. **Strictly safer failure surface.** Under regex-first, parse failure is a
   dead end. Under semantic-first, LLM failure degrades to the regex parser —
   the pre-Phase-2 pipeline is the *fallback*, so the worst case is exactly
   yesterday's behaviour (byte-verified by parity tests + engine smoke).
5. **Boundaries stay clean for later phases.** The understanding layer never
   touches SQL, DuckDB, routing-by-implementation, or computation; the
   execution engine behind ParsedIntent is untouched and byte-verified.

### 1.4 Feature flag & rollback

* `FLOATCHAT_SEMANTIC_UNDERSTANDING_ENABLED=false` — instant rollback to the
  exact pre-Phase-2 regex-first pipeline (DI wiring collapses to
  `understanding=None`).
* `FLOATCHAT_SEMANTIC_MODEL=""` — disables the layer (mirrors the
  `extractor_model` convention); honours the existing `llm_enabled` gate and
  the `FLOATCHAT_LLM_PROVIDER` toggle (ollama default; gemini/groq optional).
* Settings added: `semantic_model`, `semantic_timeout`, `semantic_temperature`,
  `semantic_max_tokens`, `semantic_min_confidence` (defaults documented in
  `config.py`).

### 1.5 What the legacy LLM bits are now

The legacy `LLMIntentCompiler` (emits ParsedIntent JSON directly) remains part
of the **frozen fallback chain only** — it is never invoked on the semantic
path (`from_semantic` guard in the resolver). Retiring it is a later-phase
decision; Phase 2 keeps the compatibility path verbatim.

---

## 2. Semantic Flow

```
                 ┌─────────────────────────── chat_service.handle_chat ───────────────────────────┐
                 │  Traffic-Cop classifier (unchanged): SMALL_TALK / OUT_OF_DOMAIN /             │
                 │  KNOWLEDGE_QUERY / DATA_QUERY                                                  │
                 └───────────────┬───────────────────────────────────────────────────────────────┘
                     DATA_QUERY  ▼
   IntentResolver.resolve(message, session_id)
                 │
                 ▼ semantic layer wired & enabled? ── no ───────────────────────────┐
                 │ yes                                                              │
                 ▼                                                                  │
   SemanticUnderstandingService.understand                                          │
     prompt  = ontology-built system prompt (variables, regions, intents, concepts) │
             + message + prior conversation context (read-only)                     │
     LLM (1 call, JSON mode, temp≈0)                                                │
                 │                                                                  │
                 ▼ invalid/unavailable ──► SemanticUnavailableError ────────────────┤
                 ▼                                                                  │
   SemanticConverter.convert (deterministic)                                        │
     ground: intent name → ontology INTENT_DEFINITIONS                              │
            variable mentions → ontology VARIABLES (+typo map, filler strip)        │
            region mentions → ontology REGIONS                                      │
            place mentions → gazetteer (only when no region; parser parity)         │
            floats/ids/coords/year/month/depth/dates → range validation             │
                 │                                                                  │
     ┌───────────┴───────────────────────┐                                          │
     ▼                                   ▼                                          ▼
 ClarificationRequest              ParsedIntent                                 regex parser (+ legacy compiler chain)
     ▼                                   ▼                                          ▼
 SemanticClarificationNeeded     resolver tail (validate, metadata-followup      identical legacy pipeline
     ▼                             routing, context merge — unchanged)    ◄───────┘
 chat_service →                         ▼
 ChatResponse(intent=                Planner → QueryEngine → Executors → DuckDB
 "clarification")                   (unchanged execution)
```

---

## 3. Modified Files

**Created — `src/floatchat/understanding/` (new package, the whole layer)**

| File | One-sentence reason |
|---|---|
| `understanding/models.py` | The `SemanticUnderstanding` understanding contract + mention/ambiguity sub-models (tolerant pydantic, strict separation from ParsedIntent). |
| `understanding/prompt.py` | Builds the LLM system prompt *from the ontology at runtime* (vocabulary is generated, never duplicated) and the per-request user prompt with prior-context block. |
| `understanding/converter.py` | Deterministic ontology grounding + validation of the understanding into `ParsedIntent` or a structured `ClarificationRequest`; never invents values. |
| `understanding/service.py` | Owns the single LLM call (JSON mode) and validates output into `SemanticUnderstanding`; every failure raises the benign `SemanticUnavailableError`. |
| `understanding/exceptions.py` | `SemanticUnavailableError` (fallback signal) and `SemanticClarificationNeeded` (ask-instead-of-guess signal, subclasses `IntentParseError`). |
| `understanding/__init__.py` | Curated public API of the layer. |

**Created — `tests/test_understanding/` (121 tests)**

| File | One-sentence reason |
|---|---|
| `conftest.py` | `CannedLLM` double (no network ever), passthrough conversation manager, `enable_semantic` monkeypatch fixture. |
| `test_semantic_models.py` | Semantic-representation creation: full/minimal payloads, provider tolerance (extra keys, scalars, clamping). |
| `test_prompt.py` | Ontology grounding of the prompt incl. a mutation test proving the prompt tracks ontology edits automatically. |
| `test_converter.py` | Synonym/paraphrase equivalence, ontology grounding tables, per-intent conversion, comparison contract parity, no-invention drops, ambiguity→clarification rules, confidence gate. |
| `test_service.py` | LLM-output validation, fenced-JSON tolerance, every failure mode → `SemanticUnavailableError`, flag gates, context-in-prompt, converter delegation. |
| `test_resolver_integration.py` | Semantic-primary wiring (parser/compiler not called), clarification escalation, 8-query byte-identical fallback parity vs legacy resolver, flag-off rollback, deterministic-tail application. |
| `test_chat_integration.py` | /chat orchestration: converted intent reaches QueryEngine, clarification response pseudo-intent without engine, dead-LLM user-visible fallback, paraphrase-pair execution identity. |

**Modified (7)**

| File | One-sentence reason |
|---|---|
| `src/floatchat/config.py` | Adds the Phase 2 settings block: feature flag + model/timeout/temperature/max-tokens/min-confidence for the understanding call. |
| `src/floatchat/llm_service/factory.py` | Adds `build_semantic_llm_service()` (same provider toggle/graceful degradation as the compiler builder). |
| `src/floatchat/intent_resolution/resolver.py` | Adds the semantic-first branch (clarification raise / fallback on `SemanticUnavailableError`) and guards the legacy compiler fill-in to the legacy path only; constructor gains optional `understanding=`. |
| `src/floatchat/api/services/chat_service.py` | Catches `SemanticClarificationNeeded` first and answers with the existing `clarification` pseudo-intent (schema unchanged). |
| `src/floatchat/api/dependencies.py` | Adds `get_semantic_understanding()` provider and wires it into `get_intent_resolver()` behind the feature flag. |
| `tests/conftest.py` | Pins `semantic_understanding_enabled=False` for the legacy suite so pre-Phase-2 tests stay deterministic on any machine (same convention as the data-lake pins); understanding tests opt in per-test. |
| `src/floatchat/ontology/*` | **Not modified.** Phase 1 ontology is consumed, not changed. |

**Removed:** none.

---

## 4. Verification Evidence (all actually run)

| Check | Result |
|---|---|
| Full suite from repo root (`python3 -m pytest -q`) | **885 passed** (`/home/user/floatchat-2`) |
| Full suite from package root (`python3 -m pytest tests/ -q`) | **885 passed** (`/home/user/floatchat-2/floatchat`) |
| — of which new understanding tests | **121 passed** |
| Engine smoke (16 intents, real QueryEngine) leaf-diff vs pre-Phase-2 snapshot | **12,262 leaves, 0 diffs** |
| OpenAPI document vs m5 baseline | **byte-identical** |
| DI wiring probe (flag off/on, provider dead) | legacy resolver / wired / falls back transparently |
| Fallback parity (8 realistic queries, dead LLM vs legacy resolver, byte compared) | identical |

Three defects were caught by the new tests during development and fixed
(positional construction of a pydantic model in the converter; missing
primary-region mirror for region-vs-region comparisons; one test's exception
expectation corrected to the legacy `IntentParseError` surface) — application
code was implicated in the first two, both inside the new package only.

---

## 5. Testing Required (manual test plan — semantic understanding only)

Run with a real provider configured (e.g. local Ollama with `qwen2.5:3b`, or
`FLOATCHAT_LLM_PROVIDER=groq` + key). The intent log line
"Semantic understanding resolved …" confirms the semantic path fired.

1. **Paraphrase battery** — ask the same question 4 ways ("salinity in
   arabian sea 2024" / "how salty was the arabian sea back in 2024" / "salt
   content of arabian sea waters during 2024" / "PSAL profile, arabian sea,
   year 2024") → identical plot/intent log each time.
2. **Synonym understanding** — "o2 near goa", "dissolved oxygen levels", "Oxygen
   concentration" → all ground to DOXY; "chl"/"chlorophyll-a"/"chlorophyl" → CHLA.
3. **Typo tolerance (LLM + deterministic)** — "tembaratre profile of float
   2902403" resolves to TEMP (log shows semantic resolution; converter's
   ontology typo map confirms).
4. **Ontology grounding of new knowledge** — (developer check) append one
   alias to a `parser_synonyms` tuple in `ontology/variables.py`, restart:
   the alias is understood with no other code change (`test_prompt.py`'s
   mutation test is the automated proof).
5. **Ambiguity → ask, don't guess** — "oxygen in the baltic sea" →
   clarification listing known regions, no figure; "plot it" as first message
   in a fresh session → targeted question, not a guess; "show something about
   the ocean" → clarification (or legacy suggestion), never a fabricated
   variable/region/float.
6. **Comparisons** — "compare oxygen between 2902403 and 2903467" →
   comparison_plot with both floats (same result as Sprint-1 Bug-7 behaviour);
   "compare arabian sea vs bay of bengal salinity" → comparison_plot with both
   regions.
7. **Follow-up references (existing capability only)** — after a float profile:
   "what sensors does it carry?" → metadata card for that float; "same but in
   2023" → same scope, new year. (Conversation redesign is Phase 4 — only
   assert what Phase 1-era memory already supported.)
8. **Season/temporal** — "oxygen near goa during monsoon" → month window
   [6,7,8,9] in the intent log; "winter 2023 chlorophyll in bay of bengal" →
   [12,1,2] window.
9. **Fallback drill (feature flag)** — stop the provider (or set
   `FLOATCHAT_SEMANTIC_UNDERSTANDING_ENABLED=false`), repeat items 1–3's well-
   formed versions: results must be exactly the old regex behaviour; check logs
   show "falling back to regex parser".
10. **LLM-failure resilience (flag on, provider up)** — kill Ollama mid-session:
    the next request still answers via regex with no user-visible error, then
    restart and confirm semantic logs resume.
11. **Execution unchanged spot-check** — re-run 3-4 Sprint-1 matrix queries
    (available-plots question, nearest-float map, Arabian Sea count) and
    confirm identical answers/markers to pre-Phase-2 (engine smoke already
    proves the deterministic side byte-for-byte).
12. **No new failure mode in JSON edge cases** — (developer) point the layer at
    a model that returns fenced JSON / chatty wrappers: still answers (fence
    tolerance), and a nonsense output silently falls to regex (log lines only).

**Do not** re-test Planner/QueryEngine/visualization behaviour here — the
engine smoke + OpenAPI evidence covers the frozen execution surface; items
above target semantic understanding only.

---

## 6. Out of Scope (deferred, untouched)

- Phase 3 (planner/query-plan implications of richer understanding),
  Phase 4 (conversation redesign/memory), Phase 5 (rollout/removal of the
  legacy parser+compiler chain).
- Retirement of `LLMIntentCompiler` (still part of the frozen fallback path).
- Any change to ParsedIntent, Planner, QueryEngine, Executors, DuckDB,
  Visualization, Scientific Narration, API contracts.
- Live Nominatim geocoding enablement decisions within the semantic layer
  (the converter reuses the parser's gazetteer function, which honours the
  existing `allow_live_geocoding` gate; default behaviour unchanged).

**Phase 2 is staged (`git add`ed) and awaits your approval. Do not proceed to
Phase 3 until Phase 2 testing is confirmed.**
