# FloatChat

AI-powered conversational backend for querying live Argo BGC (Biogeochemical) oceanographic data.

## What It Does

FloatChat accepts natural-language questions about Argo float data and returns interactive Plotly visualizations. The backend queries the official Ifremer GDAC in real time — no local NetCDF cache, no database.

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
User NL → Intent Parser → ParsedIntent → Query Engine
                                               ↓
Metadata Service ←→ GDAC HTTP Index (argo_bio-profile_index.txt.gz)
                                               ↓
Repository Service ←→ GDAC HTTP NetCDF (memory-streamed)
                                               ↓
NetCDF Reader → Pandas DataFrame → Visualization Engine → Plotly JSON
```

- **Deterministic backend**: The LLM only converts NL → JSON. All data logic is pure Python.
- **Swappable parsers**: Mock → Regex → Ollama without changing any downstream code.
- **No disk I/O for NetCDF**: Files are streamed into RAM via `netCDF4.Dataset(memory=bytes)`.

## Quick Start

### 1. Install

Requires Python 3.11+.

```bash
cd floatchat
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Run Tests

```bash
pytest tests/ -v
```

### 3. Start Server

```bash
uvicorn floatchat.api.main:app --reload --port 8000
```

### 4. Query

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
├── src/floatchat/
│   ├── config.py
│   ├── exceptions.py
│   ├── logging_config.py
│   ├── models/           # Pydantic cross-module types
│   ├── intent_parser/    # Mock, Regex, Ollama
│   ├── metadata_service/ # GDAC index loader & searcher
│   ├── repository_service/ # HTTP NetCDF fetcher
│   ├── netcdf_reader/    # BGC variable extractor
│   ├── visualization_engine/ # Plotly renderers
│   ├── query_engine/     # Orchestrator
│   └── api/              # FastAPI app
└── tests/
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `FLOATCHAT_GDAC_BASE_URL` | `https://data-argo.ifremer.fr` | GDAC root URL |
| `FLOATCHAT_HTTP_TIMEOUT` | `30` | HTTP request timeout (seconds) |
| `FLOATCHAT_METADATA_CACHE_TTL_HOURS` | `24` | Metadata index cache lifetime |
| `FLOATCHAT_LOG_LEVEL` | `INFO` | Logging level |

## License

MIT
