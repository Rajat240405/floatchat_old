"""FastAPI dependency injection.

All heavy dependencies are constructed lazily and cached so they can be
overridden easily in tests via ``app.dependency_overrides``.

Priority 1B: Query normalizer uses FallbackQueryNormalizer (deterministic)
by default. OllamaQueryNormalizer is DEPRECATED for hot-path use.
"""

from pathlib import Path
from typing import Annotated

from fastapi import Depends

from floatchat.config import settings
from floatchat.conversation.base import AbstractConversationManager
from floatchat.data_lake.base import AbstractDataLake
from floatchat.data_lake.duckdb_lake import DuckDBDataLake
from floatchat.conversation.memory import InMemoryConversationManager
from floatchat.entity_extractor.extractor import LLMIntentCompiler
from floatchat.intent_resolution.resolver import IntentResolver
from floatchat.intent_parser.base import AbstractIntentParser
from floatchat.intent_parser.regex import RegexIntentParser
from floatchat.llm_service.base import AbstractLLMService
from floatchat.llm_service.classifier import QueryClassifier
from floatchat.llm_service.ollama import OllamaLLMService
from floatchat.metadata_service.base import AbstractMetadataService
from floatchat.metadata_service.gdac import GDACMetadataService
from floatchat.netcdf_reader.base import AbstractNetCDFReader
from floatchat.netcdf_reader.bgc_reader import BGCNetCDFReader
from floatchat.query_engine.engine import QueryEngine
from floatchat.query_normalizer.base import AbstractQueryNormalizer
from floatchat.query_normalizer.fallback import FallbackQueryNormalizer
from floatchat.repository_service.base import AbstractRepositoryService
from floatchat.repository_service.gdac_http import GDACRepositoryService
from floatchat.scientific_explanation.engine import ScientificExplanationEngine
from floatchat.scientific_explanation.features import ScientificFeatureExtractor
from floatchat.scientific_explanation.narrator import ScientificNarrator
from floatchat.scientific_explanation.output_parser import NarratorOutputParser
from floatchat.scientific_explanation.prompt_builder import PromptBuilder
from floatchat.scientific_explanation.verification_guard import VerificationGuard
from floatchat.visualization_engine.base import AbstractVisualizationEngine
from floatchat.visualization_engine.profile import ProfileVisualizationEngine

# Singleton caches (module-level for simplicity in MVP).
_metadata_service: GDACMetadataService | None = None
_data_lake: AbstractDataLake | None = None
_repository_service: GDACRepositoryService | None = None
_netcdf_reader: BGCNetCDFReader | None = None
_viz_engine: ProfileVisualizationEngine | None = None
_intent_parser: RegexIntentParser | None = None
_intent_resolver: IntentResolver | None = None
_query_engine: QueryEngine | None = None
_llm_service: OllamaLLMService | None = None
_extractor_llm_service: OllamaLLMService | None = None  # P2: provider-toggled extractor LLM
_query_classifier: QueryClassifier | None = None
_conversation_manager: InMemoryConversationManager | None = None
_query_normalizer: AbstractQueryNormalizer | None = None
_scientific_llm_service: OllamaLLMService | None = None
_scientific_narrator: ScientificNarrator | None = None
_scientific_feature_extractor: ScientificFeatureExtractor | None = None
_scientific_prompt_builder: PromptBuilder | None = None
_narrator_output_parser: NarratorOutputParser | None = None
_verification_guard: VerificationGuard | None = None
_scientific_explanation_engine: ScientificExplanationEngine | None = None
_knowledge_base: object | None = None  # KnowledgeBase singleton (Phase 6)


def get_metadata_service() -> AbstractMetadataService:
    global _metadata_service
    if _metadata_service is None:
        _metadata_service = GDACMetadataService()
    return _metadata_service


def get_data_lake() -> AbstractDataLake:
    """Return the process-local DuckDB/Parquet service singleton."""
    global _data_lake
    if _data_lake is None:
        if settings.data_lake_phase2_enabled:
            phase2_root = Path(settings.data_lake_dir)
            levels_root = phase2_root / "parquet" / "levels"
            if levels_root.exists() and any(levels_root.rglob("*.parquet")):
                _data_lake = DuckDBDataLake(phase2_root=phase2_root, use_phase2=True)
        if _data_lake is None:
            _data_lake = DuckDBDataLake(lake_root=Path(settings.data_lake_root))
        # Warm the startup thread's reusable connection. Worker threads get
        # their own thread-affine connection on first use.
        if hasattr(_data_lake, "_get_connection"):
            _data_lake._get_connection()
    return _data_lake


