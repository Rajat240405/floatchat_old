"""Application configuration using pydantic-settings."""

from pydantic import AliasChoices, ConfigDict, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """FloatChat runtime settings.

    All values can be overridden via environment variables with the prefix
    ``FLOATCHAT_``. For example: ``FLOATCHAT_GDAC_BASE_URL=...``.
    """

    model_config = ConfigDict(
        env_prefix="FLOATCHAT_",
        case_sensitive=False,
    )

    # GDAC / data
    gdac_base_url: str = "https://data-argo.ifremer.fr"
    metadata_index_path: str = "/argo_bio-profile_index.txt.gz"
    metadata_cache_ttl_hours: int = 24
    enable_synthetic_index: bool = False
    # GDAC metadata is optional at application runtime. Keep disabled for the
    # DuckDB/Parquet-backed service; enable explicitly for the legacy remote
    # fallback. Offline ETL loads GDAC metadata directly and is unaffected.
    enable_gdac_runtime: bool = False

    # HTTP
    http_timeout: int = 30
    http_max_retries: int = 3
    http_max_connections: int = 20
    http_max_keepalive: int = 10

    # Query limits
    max_profiles_per_query: int = 5
    deployment_mode: str = "GLOBAL"  # Options: "GLOBAL", "INDIA_ONLY"

    # Conversation memory
    conversation_max_turns: int = 10

    # P3 #2: "currently alive" threshold — a float counts as currently alive if
    # it has >=1 profile in profile_index within the last N months.
    alive_recent_months: int = 12

    # P4 #1: Live geocoding gate. When True (default), the chat pipeline may
    # call Nominatim (OpenStreetMap) for place names not in the local gazetteer.
    # When False, the chat pipeline is FULLY OFFLINE (except startup metadata
    # load) — place resolution is limited to the local gazetteer table + cache.
    allow_live_geocoding: bool = True

    # NetCDF cache
    netcdf_cache_ttl_days: int = 7

    # LLM / Ollama
    llm_enabled: bool = True
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b"
    ollama_timeout: float = 60.0
    ollama_classifier_timeout: float = 10.0

    # Scientific Narrator – LLM-driven explanation (Phase 26+)
    sci_narrator_enabled: bool = True
    sci_narrator_model: str = "qwen2.5:3b"
    sci_narrator_temperature: float = 0.25
    sci_narrator_top_p: float = 0.9
    sci_narrator_timeout: float = 60.0
    sci_narrator_max_retries: int = 0
    sci_narrator_thinking: bool = False  # Qwen3 – disable /no_think for fast narration
    sci_narrator_max_tokens: int = 500
    sci_narrator_max_payload_bytes: int = 4096  # configurable ScientificFacts JSON cap
    sci_narrator_prompt_version: str = "sci_narrator_v2_2026-07"
    sci_narrator_fallback: str = "template"  # template | kb

    # Data Lake (Phase 1 — walking skeleton)
    data_lake_enabled: bool = True  # Master toggle for DuckDB/Parquet path
    data_lake_root: str = ".data_lake/parquet"  # Root of Parquet partitions (Phase 1)
    data_lake_max_profiles: int = 100  # Max profile cycles per lake query

    # Data Lake (Phase 2 — full India-region data lake)
    # Root directory for the complete Phase 2 data lake.
    # On Windows, set to something like: E:\\floatchat_data_lake\\
    # Subdirectories created: raw/{core,bgc}/, parquet/{float_registry,profile_index,levels,region_month_stats}/
    data_lake_dir: str = "E:\\floatchat_data_lake\\"
    # If True, use the Phase 2 data lake for queries (overrides data_lake_root Phase 1 path)
    data_lake_phase2_enabled: bool = True
    # Number of parallel download workers
    data_lake_download_workers: int = 4

    # ── Priority 1A: Remote GDAC fallback control ──
    # When False (default), the live chat pipeline is PHYSICALLY UNABLE to call
    # repository_service.gdac_http, GDACMetadataService index search, or BGCNetCDFReader.
    # Zero rows means "explain no data" — never a silent remote download.
    # When True, allows remote GDAC fallback for backwards compatibility (NOT recommended).
    # Note: repository_service.gdac_http remains available for:
    #   (a) the offline phase2_builder ETL
    #   (b) explicit NetCDF export features
    allow_remote_gdac_fallback: bool = False

    # ── Priority 1B: Query normalizer mode ──
    # When "deterministic" (default), uses FallbackQueryNormalizer only (fast, no LLM).
    # When "llm", uses OllamaQueryNormalizer (slow, 3-12s latency, causes semantic damage).
    # The LLM normalizer is DEPRECATED for hot-path use.
    query_normalizer_mode: str = "deterministic"

    # ── Priority 3: Structured LLM Entity Extractor ──
    # When the deterministic regex parser fails to fill all slots, the system
    # can make ONE call to a small local model to extract structured entities.
    # The LLM returns a validated JSON QuerySpec — never raw SQL or free text.
    # Set to empty string "" to disable LLM extraction entirely.
    extractor_model: str = "qwen2.5:3b"  # P2: 0.5b hallucinated regions/vars; 3b is reliable
    extractor_timeout: float = 10.0  # seconds — generous timeout for small model
    extractor_max_retries: int = 1
    # Minimum confidence (0.0-1.0) from the LLM to accept its extraction.
    # Below this threshold, return a clarification question instead.
    extractor_min_confidence: float = 0.5
    # Temperature for extraction — low for deterministic output
    extractor_temperature: float = 0.1

    # ── P2: LLM provider toggle (extractor + classifier) ──
    # "ollama" (default, offline) | "gemini" (cloud) | "groq" (cloud, fast).
    # This is the A/B switch for diagnosing model-hallucination vs code-design:
    #   FLOATCHAT_LLM_PROVIDER=<provider> routes BOTH the entity extractor and
    #   the 4-way query classifier through that provider using the SAME
    #   prompts/schemas/gating. Default stays "ollama" so the app remains fully
    #   offline-capable unless explicitly flipped.
    llm_provider: str = "ollama"
    # Gemini model used for BOTH extractor and classifier when provider=gemini.
    gemini_model: str = "gemini-2.5-flash"
    # API key. Accepts the conventional GEMINI_API_KEY env var OR the
    # FLOATCHAT_-prefixed form. Read lazily by the factory.
    gemini_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("FLOATCHAT_GEMINI_API_KEY", "GEMINI_API_KEY"),
    )
    # Groq model (OpenAI-compatible API at api.groq.com). Default to
    # OpenAI GPT-OSS-120B as requested for the A/B test; Groq also hosts
    # qwen2.5 / llama-3.3 / mixtral etc. for richer comparison.
    groq_model: str = "openai/gpt-oss-120b"
    # Groq API key (from groq.com console). Accepts GROQ_API_KEY or prefixed form.
    groq_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("FLOATCHAT_GROQ_API_KEY", "GROQ_API_KEY"),
    )

    # Logging
    log_level: str = "INFO"


# Global settings singleton. Override in tests via dependency injection.
settings = Settings()
