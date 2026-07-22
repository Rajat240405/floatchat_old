# FloatChat Architecture

## Overview

FloatChat is a deterministic Python backend that converts natural-language queries about Argo BGC oceanographic data into structured visualizations. The LLM is strictly isolated behind an interface and is only responsible for NL → JSON translation. All data retrieval, processing, and rendering is deterministic.

## Design Principles

1. **Single Responsibility**: Each module has exactly one reason to change.
2. **Interface-Driven**: Modules communicate through abstract interfaces (ABC/Protocol), enabling independent testing and future swaps.
3. **Typed Communication**: All cross-module messages are Pydantic models. No raw dicts or tuples.
4. **No God Classes**: Services are small, focused, and composable.
5. **No Local NetCDF Persistence**: Files are streamed into RAM via HTTP and opened with `netCDF4.Dataset(memory=bytes)`.
6. **No Database**: The official GDAC metadata index is the single source of truth.
7. **Observability**: Every module uses structured logging via `logging.getLogger(__name__)`.

## Project Structure

```
floatchat/
├── pyproject.toml
├── README.md
├── ARCHITECTURE.md
├── src/
│   └── floatchat/
│       ├── __init__.py
│       ├── config.py                 # Pydantic-settings configuration
│       ├── logging_config.py         # Structured logging setup
│       ├── exceptions.py             # Domain exception hierarchy
│       ├── models/
│       │   ├── __init__.py
│       │   ├── intent.py             # ParsedIntent
│       │   ├── metadata.py           # MetadataRecord, SearchCriteria
│       │   ├── data.py               # DataFrame wrapper / validation types
│       │   └── response.py           # ChatResponse, ErrorResponse
│       ├── intent_parser/
│       │   ├── __init__.py
│       │   ├── base.py               # AbstractIntentParser
│       │   ├── mock.py               # MockIntentParser (Phase 1)
│       │   ├── regex.py              # RegexIntentParser (Phase 2)
│       │   └── ollama.py             # OllamaIntentParser (Phase 3)
│       ├── metadata_service/
│       │   ├── __init__.py
│       │   ├── base.py               # AbstractMetadataService
│       │   ├── gdac.py               # GDAC HTTP metadata loader & searcher
│       │   └── regions.py            # Named region → lat/lon bounds
│       ├── repository_service/
│       │   ├── __init__.py
│       │   ├── base.py               # AbstractRepositoryService
│       │   └── gdac_http.py          # HTTP fetcher → netCDF4.Dataset(memory=...)
│       ├── netcdf_reader/
│       │   ├── __init__.py
│       │   ├── base.py               # AbstractNetCDFReader
│       │   └── bgc_reader.py         # Argo BGC profile extraction → DataFrame
│       ├── visualization_engine/
│       │   ├── __init__.py
│       │   ├── base.py               # AbstractVisualizationEngine
│       │   ├── profile.py            # plot_profile()
│       │   └── utils.py              # Shared Plotly layout helpers
│       ├── query_engine/
│       │   ├── __init__.py
│       │   └── engine.py             # Orchestrator: intent → metadata → repo → reader → viz → response
│       └── api/
│           ├── __init__.py
│           ├── main.py               # FastAPI app factory
│           ├── routes.py             # POST /chat
│           └── dependencies.py       # FastAPI dependency injection
└── tests/
    ├── conftest.py                   # Shared fixtures (httpx mock, sample NetCDF in memory)
    ├── test_intent_parser/
    ├── test_metadata_service/
    ├── test_repository_service/
    ├── test_netcdf_reader/
    ├── test_visualization_engine/
    ├── test_query_engine/
    └── test_api/
```

## Module Responsibilities

### 1. Intent Parser

- **Input**: Natural language string (`message: str`)
- **Output**: `ParsedIntent` Pydantic model
- **Contract**: The backend never knows which parser produced the intent.
- **Implementations**: Mock → Regex → Ollama (swappable without backend changes)

### 2. Metadata Service

- **Responsibilities**:
  - Download `argo_bio-profile_index.txt.gz` if missing or stale.
  - Decompress and load into `pandas.DataFrame` kept in RAM.
  - Accept `SearchCriteria` and return matching `List[MetadataRecord]`.
  - Resolve named regions to lat/lon bounds.
- **No other module knows the index file format or column names.**

### 3. Repository Service

- **Responsibilities**:
  - Receive a `relative_path: str` (from `MetadataRecord.file`).
  - Construct GDAC URL: `{base_url}/dac/{relative_path}`.
  - Perform HTTP GET with `httpx`.
  - Return `netCDF4.Dataset(memory=response.content)`.
  - Handle timeouts, retries, and HTTP errors.
