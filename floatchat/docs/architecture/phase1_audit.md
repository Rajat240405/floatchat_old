# Phase 1 — Architecture Audit & Baseline

**Status:** Complete. No code changes made. This document is the audit only.

---

## 1. Complete Decision Flow (where every routing choice is made)

```
User message arrives at POST /api/v1/chat
  │
  ├─ [DECISION 1] CLASSIFIER (classifier.py:228)
  │   classify() checks in order:
  │   1. _is_small_talk() → greetings, thanks, help
  │   2. _is_out_of_domain() → sports, politics, coding, cooking
  │   3. _is_knowledge_query() → "what is argo", "bgc", "parking depth"
  │   4. If llm_enabled: LLM fallback → DATA/SMALL/OOD/KNOWLEDGE
  │   5. Default: DATA_QUERY
  │
  ├─ [DECISION 2] CONVERSATIONAL OVERRIDE (routes.py:720)
  │   If classified as KNOWLEDGE/GENERAL/OOD:
  │   Check _is_conversational_follow_up() → if yes, override to DATA_QUERY
  │   (catches "what about 2022?" after a data discussion)
  │
  ├─ [DECISION 3] BUCKET DISPATCH (routes.py:731-800)
  │   SMALL_TALK → hardcoded greeting (return immediately)
  │   OUT_OF_DOMAIN → hardcoded bouncer (return immediately)
  │   GENERAL_QUERY → legacy LLM answer (return immediately)
  │   KNOWLEDGE_QUERY → KB search + LLM answer (return immediately)
  │   DATA_QUERY → continues to parser
  │
  ├─ [DECISION 4] REGEX INTENT DETECTION (regex.py:520, _detect_intent)
  │   Priority chain (first match wins):
  │   1. metadata keywords (sensors, battery, status) → metadata_lookup
  │   2. hovmoller keywords → hovmoller
  │   3. ts_diagram keywords → ts_diagram
  │   4. comparison keywords → comparison_plot
  │   5. time_series keywords → time_series
  │   6. trajectory keywords → trajectory
  │   7. nearest/closest → nearest_float
  │   8. radius (within Xkm, near + coords + "floats") → radius_search
  │   9. count keywords → count_aggregate
  │   10. region + no profile verb → region_search
  │   11. profile verb (show/plot) → profile_plot
  │   12. DEFAULT FALLBACK → profile_plot
  │
  ├─ [DECISION 5] ROUTING OVERRIDE (regex.py:369)
  │   if intent == "radius_search" and variables present:
  │   → override to profile_plot
  │   (converts "temperature near Goa" from float discovery to measurement)
  │
  ├─ [DECISION 6] PARSE ERROR HANDLING (routes.py:817-860)
  │   If regex parse raises IntentParseError:
  │   6a. _try_conversational_recovery() → reference phrase + context inheritance
  │   6b. _try_llm_extraction_as_recovery() → LLM last resort (temporal + spatial only)
  │   6c. If all fail → return "unknown" intent with suggestions
  │
  ├─ [DECISION 7] LLM ENTITY EXTRACTION (routes.py:307, _try_llm_extraction)
  │   Fires when "critical slots" are missing:
  │   - has_vars AND (has_region OR has_coords OR has_float) AND has_year → SKIP
  │   - Otherwise → ONE LLM call (temporal + action resolution only)
  │   - LLM output for variables/float_id/depth/operational → IGNORED
  │   - LLM output for time_filter → accepted (temporal resolution)
  │   - LLM output for spatial_filter → accepted only when no coords exist
  │
  ├─ [DECISION 8] CONVERSATION CONTEXT MERGE (memory.py:51, merge_context)
  │   Requires explicit reference phrase in the message:
  │   - No reference phrase → NO inheritance (return unchanged)
  │   - "same region" → inherit region only
  │   - "that float" → inherit float_id only
  │   - "same variable" → inherit variables only
  │   - "same" / "what about" → inherit ALL fields
  │   - Compound ("same region but in 2024") → inherit region + variables
  │   - Metadata followup ("sensors?", "battery?") → inherit float_id only
  │
  ├─ [DECISION 9] CLARIFICATION CHECK (routes.py:61, _check_critical_fields)
  │   Intent-specific: asks user if essential fields missing
  │   - profile_plot without variable → "Which variable?"
  │   - radius_search without location → "Which location?"
  │   - metadata_lookup without float → "Which float?"
  │   - Nothing extracted → general guidance
  │   - Has conversation context → skip (inherit instead)
  │
  └─ [DECISION 10] ENGINE EXECUTION ROUTING (engine.py:234)
      Switch on intent.intent:
      - nearest_float → _execute_nearest_float
      - radius_search → _execute_radius_search
      - metadata_lookup → _execute_metadata_lookup
      - count_aggregate → _execute_count_aggregate
      - trajectory → _execute_trajectory
      - everything else → _execute_data_query_via_lake
        (profile_plot, region_search, time_series, hovmoller, ts_diagram, comparison)
```

