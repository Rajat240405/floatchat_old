# FloatChat

> **Architecture:** the authoritative, final architecture contract lives in
> [`../ARCHITECTURE.md`](../ARCHITECTURE.md) (finalized by cleanup Milestones M1–M5).

AI-powered conversational backend for querying live Argo BGC (Biogeochemical) oceanographic data.

## What It Does

FloatChat accepts natural-language questions about Argo float data and returns interactive Plotly visualizations. The backend queries a **local DuckDB/Parquet data lake** of Argo profiles (built offline from the official Ifremer GDAC). Live GDAC queries at runtime are disabled by default (`FLOATCHAT_ALLOW_REMOTE_GDAC_FALLBACK`) — the lake is refreshed by the offline ETL under `src/floatchat/data_lake/`.

**Example:**
```
POST /api/v1/chat
{"message": "show oxygen profile in Arabian Sea for 2024"}
```

**Response:**
```json
{
  "intent": "profile_plot",
  "message": "Retrieved 3 profile(s) with 150 total measurements for variables DOXY.",
  "figure": { /* Plotly JSON */ },
  "data_summary": { "matched_records": 3, ... }
}
```

## Architecture

```
User NL → QueryClassifier (traffic-cop bucket)
              → IntentResolver (regex → optional LLM compiler) → ParsedIntent
              → Retrieval Planner → Query Engine
                                               ↓
        DuckDB/Parquet Data Lake (local; built offline from the Ifremer GDAC)
                                               ↓
        Pandas DataFrame → Visualization Engine → Plotly JSON
              (+ optional Scientific Explanation / Narration)
```

The legacy GDAC-HTTP path (metadata index search, memory-streamed NetCDF via
`netCDF4.Dataset(memory=bytes)`) still exists behind `repository_service/` and
`metadata_service/` for the offline ETL and explicit export tools, but it is
not used for live chat traffic unless `FLOATCHAT_ALLOW_REMOTE_GDAC_FALLBACK`
is enabled.

- **Deterministic backend**: The LLM only converts NL → JSON. All data logic is pure Python.
- **Canonical intent resolution**: deterministic regex parser with an optional structured
  LLM compiler fallback (`intent_resolution/`), behind the `ParsedIntent` contract. The
  legacy individual parsers (`intent_parser/` — Mock, Regex, Ollama) remain available to
  tests and tooling.
- **Local-first data**: chat traffic reads the local lake; `/health` reports `degraded`
  until a populated lake is configured (see Environment Variables below).

## Quick Start

### 1. Install

Requires Python 3.11+.

```bash
cd floatchat
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Configure (optional)

```bash
cp .env.example .env
# then set FLOATCHAT_DATA_LAKE_DIR in .env to your local data-lake root.
```

Without a configured lake the server still starts, but `/health` reports
`degraded` and data queries return "no data" explanations.

### 3. Run Tests

```bash
pytest tests/ -v
```

The suite is self-contained and cwd-independent: it runs identically from this
directory or from the repository root (see `../pytest.ini`), using the small
committed fixture lake under `tests/fixtures/lake_parquet/` — no machine-local
paths or env vars required.

### 4. Start Server

```bash
uvicorn floatchat.api.main:app --reload --port 8000
```

### 5. Query

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"show oxygen profile in arabian sea for 2024"}'
```

## Project Structure

```
floatchat/
├── pyproject.toml
├── README.md
├── ARCHITECTURE.md
├── .env.example          # Documented env template (copy to .env)
├── src/floatchat/
│   ├── config.py
│   ├── exceptions.py
│   ├── logging_config.py
│   ├── api/              # schemas.py, routes/ (thin: chat, floats, health),
│   │                     # services/ (chat_service, floats_service, health_service)
│   ├── models/           # Pydantic cross-module types
│   ├── intent_resolution/# Canonical resolver + llm_compiler.py (single LLM path)
│   ├── intent_parser/    # Legacy individual parsers (Mock, Regex, Ollama)
│   ├── llm_service/      # Query classifier, Ollama client, knowledge base
│   ├── query_normalizer/ # Query cleanup (deterministic by default)
│   ├── conversation/     # Session context memory
│   ├── retrieval_planner/# Operation planner
│   ├── metadata_service/ # GDAC index loader & searcher (ETL / legacy)
│   ├── repository_service/ # NetCDF fetch & cache (ETL / legacy)
│   ├── netcdf_reader/    # BGC variable extractor
│   ├── data_lake/        # DuckDB/Parquet lake + Phase 2 ETL builder
│   ├── visualization_engine/ # Plotly renderers
│   ├── scientific_explanation/ # Scientific narration pipeline
│   ├── variable_registry/# Canonical variable metadata
│   └── query_engine/     # Orchestrator (engine) + dispatch, executors/, helpers, response_builder
├── scripts/              # Maintenance & ETL utilities
└── tests/
    └── fixtures/lake_parquet/  # Small committed sample lake used by tests
```

## Environment Variables

All settings can also be placed in a git-ignored `.env` file — run
`cp .env.example .env` and edit. Values are read via `FLOATCHAT_`-prefixed
environment variables (pydantic-settings).

| Variable | Default | Description |
|---|---|---|
| `FLOATCHAT_DATA_LAKE_DIR` | *(unset)* | Root of the local Phase 2 data lake — machine-specific, set per developer (env or `.env`). No default is shipped. |
| `FLOATCHAT_DATA_LAKE_ROOT` | `.data_lake/parquet` | Phase 1 fallback lake root (relative to the process cwd). Tests override this to the committed fixture lake. |
| `FLOATCHAT_ALLOW_REMOTE_GDAC_FALLBACK` | `false` | Re-enable live GDAC HTTP queries at runtime (legacy; not recommended) |
| `FLOATCHAT_LLM_PROVIDER` | `ollama` | LLM provider for classifier/extractor (`ollama`, `gemini`, `groq`) |
| `FLOATCHAT_GDAC_BASE_URL` | `https://data-argo.ifremer.fr` | GDAC root URL (ETL and legacy runtime fallback) |
| `FLOATCHAT_HTTP_TIMEOUT` | `30` | HTTP request timeout (seconds) |
| `FLOATCHAT_METADATA_CACHE_TTL_HOURS` | `24` | Metadata index cache lifetime |
| `FLOATCHAT_LOG_LEVEL` | `INFO` | Logging level |

## License

MIT