def get_repository_service() -> AbstractRepositoryService:
    global _repository_service
    if _repository_service is None:
        _repository_service = GDACRepositoryService()
    return _repository_service


def get_netcdf_reader() -> AbstractNetCDFReader:
    global _netcdf_reader
    if _netcdf_reader is None:
        _netcdf_reader = BGCNetCDFReader()
    return _netcdf_reader


def get_visualization_engine() -> AbstractVisualizationEngine:
    global _viz_engine
    if _viz_engine is None:
        _viz_engine = ProfileVisualizationEngine()
    return _viz_engine


def get_query_normalizer() -> AbstractQueryNormalizer:
    """Priority 1B: Use deterministic normalizer by default.

    The OllamaQueryNormalizer (qwen2.5:7b) is DEPRECATED for hot-path use.
    It adds 3-12s latency and causes semantic damage.
    To re-enable (NOT recommended): set FLOATCHAT_QUERY_NORMALIZER_MODE=llm
    """
    global _query_normalizer

    if _query_normalizer is None:
        if settings.query_normalizer_mode == "llm":
            # DEPRECATED: LLM normalizer causes 3-12s latency and semantic damage
            import warnings
            warnings.warn(
                "OllamaQueryNormalizer is DEPRECATED for hot-path use. "
                "It adds 3-12s latency and can cause semantic damage. "
                "Use FLOATCHAT_QUERY_NORMALIZER_MODE=deterministic instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            from floatchat.query_normalizer.ollama import OllamaQueryNormalizer
            _query_normalizer = OllamaQueryNormalizer()
        else:
            # Default: Fast deterministic normalizer (no LLM, no latency)
            _query_normalizer = FallbackQueryNormalizer()

    return _query_normalizer


def get_intent_parser(
    normalizer: Annotated[
        AbstractQueryNormalizer,
        Depends(get_query_normalizer),
    ],
) -> AbstractIntentParser:
    global _intent_parser
    if _intent_parser is None:
        _intent_parser = RegexIntentParser(
            normalizer=normalizer if settings.query_normalizer_mode == "llm" else None
        )
    return _intent_parser


def get_scientific_llm_service() -> AbstractLLMService:
    """Return the provider used for scientific narration.

    Follows the FLOATCHAT_LLM_PROVIDER toggle (same as extractor + classifier).
    Previously hardcoded to Ollama only. Now routes through the factory so
    Groq/Gemini can be used for narration (0.5s vs 37s with local qwen2.5:7b).

    The VerificationGuard is NOT modified — it still checks every number
    against ScientificFacts regardless of which LLM produced the text.
    """
    global _scientific_llm_service
    if _scientific_llm_service is None:
        from floatchat.llm_service.factory import build_llm_service
        _scientific_llm_service = build_llm_service(
            json_mode=True,
            model=settings.sci_narrator_model,
            timeout=settings.sci_narrator_timeout,
            temperature=settings.sci_narrator_temperature,
            top_p=settings.sci_narrator_top_p,
            max_tokens=settings.sci_narrator_max_tokens,
        )
    return _scientific_llm_service


def get_scientific_narrator(
    llm: Annotated[AbstractLLMService, Depends(get_scientific_llm_service)],
) -> ScientificNarrator:
    global _scientific_narrator
    if _scientific_narrator is None:
        _scientific_narrator = ScientificNarrator(
            llm,
            max_retries=settings.sci_narrator_max_retries,
        )
    return _scientific_narrator


def get_scientific_feature_extractor() -> ScientificFeatureExtractor:
    global _scientific_feature_extractor
    if _scientific_feature_extractor is None:
        _scientific_feature_extractor = ScientificFeatureExtractor(use_legacy=True)
    return _scientific_feature_extractor


def get_scientific_prompt_builder() -> PromptBuilder:
    global _scientific_prompt_builder
    if _scientific_prompt_builder is None:
        _scientific_prompt_builder = PromptBuilder(
            max_payload_bytes=settings.sci_narrator_max_payload_bytes,
            prompt_version=settings.sci_narrator_prompt_version,
        )
    return _scientific_prompt_builder


def get_narrator_output_parser() -> NarratorOutputParser:
    global _narrator_output_parser
    if _narrator_output_parser is None:
        _narrator_output_parser = NarratorOutputParser()
    return _narrator_output_parser


def get_verification_guard() -> VerificationGuard:
    global _verification_guard
    if _verification_guard is None:
        _verification_guard = VerificationGuard()
    return _verification_guard


def get_scientific_explanation_engine(
    feature_extractor: Annotated[
        ScientificFeatureExtractor,
        Depends(get_scientific_feature_extractor),
    ],
    prompt_builder: Annotated[PromptBuilder, Depends(get_scientific_prompt_builder)],
    narrator: Annotated[ScientificNarrator, Depends(get_scientific_narrator)],
    output_parser: Annotated[NarratorOutputParser, Depends(get_narrator_output_parser)],
    verification_guard: Annotated[VerificationGuard, Depends(get_verification_guard)],
) -> ScientificExplanationEngine:
    global _scientific_explanation_engine
    if _scientific_explanation_engine is None:
        _scientific_explanation_engine = ScientificExplanationEngine(
            feature_extractor=feature_extractor,
            prompt_builder=prompt_builder,
            narrator=narrator,
            output_parser=output_parser,
            verification_guard=verification_guard,
        )
    return _scientific_explanation_engine


def get_query_engine(
    metadata: Annotated[AbstractMetadataService, Depends(get_metadata_service)],
    repository: Annotated[AbstractRepositoryService, Depends(get_repository_service)],
    reader: Annotated[AbstractNetCDFReader, Depends(get_netcdf_reader)],
    viz: Annotated[AbstractVisualizationEngine, Depends(get_visualization_engine)],
    explanation_engine: Annotated[
        ScientificExplanationEngine,
        Depends(get_scientific_explanation_engine),
    ],
    data_lake: AbstractDataLake = Depends(get_data_lake),
) -> QueryEngine:
    global _query_engine
    if not hasattr(data_lake, "query"):
        data_lake = get_data_lake()
    if _query_engine is None:
        _query_engine = QueryEngine(
            metadata,
            repository,
            reader,
            viz,
            explanation_engine=explanation_engine,
            data_lake=data_lake,
        )
    return _query_engine


def initialize_runtime_services() -> None:
    """Construct the long-lived application runtime graph once at startup."""
    explanation_engine = get_scientific_explanation_engine(
        get_scientific_feature_extractor(),
        get_scientific_prompt_builder(),
        get_scientific_narrator(get_scientific_llm_service()),
        get_narrator_output_parser(),
        get_verification_guard(),
    )
    get_query_engine(
        get_metadata_service(),
        get_repository_service(),
        get_netcdf_reader(),
        get_visualization_engine(),
        explanation_engine,
        get_data_lake(),
    )


def get_runtime_query_engine() -> QueryEngine:
    """Return the startup-initialized QueryEngine for deterministic routes."""
    global _query_engine
    if _query_engine is None:
        initialize_runtime_services()
    return _query_engine


def get_llm_service() -> AbstractLLMService:
    """Return the general LLM service (classifier + narration fallback).

    P2: honours ``settings.llm_provider`` so the query classifier can be A/B
    tested against Gemini. Default remains Ollama (offline).
    """
    global _llm_service
    if _llm_service is None:
        from floatchat.llm_service.factory import build_llm_service
        _llm_service = build_llm_service(json_mode=False)
    return _llm_service


def get_extractor_llm_service() -> AbstractLLMService:
    """Return the LLM service used by the Priority-3 entity extractor.

    P2: honours ``settings.llm_provider`` (Ollama by default, Gemini when
    ``FLOATCHAT_LLM_PROVIDER=gemini`` + ``GEMINI_API_KEY`` is set).
    """
    global _extractor_llm_service
    if _extractor_llm_service is None:
        from floatchat.llm_service.factory import build_extractor_llm_service
        _extractor_llm_service = build_extractor_llm_service()
    return _extractor_llm_service



def get_query_classifier(
    llm: Annotated[AbstractLLMService, Depends(get_llm_service)],
) -> QueryClassifier:
    global _query_classifier
    if _query_classifier is None:
        _query_classifier = QueryClassifier(llm)
    return _query_classifier


def get_conversation_manager() -> AbstractConversationManager:
    global _conversation_manager
    if _conversation_manager is None:
        _conversation_manager = InMemoryConversationManager()
    return _conversation_manager


def get_intent_resolver(
    parser: Annotated[AbstractIntentParser, Depends(get_intent_parser)],
    conversation_manager: Annotated[
        AbstractConversationManager, Depends(get_conversation_manager)
    ],
) -> IntentResolver:
    global _intent_resolver
    if _intent_resolver is None:
        _intent_resolver = IntentResolver(
            parser=parser,
            compiler=LLMIntentCompiler(),
            conversation_manager=conversation_manager,
        )
    return _intent_resolver



def get_knowledge_base():
    """Return vetted Argo Knowledge Base singleton (Phase 6)."""
    global _knowledge_base
    if _knowledge_base is None:
        from floatchat.llm_service.knowledge_base import KnowledgeBase
        _knowledge_base = KnowledgeBase()
    return _knowledge_base