---

## 2. Places Where a Query Is Forced Into a Single Intent

| # | Location | Code | What it forces | Problem |
|---|----------|------|---------------|---------|
| 1 | `regex.py:369` | `if intent == "radius_search" and variables: intent = "profile_plot"` | Variables + spatial → always profile_plot | "Find floats measuring oxygen" becomes profile_plot (wrong — user wants discovery) |
| 2 | `regex.py:533` | `if _INTENT_METADATA.search(text): return "metadata_lookup"` | Metadata keyword → always metadata_lookup | "sensors on all BGC floats near Goa" → metadata_lookup (ignores spatial scope) |
| 3 | `regex.py:547` | `if _INTENT_RADIUS.search(text) or radius_km or (...)` | "within Xkm" or "near" → radius_search | Even when the query is about plotting data, "within 500km" forces discovery |
| 4 | `regex.py:556-557` | `return "profile_plot"` (default fallback) | Unknown intent → profile_plot | Ambiguous queries get plotting behavior by default |
| 5 | `classifier.py:195` | `if "argo" in text and not data_force and len(text.split()) <= 12: return True` | Short query with "argo" → KNOWLEDGE_QUERY | "Show all Argo floats near India" (6 words) → misclassified as knowledge |
| 6 | `classifier.py:102` | `_DATA_FORCING_REGEXES` | Hardcoded patterns for data detection | "India" not in region list; "floats" not a forcing pattern by itself |
| 7 | `routes.py:765` | `if query_type == "GENERAL_QUERY":` | Legacy alias → direct LLM answer | Dead path from old tests; no longer used in production |

---

## 3. Dependencies Between Components

```
Classifier ────── determines ───→ which bucket (DATA/KNOWLEDGE/OOD/SMALL_TALK)
     │
     ↓ (only if DATA_QUERY)
Regex Parser ──── determines ───→ single intent (profile_plot, radius_search, etc.)
     │                              + extracts: variables, region, float_id, coords,
     │                                         depth, operational_filter, seasons
     │
     ↓
LLM Extractor ─── resolves ─────→ temporal only (action + time_filter)
     │                              (variables/float_id/depth/operational → IGNORED)
     │
     ↓
Conversation Merge ─ inherits ──→ fields from previous turn
     │                              (gated by reference phrases)
     │
     ↓
Clarification Check ── asks ───→ user if critical fields missing
     │
     ↓
Query Engine ──── executes ────→ DuckDB query + visualization + narration
                                    (one execution path per intent)
```

**Key dependency chains:**
- Classifier → Regex Parser: classifier determines IF data parsing happens at all. If misclassified, parser never runs.
- Regex → LLM Extractor: extractor only fires if regex leaves slots empty. If regex finds everything, no LLM call.
- Regex → Conversation Merge: merge inherits fields, but ONLY for fields the reference phrase explicitly targets.
- Clarification → Engine: clarification can short-circuit before execution if fields are missing.

**Circular dependency risk:**
- `_is_conversational_follow_up()` in regex.py is called from routes.py AFTER classification. If the classifier routes to KNOWLEDGE but the message has a follow-up pattern, it's overridden to DATA. This creates a path where classification is partially overridden.

---

## 4. Component-by-Component Assessment

### 4.1 Classifier (`classifier.py`)
- **Type:** Rule-based regex (deterministic). LLM fallback disabled (`llm_enabled=False`).
- **Strengths:** Fast (0ms), handles greetings, clear OOD, and explicit knowledge questions well.
- **Weaknesses:**
  - "argo" keyword + short text → false KNOWLEDGE_QUERY (Decision 5 above)
  - `_DATA_FORCING_REGEXES` has a fixed region list — "India" missing
  - No semantic understanding — can't distinguish "what is Argo" from "show Argo floats"
- **LLM fallback exists but disabled:** `classify()` lines 248-266 — would call LLM if `llm_enabled=True`.

### 4.2 Regex Parser (`regex.py`)
- **Type:** Deterministic regex pattern matching.
- **Strengths:** Handles standard patterns ("temperature in Arabian Sea 2024"), fast, no hallucination.
- **Weaknesses:**
  - Priority chain in `_detect_intent` is rigid — first match wins, no disambiguation
  - Routing override (`radius_search → profile_plot`) is too aggressive
  - Can't handle compound queries ("find floats AND plot oxygen")
  - Gazetteer is a flat lookup — no semantic place understanding
  - Fallback to `profile_plot` for anything unrecognized

### 4.3 LLM Entity Extractor (`extractor.py`)
- **Type:** LLM-based, restricted to temporal + action resolution.
- **Strengths:** Good temporal resolution ("last monsoon" → date range), restricted fields prevent hallucination.
- **Weaknesses:**
  - Only resolves temporal — can't help with intent disambiguation
  - Fires whenever `year` is missing (most queries lack explicit years)
  - Recovery path (`_try_llm_extraction_as_recovery`) only accepts spatial + temporal