- **No other module knows the GDAC URL pattern or HTTP details.**

### 4. NetCDF Reader

- **Responsibilities**:
  - Receive an open `netCDF4.Dataset`.
  - Inspect variables dynamically. Never assume existence.
  - Extract requested BGC variables + `PRES` (pressure/depth proxy) + QC flags.
  - Return a tidy `pandas.DataFrame`.
  - Close the Dataset when done.
- **Column convention**: `N_PROF`, `N_LEVELS`, `PRES`, `{VAR}`, `{VAR}_QC`, `{VAR}_ADJUSTED`, `{VAR}_ADJUSTED_QC`.

### 5. Visualization Engine

- **Responsibilities**:
  - Receive a DataFrame and a `ParsedIntent`.
  - Select graph type based **only** on `intent` field.
  - Return a Plotly JSON figure dict.
  - Never call the LLM. Never touch NetCDF.
- **Initial scope**: `plot_profile()` only.

### 6. Query Engine

- **Responsibilities**:
  - Orchestrate the pipeline.
  - Map `ParsedIntent` → `SearchCriteria`.
  - Fetch metadata, select top-N profiles, fetch NetCDFs, read, visualize.
  - Handle errors at each stage and wrap them into `ChatResponse`.
  - Manage resource cleanup (close NetCDF datasets).

### 7. API Layer

- **Responsibilities**:
  - FastAPI application.
  - `POST /chat` → `{"message": "..."}` → `ChatResponse`.
  - Inject dependencies (parser, metadata service, etc.) via FastAPI dependency overrides.
  - Convert domain exceptions to HTTP status codes.

## Data Models

### ParsedIntent

```python
class ParsedIntent(BaseModel):
    intent: Literal["profile_plot", "time_series", "comparison_plot", "trajectory", "unknown"]
    region: Optional[str] = None
    variables: List[str] = Field(default_factory=list)
    year: Optional[int] = None
    month: Optional[int] = None
    day: Optional[int] = None
    lat_min: Optional[float] = Field(None, ge=-90, le=90)
    lat_max: Optional[float] = Field(None, ge=-90, le=90)
    lon_min: Optional[float] = Field(None, ge=-180, le=180)
    lon_max: Optional[float] = Field(None, ge=-180, le=180)
    depth_min: Optional[float] = None
    depth_max: Optional[float] = None
    float_id: Optional[str] = None  # WMO ID
    cycle_number: Optional[int] = None
    limit: int = Field(default=5, ge=1, le=20)
```

### MetadataRecord

```python
class MetadataRecord(BaseModel):
    file: str
    date: datetime
    latitude: float
    longitude: float
    ocean: str
    profiler_type: str
    institution: str
    parameters: str
    parameter_data_mode: str
    date_update: datetime
```

### SearchCriteria

```python
class SearchCriteria(BaseModel):
    lat_min: Optional[float] = None
    lat_max: Optional[float] = None
    lon_min: Optional[float] = None
    lon_max: Optional[float] = None
    year: Optional[int] = None
    month: Optional[int] = None
    day: Optional[int] = None
    parameters: List[str] = Field(default_factory=list)
    float_id: Optional[str] = None
    limit: int = Field(default=5, ge=1, le=20)
```

## Error Handling

All domain exceptions inherit from `FloatChatError`. The API layer catches these and maps them:

- `IntentParseError` → 400 Bad Request
- `MetadataError` → 503 Service Unavailable
- `RepositoryError` → 502 Bad Gateway
- `NetCDFReadError` → 500 Internal Server Error
- `VisualizationError` → 500 Internal Server Error

## Memory & Performance

- **Metadata**: ~350k rows × 10 columns ≈ 30–50 MB in Pandas. Loaded once at startup and kept in RAM.
- **NetCDF**: Streamed via HTTP into `bytes`, opened in-memory, extracted to DataFrame, then Dataset is closed and bytes are garbage-collected. No disk I/O.
- **Visualization**: Plotly JSON figures are returned; no image rendering on the server.

## Testing Strategy

- **Unit tests** for every module using interface mocks.
- **NetCDF tests** use in-memory datasets created with `netCDF4.Dataset(memory=...)` so no external files are needed.
- **HTTP tests** use `httpx` transport mocking or `respx`.
- **API tests** use FastAPI `TestClient` with dependency overrides.

## Review Checklist

- [X] Every module has one responsibility.
- [X] Every module has an abstract interface.
- [X] Cross-module communication uses Pydantic models.
- [X] No database dependencies.
- [X] No local NetCDF caching.
- [X] LLM is fully decoupled.
- [X] Logging is configured per module.
- [X] Error hierarchy is domain-specific.
- [X] FastAPI dependencies are injectable for testing.
