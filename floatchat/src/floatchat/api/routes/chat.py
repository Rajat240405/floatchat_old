"""Chat routes — POST /chat (HTTP wiring only).

Cleanup M3 (API layer decomposition): this module only binds the HTTP
contract to the application service. All classification, traffic-cop
routing, and response construction live in
``floatchat.api.services.chat_service``.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from floatchat.api.dependencies import (
    get_conversation_intelligence,
    get_conversation_manager,
    get_intent_parser,
    get_intent_resolver,
    get_knowledge_base,
    get_llm_service,
    get_query_classifier,
    get_query_engine,
    get_scientific_response_layer,
)
from floatchat.api.schemas import ChatRequest
from floatchat.api.services.chat_service import handle_chat
from floatchat.conversation.base import AbstractConversationManager
from floatchat.intent_parser.base import AbstractIntentParser
from floatchat.llm_service.base import AbstractLLMService
from floatchat.llm_service.classifier import QueryClassifier
from floatchat.llm_service.knowledge_base import KnowledgeBase
from floatchat.models import ChatResponse
from floatchat.query_engine.engine import QueryEngine

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    classifier: Annotated[QueryClassifier, Depends(get_query_classifier)],
    llm_service: Annotated[AbstractLLMService, Depends(get_llm_service)],
    intent_parser: Annotated[AbstractIntentParser, Depends(get_intent_parser)],
    intent_resolver: Annotated[object, Depends(get_intent_resolver)],
    query_engine: Annotated[QueryEngine, Depends(get_query_engine)],
    conversation_manager: Annotated[
        AbstractConversationManager, Depends(get_conversation_manager)
    ],
    knowledge_base: Annotated[KnowledgeBase, Depends(get_knowledge_base)],
    conversation_intelligence: Annotated[
        object, Depends(get_conversation_intelligence)
    ],
    response_layer: Annotated[object, Depends(get_scientific_response_layer)],
) -> ChatResponse:
    """Convert a natural-language message into a data visualization or answer.

    Flow (Phase 6 Traffic Cop):
        1. Classify into 4 buckets via QueryClassifier (rule-based + LLM)
        2. SMALL_TALK      → hardcoded greeting (no LLM)
        3. OUT_OF_DOMAIN   → hardcoded polite bouncer (no LLM)
        4. KNOWLEDGE_QUERY → KB search + strict LLM prompt (or raw KB if LLM disabled)
        5. DATA_QUERY      → intent parser → merge context → query engine → viz
    """
    return handle_chat(
        request,
        classifier,
        llm_service,
        intent_parser,
        intent_resolver,
        query_engine,
        conversation_manager,
        knowledge_base,
        conversation_intelligence=conversation_intelligence,
        response_layer=response_layer,
    )