### 4.4 Conversation Memory (`memory.py`)
- **Type:** In-memory, session-scoped, reference-phrase-gated.
- **Strengths:** Safe — won't inherit stale fields without explicit reference. Handles "same region", "that float", "there", "what about".
- **Weaknesses:**
  - Can't inherit partial context ("latest float" doesn't inherit variable from "show chlorophyll")
  - Reference phrase detection is keyword-based, not semantic
  - Max 10 turns — no long-term memory

### 4.5 Query Engine (`engine.py`)
- **Type:** Switch-case on intent, each branch executes a specific DuckDB query.
- **Strengths:** Deterministic SQL, no LLM in data path, good zero-result explanations.
- **Weaknesses:**
  - One intent = one execution path — can't combine discovery + plotting
  - `get_map_markers` runs a SEPARATE query from data (causes map/graph mismatch)
  - Profile LIMIT (100) can exclude floats from multi-float queries
  - No streaming — entire response built before returning

---

## 5. Benchmark Query Results (Current Behavior)

| # | Query | Classifier | Intent | Result | Issue |
|---|-------|-----------|--------|--------|-------|
| 1 | temperature in Arabian Sea 2024 | DATA_QUERY | region_search | ✅ Correct data + figure | None |
| 2 | salinity in Bay of Bengal | DATA_QUERY | region_search | ✅ Correct (LLM fires for year) | LLM call adds ~0.5s |
| 3 | trajectory of float 2902403 | DATA_QUERY | trajectory | ✅ Map path | None |
| 4 | what sensors does float 2902403 have | KNOWLEDGE→DATA override | metadata_lookup | ✅ Metadata card | None |
| 5 | floats near Sri Lanka | DATA_QUERY | radius_search | ✅ Float list | None |
| 6 | oxygen in Arabian Sea 2024 | DATA_QUERY | region_search | ✅ Data + figure | None |
| 7 | chlorophyll in Bay of Bengal | DATA_QUERY | region_search | ✅ Data + figure | None |
| 8 | Show me floats that were alive near Goa around the last monsoon | DATA_QUERY | radius_search | ✅ Float list + alive filter | Place name "goa" extracted correctly |
| 9 | floats alive near Goa last summer | DATA_QUERY | radius_search | ✅ Float list | None |
| 10 | deep oxygen in Bay of Bengal | DATA_QUERY | region_search | ✅ Data + depth filter | None |
| 11 | temperature in Arabian Sea during monsoon | DATA_QUERY | region_search | ✅ JJAS window | None |
| 12 | Show all Argo floats near India | **KNOWLEDGE_QUERY** | KB answer | ❌ Wrong — should be DATA | "argo" + short → knowledge |
| 13 | Find all active BGC floats within 500km of Goa, measuring oxygen | DATA_QUERY | **profile_plot** | ❌ Wrong — should be radius_search | Routing override: variables → profile_plot |
| 14 | Plot temperature for float 2901623 | DATA_QUERY | profile_plot | ✅ Figure | Map shows 1344 markers (should show 1) |
| 15 | Show oxygen profiles in the Arabian Sea | DATA_QUERY | profile_plot | ✅ Figure + narration | Narrator takes 29s (Ollama qwen2.5:7b) |

---

## 6. Identified Failure Patterns (classes, not individual queries)

| Pattern | Example | Root cause | Affected phase |
|---------|---------|-----------|---------------|
| Discovery vs measurement confusion | "find floats measuring oxygen" | Routing override forces profile_plot when variables present | Phase 3 |
| Knowledge vs data confusion | "show Argo floats near India" | "argo" keyword → knowledge, no data_force match | Phase 4 |
| Map/data mismatch | Single-float query shows 1344 markers | `get_map_markers` separate query, doesn't respect all filters | Phase 3 |
| Single-intent limitation | "explain thermocline and plot one" | Parser produces one intent, engine executes one path | Phase 5 |
| Conversational gaps | "latest float" (after "chlorophyll in BoB") | Reference phrase detection can't inherit variable + change operation | Phase 7 |
| Rigid intent priority | "sensors on all BGC floats near Goa" | Metadata keyword wins over spatial scope | Phase 2 |

---

## 7. Baseline Test Results

```
TOTAL: 687 passed, 0 failed
```

All 687 existing tests pass. No regressions. The audit is complete and no code was changed.

---

## 8. Recommendations for Phase 2 Readiness

The audit identifies **6 decision points** that force single-intent behavior. The planner layer (Phase 2) should sit between the classifier and the regex parser, converting the user's query into a sequence of operations rather than a single intent. The regex parser's extraction logic (variables, regions, float IDs, etc.) remains valuable as an entity extractor for the planner — only the `_detect_intent` priority chain and the routing override need to be replaced.

---

*End of Phase 1 audit. No code was modified. Proceed to Phase 2 only after reviewing this document.*
