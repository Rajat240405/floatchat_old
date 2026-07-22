"""FastAPI route definitions — Phase 6: Traffic Cop routing.

4-way classifier expansion:
  DATA_QUERY     -> DuckDB pipeline
  SMALL_TALK     -> Fast hardcoded greeting (no LLM)
  OUT_OF_DOMAIN  -> Fast hardcoded polite bouncer (no LLM)
  KNOWLEDGE_QUERY-> Vetted local KB + strict LLM prompt, no hallucination
  GENERAL_QUERY  -> Legacy alias (treated as KNOWLEDGE but direct LLM for backward compat in tests)
"""

import json
import logging
import re
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from pathlib import Path

from floatchat.api.dependencies import (
    get_conversation_manager,
    get_intent_parser,
    get_knowledge_base,
    get_llm_service,
    get_query_classifier,
    get_query_engine,
)
from floatchat.config import settings
from floatchat.conversation.base import AbstractConversationManager
from floatchat.conversation.reference_phrases import detect_reference_phrases
from floatchat.entity_extractor.extractor import (
    LLMEntityExtractor,
    _is_placeholder_time_filter,
    build_clarification_message,
)
from floatchat.entity_extractor.temporal_resolver import resolve_temporal_filter
from floatchat.exceptions import FloatChatError, IntentParseError
from floatchat.intent_parser.base import AbstractIntentParser
from floatchat.llm_service.base import AbstractLLMService
from floatchat.llm_service.classifier import QueryClassifier
from floatchat.llm_service.knowledge_base import KnowledgeBase
from floatchat.models import ChatResponse, ParsedIntent
from floatchat.query_engine.engine import QueryEngine

# Dedicated lightweight registry response for dashboard bootstrap (no chat/LLM)
from pydantic import BaseModel

class FloatRegistryResponse(BaseModel):
    float_count: int
    map_data: list[dict]
    networks: list[str]
    dacs: list[str]
    variables: list[str]
    statuses: list[str]

logger = logging.getLogger(__name__)
router = APIRouter()



class ChatRequest(BaseModel):
    """Incoming POST /chat body."""

    message: str = Field(..., min_length=1, description="Natural language query.")
    session_id: str | None = Field(
        default=None,
        description="Client-generated session ID for conversational continuity.",
    )


def _check_critical_fields(intent: ParsedIntent, has_context: bool) -> str | None:
    """Phase 3: Return a clarification message if critical fields are missing.

    Intent-specific rules — only asks for what's genuinely needed:
      - Data queries (profile_plot, region_search, etc.): need variables + spatial scope
      - Float discovery (radius_search, nearest_float): need location, NOT variables
      - Metadata/trajectory: need float_id
      - Count: need region or location

    Returns None when the intent has everything it needs.
    """
    # Intents that don't need variables
    if intent.intent in ("radius_search", "nearest_float"):
        if intent.lat is None and intent.lon is None and not intent.region:
            if not has_context:
                return (
                    "Which location are you interested in? "
                    "Try a place name (e.g., 'floats near Goa') or "
                    "coordinates (e.g., 'nearest float to 15.5, 72.3')."
                )
        return None

    if intent.intent in ("metadata_lookup", "trajectory"):
        if not intent.float_id and not has_context:
            return (
                "Which float would you like to explore? "
                "Please provide a float ID (e.g., 'float 2902403')."
            )
        return None

    if intent.intent == "count_aggregate":
        if not intent.region and intent.lat is None and not has_context:
            return (
                "Which region? Try 'how many floats in Arabian Sea' "
                "or 'is there oxygen data near Mumbai'."
            )
        return None

    # Data queries (profile_plot, region_search, time_series, hovmoller, ts_diagram)
    # Need BOTH variables AND spatial scope
    has_spatial = (
        intent.region is not None
        or (intent.lat is not None and intent.lon is not None)
        or intent.float_id is not None
    )

    if not intent.variables and not intent.float_id:
        if not has_spatial and not has_context:
            return (
                "I can help with Argo ocean data. Try:\n"
                "• 'temperature in Arabian Sea 2024'\n"
                "• 'oxygen near Goa'\n"
                "• 'floats near Mumbai'\n"
                "• 'trajectory of float 2902403'"
            )
        if has_spatial and not has_context:
            var_list = "temperature, salinity, oxygen, chlorophyll, nitrate, pH"
            return (
                f"Which variable would you like to see? Available: {var_list}.\n\n"
                "Example: 'temperature in Arabian Sea 2024'"
            )

    if intent.variables and not has_spatial and not has_context:
        return (
            "Which region or location? Try:\n"
            "• 'temperature in Arabian Sea'\n"
            "• 'oxygen near Goa'\n"
            "• 'salinity in Bay of Bengal 2024'"
        )

    return None  # All critical fields present


def _build_full_context_prompt(
    conversation_manager: AbstractConversationManager,
    session_id: str | None,
    message: str,
) -> str:
    """Build a rich context prompt for GENERAL_QUERY / KNOWLEDGE_QUERY explanations."""
    if not session_id:
        return message

    ctx = conversation_manager.get_context(session_id)
    if not ctx:
        return message

    lines = [message, "", "--- Conversation Context ---"]
    if ctx.last_variables:
        lines.append(f"Variable(s): {', '.join(ctx.last_variables)}")
    if ctx.last_region:
        lines.append(f"Region: {ctx.last_region.replace('_', ' ')}")
    if ctx.last_float_id:
        lines.append(f"Float: {ctx.last_float_id}")
    if ctx.last_year:
        lines.append(f"Year: {ctx.last_year}")
    if ctx.last_profile_number:
        lines.append(f"Profile: {ctx.last_profile_number}")
    if ctx.last_intent:
        lines.append(f"Intent: {ctx.last_intent}")
    if ctx.last_message:
        lines.append(f"Previous result: {ctx.last_message}")
    if ctx.last_response_summary:
        summary = ctx.last_response_summary
        if summary.get("matched_records"):
            lines.append(f"Profiles retrieved: {summary['matched_records']}")
        if summary.get("total_measurements"):
            lines.append(f"Total measurements: {summary['total_measurements']}")

    return "\n".join(lines)


def _try_conversational_recovery(
    message: str,
    session_id: str | None,
    conversation_manager: AbstractConversationManager,
    intent_parser: AbstractIntentParser,
) -> ParsedIntent | None:
    """Attempt to recover from a parse failure using conversation context.

    Priority 2: Recovery only proceeds if the user's message contains an
    explicit reference phrase. Without one, no context is inherited.
    """
    if not session_id:
        logger.debug("No session_id; skipping conversational recovery")
        return None

    ctx = conversation_manager.get_context(session_id)
    if not ctx:
        logger.debug("No context for session %s; skipping recovery", session_id)
        return None

    if ctx.turn_count >= getattr(conversation_manager, "_max_turns", 10):
        logger.debug("Session %s context expired; skipping recovery", session_id)
        return None

    # Priority 2: Check for reference phrases BEFORE attempting recovery
    ref = detect_reference_phrases(message)
    if not ref.has_reference:
        logger.info(
            "No reference phrase in %r — skipping conversational recovery",
            message,
        )
        return None

    # Priority 2: If metadata follow-up detected, create a metadata_lookup intent
    if ref.is_metadata_followup:
        minimal = ParsedIntent(intent="metadata_lookup")
        # Pass the raw message explicitly so merge_context can detect
        # reference phrases robustly (no reliance on smuggled attributes).
        merged = conversation_manager.merge_context(
            session_id, minimal, message=message
        )
        logger.info(
            "Conversational recovery (metadata) for session %s: "
            "merged_float=%s ref=%s",
            session_id,
            merged.float_id,
            ref,
        )
        if merged.float_id:
            return merged
        # No float_id to inherit — can't do metadata lookup without a float
        return None

    try:
        minimal = intent_parser.parse(message)
    except IntentParseError:
        minimal = ParsedIntent(intent="profile_plot")

    # Pass the raw message explicitly so merge_context can detect reference
    # phrases robustly (no reliance on a smuggled _original_message attribute).
    merged = conversation_manager.merge_context(
        session_id, minimal, message=message
    )
    logger.info(
        "Conversational recovery for session %s: original_vars=%s merged_vars=%s "
        "merged_region=%s merged_float=%s ref=%s",
        session_id,
        minimal.variables,
        merged.variables,
        merged.region,
        merged.float_id,
        ref,
    )

    if merged.variables or merged.float_id:
        return merged

    return None


def _build_suggestion_message(ctx) -> str:
    """Phase 8: Build an intelligent suggestion message when parsing fails.

    Provides available variables, available regions, and context-aware
    suggestions instead of a generic error.
    """
    parts = ["I couldn't fully understand your query."]

    # Show what was previously being discussed (context-aware suggestions)
    if ctx and (ctx.last_variables or ctx.last_region or ctx.last_float_id):
        parts.append("\nYou were previously looking at:")
        if ctx.last_variables:
            parts.append(f"  • Variable: {', '.join(ctx.last_variables)}")
        if ctx.last_region:
            parts.append(f"  • Region: {ctx.last_region.replace('_', ' ').title()}")
        if ctx.last_float_id:
            parts.append(f"  • Float: {ctx.last_float_id}")
        if ctx.last_year:
            parts.append(f"  • Year: {ctx.last_year}")
        parts.append("\nTry: 'same region but in 2024', 'latest profile', 'that float'")

    # Available variables
    parts.append("\nAvailable variables:")
    parts.append("  • Temperature, Salinity, Oxygen, Chlorophyll")
    parts.append("  • Nitrate, pH, Backscattering, PAR")

    # Available regions
    parts.append("\nAvailable regions:")
    parts.append("  • Arabian Sea, Bay of Bengal, Indian Ocean")

    # Example queries
    parts.append("\nExample queries:")
    parts.append("  • temperature in Arabian Sea 2024")
    parts.append("  • floats near Goa")
    parts.append("  • trajectory of float 2902403")
    parts.append("  • oxygen in Bay of Bengal during monsoon")

    return "\n".join(parts)


def _try_llm_extraction(
    message: str,
    parsed: ParsedIntent,
    session_id: str | None,
    conversation_manager: AbstractConversationManager,
) -> ParsedIntent:
    """Priority 3: Try LLM entity extraction if critical slots are missing.

    Rules:
      1. If all slots are filled → return parsed unchanged (NO LLM call).
      2. If slots are missing → ONE call to small model.
      3. If LLM succeeds → merge extracted fields into parsed intent.
      4. If LLM fails or low confidence → return parsed unchanged (graceful degradation).
    """
    # Check if critical slots are missing
    has_vars = bool(parsed.variables)
    has_float = parsed.float_id is not None
    has_region = parsed.region is not None
    has_coords = parsed.lat is not None and parsed.lon is not None
    has_year = parsed.year is not None
    is_metadata = parsed.intent == "metadata_lookup"
    is_trajectory = parsed.intent == "trajectory"

    # P2 dedupe: if this intent was already produced by the LLM recovery path
    # (_try_llm_extraction_as_recovery), it has already consumed one LLM call.
    # Don't fire a second extraction — that was the source of the duplicate
    # ~4s call seen in production for queries like #7.
    if getattr(parsed, "_llm_extracted", False):
        logger.debug("Intent already LLM-extracted via recovery — skipping second extraction")
        return parsed

    # For metadata_lookup and trajectory, float_id is the only critical slot
    if is_metadata or is_trajectory:
        if has_float:
            return parsed  # All critical slots filled

    # For count_aggregate, region alone may be enough
    if parsed.intent == "count_aggregate" and has_region:
        return parsed

    # For data queries, we need variables + spatial scope.
    # BUT: if year is missing, we still try LLM to extract temporal info
    # (e.g., "during monsoon", "last summer"). This is the main use case
    # for the LLM extractor — resolving season tokens.
    if has_vars and (has_region or has_coords or has_float) and has_year:
        return parsed  # All critical slots filled (including year)

    # If we have vars + spatial but no year, try LLM for temporal extraction
    # If we're missing vars or spatial scope, try LLM for those too
    needs_llm = (
        not has_vars
        or not (has_region or has_coords or has_float)
        or not has_year
    )

    if not needs_llm:
        return parsed

    # If we reach here, slots are missing. Try LLM extraction.
    logger.info(
        "Priority 3: Missing critical slots (vars=%s region=%s float=%s year=%s) "
        "— attempting LLM extraction",
        parsed.variables, parsed.region, parsed.float_id, parsed.year,
    )

    extractor = LLMEntityExtractor()

    # Get conversation context for the LLM
    ctx_vars, ctx_region, ctx_year, ctx_float = [], None, None, None
    if session_id:
        ctx = conversation_manager.get_context(session_id)
        if ctx:
            ctx_vars = ctx.last_variables
            ctx_region = ctx.last_region
            ctx_year = ctx.last_year
            ctx_float = ctx.last_float_id

    spec = extractor.extract(
        message=message,
        context_vars=ctx_vars,
        context_region=ctx_region,
        context_year=ctx_year,
        context_float=ctx_float,
    )

    if spec is None:
        logger.info("Priority 3: LLM extraction returned None — keeping original parsed intent")
        return parsed

    # Phase 1/2: LLM is RESTRICTED to temporal + action only.
    # Hard-ignore LLM output for variables, float_id, depth, operational_filter.
    # Only time_filter and spatial_filter (as geographic inference when no coords)
    # are accepted from the LLM.
    updates = {}

    # variables: NEVER from LLM
    if spec.variables:
        logger.warning("LLM returned variables %s — IGNORED (restricted field)", spec.variables)

    # float_id: NEVER from LLM
    if spec.float_id:
        logger.warning("LLM returned float_id %s — IGNORED (restricted field)", spec.float_id)

    # operational_filter: NEVER from LLM (regex handles "alive"/"active")
    if spec.operational_filter:
        logger.warning("LLM returned operational_filter %s — IGNORED (restricted field)", spec.operational_filter)

    # depth_filter: NEVER from LLM (regex handles "deep"/"below Nm"/"surface")
    if spec.depth_filter:
        logger.warning("LLM returned depth_filter %s — IGNORED (restricted field)", spec.depth_filter)

    # spatial_filter: ACCEPTABLE only as geographic inference when no coords exist
    # (e.g., "near Goa" → region inference). Blocked when coordinates already resolved.
    if not has_region and spec.spatial_filter and not has_coords:
        updates["region"] = spec.spatial_filter

    if not has_year and spec.time_filter and not _is_placeholder_time_filter(spec.time_filter):
        # Resolve the temporal filter deterministically. Placeholder values
        # ("year", "time", ">=", ...) are already filtered out above; any
        # remaining unresolvable token yields None here and is silently
        # dropped — a hard filter, not just a warning.
        resolved = resolve_temporal_filter(
            spec.time_filter, reference_year=ctx_year
        )
        if resolved:
            if "year" in resolved:
                updates["year"] = resolved["year"]
            # If it's a date range, store in data_summary for engine to use
            elif "date_start" in resolved:
                updates["temporal_date_start"] = resolved["date_start"]
                updates["temporal_date_end"] = resolved["date_end"]
                # Extract year from date_start for the year field
                updates["year"] = int(resolved["date_start"][:4])

    # depth_filter: NEVER from LLM (handled above — IGNORED)
    # operational_filter: NEVER from LLM (handled above — IGNORED)

    if updates:
        logger.info(
            "Priority 3: LLM extraction filled slots: %s",
            {k: v for k, v in updates.items() if not k.startswith("_")},
        )
        merged_data = parsed.model_dump()
        merged_data.update({k: v for k, v in updates.items() if not k.startswith("_")})
        parsed = ParsedIntent(**merged_data)

    return parsed


def _try_llm_extraction_as_recovery(
    message: str,
    session_id: str | None,
    conversation_manager: AbstractConversationManager,
) -> ParsedIntent | None:
    """Priority 3: Try LLM entity extraction when regex parsing AND conversational
    recovery both fail.

    This handles complex queries like "alive floats near Goa during last monsoon"
    where the gazetteer fails but the LLM can extract structured entities.

    Returns a ParsedIntent if extraction succeeds, or None.
    """
    extractor = LLMEntityExtractor()

    ctx_vars, ctx_region, ctx_year, ctx_float = [], None, None, None
    if session_id:
        ctx = conversation_manager.get_context(session_id)
        if ctx:
            ctx_vars = ctx.last_variables
            ctx_region = ctx.last_region
            ctx_year = ctx.last_year
            ctx_float = ctx.last_float_id

    spec = extractor.extract(
        message=message,
        context_vars=ctx_vars,
        context_region=ctx_region,
        context_year=ctx_year,
        context_float=ctx_float,
    )

    if spec is None:
        logger.info("LLM recovery extraction returned None")
        return None

    # Phase 1/2: LLM recovery is ALSO restricted to temporal + action + spatial inference.
    # Hard-ignore variables, float_id, depth, operational_filter from the LLM.
    updates: dict[str, Any] = {
        "intent": spec.action,
    }

    # variables: NEVER from LLM
    if spec.variables:
        logger.warning("LLM recovery returned variables %s — IGNORED", spec.variables)

    # float_id: NEVER from LLM
    if spec.float_id:
        logger.warning("LLM recovery returned float_id %s — IGNORED", spec.float_id)

    # spatial_filter: ACCEPTABLE for gazetteer resolution (geographic inference)
    if spec.spatial_filter:
        # Check if it's a known region
        known_regions = {"arabian_sea", "bay_of_bengal", "indian_ocean"}
        sf = spec.spatial_filter.lower().replace(" ", "_").replace("-", "_")
        if sf in known_regions:
            updates["region"] = sf
        else:
            # Try gazetteer for place names
            try:
                from floatchat.intent_parser.gazetteer import resolve_place_name
                resolved = resolve_place_name(spec.spatial_filter)
                if resolved:
                    updates["lat"] = resolved["lat"]
                    updates["lon"] = resolved["lon"]
                    # If "alive" or "near" in query, this is a radius_search
                    if spec.operational_filter or "near" in message.lower():
                        updates["intent"] = "radius_search"
                        updates["radius_km"] = 500.0
            except Exception as exc:
                logger.warning("Gazetteer failed for LLM-extracted place '%s': %s", spec.spatial_filter, exc)

    # float_id: NEVER from LLM (handled above — IGNORED)

    if spec.time_filter and not _is_placeholder_time_filter(spec.time_filter):
        resolved = resolve_temporal_filter(spec.time_filter, reference_year=ctx_year)
        if resolved:
            if "year" in resolved:
                updates["year"] = resolved["year"]
            elif "date_start" in resolved:
                updates["temporal_date_start"] = resolved["date_start"]
                updates["temporal_date_end"] = resolved["date_end"]
                updates["year"] = int(resolved["date_start"][:4])

    # depth_filter: NEVER from LLM (IGNORED)
    # operational_filter: NEVER from LLM (IGNORED)

    # Only return if we got meaningful spatial or temporal data
    # (variables and float_id are no longer accepted from the LLM)
    if not updates.get("lat") and not updates.get("region") and not updates.get("year"):
        logger.info("LLM recovery extraction had no meaningful spatial/temporal slots")
        return None

    parsed = ParsedIntent(
        intent=updates.pop("intent", "region_search"),
        **{k: v for k, v in updates.items() if not k.startswith("_")},
    )
    # P2 dedupe: mark this intent as already LLM-extracted so the subsequent
    # _try_llm_extraction call in chat() skips a redundant second LLM call.
    parsed.__dict__["_llm_extracted"] = True
    return parsed


def _execute_mixed_plan(
    plan,
    intent: ParsedIntent,
    request: ChatRequest,
    query_engine,
    conversation_manager: AbstractConversationManager,
    knowledge_base: KnowledgeBase,
    llm_service: AbstractLLMService,
) -> ChatResponse:
    """Phase 5: Execute a mixed knowledge + data plan.

    Combines a KB explanation with a data query response into a single
    ChatResponse. The data portion delegates to the existing engine (backward
    compatible). The knowledge portion delegates to the existing KB handler.
    """
    logger.info("Executing mixed plan: %s", plan)

    # --- Knowledge portion --- #
    explain_op = plan.get("explain_topic")
    kb_text = ""
    if explain_op:
        topic = explain_op.params.get("topic", "general")
        # Use the original message for KB matching (better recall)
        best = knowledge_base.get_best_match(request.message, threshold=0.10)
        if best is not None:
            entry, score = best
            if settings.llm_enabled:
                try:
                    system_prompt = (
                        "You are FloatChat, a specialized oceanographic assistant. "
                        "Answer using ONLY the provided reference text. Be concise."
                    )
                    prompt = f"Reference: {entry['answer']}\n\nQuestion: {request.message}\n\nAnswer concisely:"
                    kb_text = llm_service.generate(prompt, system=system_prompt)
                except Exception:
                    kb_text = entry["answer"]
            else:
                kb_text = entry["answer"]
            logger.info("Mixed plan KB match: %s (score %.3f)", entry["id"], score)
        else:
            kb_text = f"Information about {topic} is not available in the knowledge base."

    # --- Data portion --- #
    data_response = query_engine.execute(intent)

    # --- Combine --- #
    combined_message = ""
    if kb_text:
        combined_message += f"📖 **About:** {kb_text}\n\n"
    combined_message += f"📊 **Data:** {data_response.message}"

    return ChatResponse(
        intent="mixed_query",
        message=combined_message,
        figure=data_response.figure,
        data_summary={
            **(data_response.data_summary or {}),
            "mixed_query": True,
            "kb_explanation": kb_text[:200] if kb_text else None,
        },
        map_data=data_response.map_data,
    )


def _handle_knowledge_query(
    message: str,
    session_id: str | None,
    conversation_manager: AbstractConversationManager,
    llm_service: AbstractLLMService,
    knowledge_base: KnowledgeBase,
) -> ChatResponse:
    """Handle KNOWLEDGE_QUERY using vetted KB + strict LLM prompt (RAG-lite)."""
    # Search KB
    best = knowledge_base.get_best_match(message, threshold=0.15)

    if best is None:
        logger.info("No KB entry matched for %r — safe fallback", message)
        fallback_msg = (
            "I don't have vetted information on that specific topic in my local Argo knowledge base. "
            "I can answer questions about: What is Argo, Core vs BGC floats, how floats work, parking depth, "
            "profile depth, battery lifespan, telemetry (Argos/Iridium), data quality (real-time vs delayed mode), "
            "WMO ID, GDAC, BGC sensors, profile/cycle, pressure measurement, and why Argo is important for India/INCOIS. "
            "Could you rephrase your question using one of those topics?"
        )
        response = ChatResponse(
            intent="knowledge_base",
            message=fallback_msg,
            figure=None,
            data_summary={"kb_matched": False, "query": message},
            map_data=[],
        )
        conversation_manager.update_context(
            session_id,
            ParsedIntent(intent="knowledge_base"),
            response,
        )
        return response

    entry, score = best
    logger.info("KB match for %r -> %s (score %.3f)", message, entry["id"], score)

    # If LLM enabled, use strict prompt with ONLY vetted text
    if settings.llm_enabled:
        try:
            system_prompt = (
                "You are FloatChat, a specialized oceanographic assistant built for INCOIS. "
                "Answer the user's question using ONLY the provided reference text. "
                "Make it sound conversational and friendly. "
                "Do not add outside information, do not guess, do not hallucinate. "
                "If the reference does not contain enough info to fully answer, say so and only use what is provided."
            )
            prompt = (
                f"Reference text (vetted, from argodatamgt.org documentation):\n"
                f"---\n"
                f"Question: {entry['question']}\n"
                f"Answer: {entry['answer']}\n"
                f"---\n\n"
                f"User question: {message}\n\n"
                f"Now answer the user's question using ONLY the reference text above. "
                f"Make it conversational. Do not add outside information."
            )
            prompt = _build_full_context_prompt(conversation_manager, session_id, prompt)
            answer = llm_service.generate(prompt, system=system_prompt)
            if not answer.strip():
                answer = entry["answer"]
        except Exception:
            logger.exception("LLM generation for KNOWLEDGE_QUERY failed; falling back to raw KB text")
            answer = entry["answer"]
    else:
        answer = entry["answer"]

    response = ChatResponse(
        intent="knowledge_base",
        message=answer,
        figure=None,
        data_summary={
            "kb_matched": True,
            "kb_id": entry["id"],
            "kb_score": round(score, 3),
            "kb_question": entry["question"],
            "category": entry["category"],
        },
        map_data=[],
    )
    conversation_manager.update_context(
        session_id,
        ParsedIntent(intent="knowledge_base"),
        response,
    )
    return response


def _handle_general_query_legacy(
    message: str,
    session_id: str | None,
    conversation_manager: AbstractConversationManager,
    llm_service: AbstractLLMService,
) -> ChatResponse:
    """Legacy GENERAL_QUERY handling — direct LLM answer with context hint.

    Kept for backward compatibility with tests that monkeypatch classify to GENERAL_QUERY.
    In Phase 6, new queries go to KNOWLEDGE_QUERY path instead.
    """
    augmented_prompt = _build_full_context_prompt(
        conversation_manager, session_id, message
    )
    answer = llm_service.generate(augmented_prompt)

    response = ChatResponse(
        intent="general_chat",
        message=answer,
        figure=None,
        data_summary={},
        map_data=[],
    )
    conversation_manager.update_context(
        session_id,
        ParsedIntent(intent="general_chat"),
        response,
    )
    return response


@router.post("/chat", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    classifier: Annotated[QueryClassifier, Depends(get_query_classifier)],
    llm_service: Annotated[AbstractLLMService, Depends(get_llm_service)],
    intent_parser: Annotated[AbstractIntentParser, Depends(get_intent_parser)],
    query_engine: Annotated[QueryEngine, Depends(get_query_engine)],
    conversation_manager: Annotated[
        AbstractConversationManager, Depends(get_conversation_manager)
    ],
    knowledge_base: Annotated[KnowledgeBase, Depends(get_knowledge_base)],
) -> ChatResponse:
    """Convert a natural-language message into a data visualization or answer.

    Flow (Phase 6 Traffic Cop):
        1. Classify into 4 buckets via QueryClassifier (rule-based + LLM)
        2. SMALL_TALK      → hardcoded greeting (no LLM)
        3. OUT_OF_DOMAIN   → hardcoded polite bouncer (no LLM)
        4. KNOWLEDGE_QUERY → KB search + strict LLM prompt (or raw KB if LLM disabled)
        5. GENERAL_QUERY   → legacy path (LLM direct answer)
        6. DATA_QUERY      → intent parser → merge context → query engine → viz
    """
    request_t0 = time.perf_counter()
    logger.info(
        "POST /chat received: %r session_id=%s",
        request.message,
        request.session_id,
    )

    try:
        # --- Step 1: Classify ------------------------------------------- #
        classify_t0 = time.perf_counter()
        query_type = QueryClassifier.classify(classifier, request.message)
        classify_t1 = time.perf_counter()
        logger.info(
            "Query classified as %s in %.3fs", query_type, classify_t1 - classify_t0
        )

        # --- Step 1.5: Conversational Override -------------------------- #
        # Priority 2: Also override OUT_OF_DOMAIN when the message contains
        # a reference phrase — "what about 2022?" is NOT out of domain if
        # the user was just discussing ocean data.
        if query_type in ("KNOWLEDGE_QUERY", "GENERAL_QUERY", "OUT_OF_DOMAIN"):
            try:
                if intent_parser._is_conversational_follow_up(request.message.lower()):
                    logger.info(
                        "Overriding %s to DATA_QUERY due to follow-up pattern", query_type
                    )
                    query_type = "DATA_QUERY"
            except Exception:
                pass

        # --- Step 2: SMALL_TALK — hardcoded greeting (no LLM) --------------- #
        if query_type == "SMALL_TALK":
            response = ChatResponse(
                intent="small_talk",
                message=QueryClassifier.get_small_talk_response(),
                figure=None,
                data_summary={"query_type": "SMALL_TALK"},
                map_data=[],
            )
            conversation_manager.update_context(
                request.session_id,
                ParsedIntent(intent="small_talk"),
                response,
            )
            _log_response(response, request_t0)
            return response

        # --- Step 3: OUT_OF_DOMAIN — polite bouncer (no LLM) ----------------- #
        if query_type == "OUT_OF_DOMAIN":
            response = ChatResponse(
                intent="out_of_domain",
                message=QueryClassifier.get_out_of_domain_response(),
                figure=None,
                data_summary={"query_type": "OUT_OF_DOMAIN"},
                map_data=[],
            )
            conversation_manager.update_context(
                request.session_id,
                ParsedIntent(intent="out_of_domain"),
                response,
            )
            _log_response(response, request_t0)
            return response

        # --- Step 4a: GENERAL_QUERY — legacy direct LLM answer ---------------- #
        if query_type == "GENERAL_QUERY":
            # Legacy path preserves old behavior for tests; real new queries are KNOWLEDGE_QUERY
            gen_t0 = time.perf_counter()
            response = _handle_general_query_legacy(
                request.message,
                request.session_id,
                conversation_manager,
                llm_service,
            )
            gen_t1 = time.perf_counter()
            logger.info("LLM general answer generated in %.3fs", gen_t1 - gen_t0)
            _log_response(response, request_t0)
            return response

        # --- Step 4b: KNOWLEDGE_QUERY — vetted KB ---------------------------- #
        if query_type == "KNOWLEDGE_QUERY":
            response = _handle_knowledge_query(
                request.message,
                request.session_id,
                conversation_manager,
                llm_service,
                knowledge_base,
            )
            _log_response(response, request_t0)
            return response

        # --- Step 5: DATA_QUERY — parse + merge context + pipeline ------ #
        try:
            parsed = intent_parser.parse(request.message)
        except IntentParseError as exc:
            logger.warning(
                "Initial parse failed for %r: %s. Attempting conversational recovery.",
                request.message,
                exc.message,
            )
            recovered = _try_conversational_recovery(
                request.message,
                request.session_id,
                conversation_manager,
                intent_parser,
            )
            if recovered is not None:
                logger.info(
                    "Conversational recovery succeeded: vars=%s region=%s float=%s",
                    recovered.variables,
                    recovered.region,
                    recovered.float_id,
                )
                parsed = recovered
            else:
                # Priority 3 fix: Try LLM entity extraction as a last resort
                # before giving up. The regex parser may fail on complex queries
                # like "alive floats near Goa during last monsoon" where the
                # gazetteer can't resolve a place name that includes temporal tokens.
                logger.info(
                    "Conversational recovery failed — trying LLM entity extraction as last resort"
                )
                llm_recovered = _try_llm_extraction_as_recovery(
                    request.message,
                    request.session_id,
                    conversation_manager,
                )
                if llm_recovered is not None:
                    logger.info(
                        "LLM extraction recovery succeeded: intent=%s vars=%s region=%s float=%s",
                        llm_recovered.intent,
                        llm_recovered.variables,
                        llm_recovered.region,
                        llm_recovered.float_id,
                    )
                    parsed = llm_recovered
                else:
                    ctx = (
                        conversation_manager.get_context(request.session_id)
                        if request.session_id
                        else None
                    )
                    suggestion = _build_suggestion_message(ctx)
                    logger.info("All recovery attempts failed; returning suggestions")
                    return ChatResponse(
                        intent="unknown",
                        message=suggestion,
                        figure=None,
                        data_summary={},
                        map_data=[],
                    )

        # Priority 2 (P0 fix): The raw user message is passed explicitly to
        # merge_context below so reference-phrase detection is robust against
        # the LLM extractor / metadata override reconstructing ParsedIntent
        # (which would otherwise drop a smuggled _original_message attribute).

        # Priority 2: If the parser detected metadata_lookup but the user's
        # message contains reference phrases like "it", ensure float_id
        # inheritance from context works correctly.
        ref_check = detect_reference_phrases(request.message)
        if ref_check.is_metadata_followup and parsed.intent != "metadata_lookup":
            logger.info(
                "Priority 2: Overriding intent %s → metadata_lookup "
                "for message with metadata follow-up patterns",
                parsed.intent,
            )
            parsed = ParsedIntent(intent="metadata_lookup")

        # --- Priority 3: LLM Entity Extraction (fallback only) --- #
        # If the deterministic parser produced an intent but critical slots
        # are missing (no variables, no float_id, no region), try ONE call
        # to the small LLM model to extract structured entities.
        parsed = _try_llm_extraction(
            request.message, parsed, request.session_id, conversation_manager,
        )

        # P0 fix: pass the raw message explicitly so merge_context detects
        # reference phrases even though _try_llm_extraction may have rebuilt
        # a fresh ParsedIntent (dropping any smuggled attribute).
        intent = conversation_manager.merge_context(
            request.session_id, parsed, message=request.message
        )
        logger.info(
            "Merged intent for execution: intent=%s vars=%s region=%s year=%s float=%s profile=%s",
            intent.intent,
            intent.variables,
            intent.region,
            intent.year,
            intent.float_id,
            intent.profile_number,
        )

        # Phase 2-5: Generate operation plan — the single source of truth.
        from floatchat.retrieval_planner.operation_planner import plan_from_intent
        plan = plan_from_intent(intent, message=request.message)
        logger.info("Phase 5 plan: %s", plan)

        # Phase 5: Mixed query execution (knowledge + data).
        # When the plan is mixed, execute both explain_topic and data ops.
        # This is the ONLY place where execution deviates from the old
        # intent-based pipeline. Non-mixed queries are unchanged.
        if plan.is_mixed and plan.has("explain_topic"):
            response = _execute_mixed_plan(
                plan, intent, request, query_engine,
                conversation_manager, knowledge_base, llm_service,
            )
            conversation_manager.update_context(request.session_id, intent, response)
            _log_response(response, request_t0)
            return response

        # Phase 3: Intent-specific critical field check.
        # If essential fields are missing, ask the user instead of executing
        # with incomplete data (prevents wrong/empty results).
        clarification = _check_critical_fields(
            intent, has_context=bool(request.session_id and conversation_manager.get_context(request.session_id))
        )
        if clarification:
            logger.info("Returning clarification: %s", clarification[:80])
            return ChatResponse(
                intent="clarification",
                message=clarification,
                figure=None,
                data_summary={},
                map_data=[],
            )

        response = query_engine.execute(intent)
        conversation_manager.update_context(request.session_id, intent, response)
        _log_response(response, request_t0)
        return response

    except FloatChatError:
        raise
    except Exception as exc:
        logger.exception("Unhandled exception in /chat: %s", exc)
        # Phase 8: return a graceful error as a normal ChatResponse (200)
        # instead of HTTP 500 — the frontend can always render it.
        return ChatResponse(
            intent="error",
            message=(
                "I encountered an unexpected error while processing your query. "
                "Please try rephrasing it. Example: 'temperature in Arabian Sea 2024'"
            ),
            figure=None,
            data_summary={"error": str(exc)[:200]},
            map_data=[],
        )


def _log_response(response: ChatResponse, request_t0: float) -> None:
    """Log response size, serialization time, and total request time."""
    serialize_t0 = time.perf_counter()
    try:
        json_bytes = json.dumps(response.model_dump(mode="json")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        logger.error("JSON serialization failed: %s", exc)
        return
    serialize_t1 = time.perf_counter()

    total_time = time.perf_counter() - request_t0
    logger.info(
        "Response ready: size=%.2f KB, serialize=%.3fs, total=%.3fs, "
        "intent=%s, map_markers=%d, has_figure=%s",
        len(json_bytes) / 1024,
        serialize_t1 - serialize_t0,
        total_time,
        response.intent,
        len(response.map_data),
        response.figure is not None,
    )


# ================================================
# NEW: Dedicated lightweight registry endpoint
# Replaces the previous "floats in arabian sea" bootstrap workaround.
# Returns data directly from Phase 2 float_registry + profile_index.
# No LLM, no intent parser, no session, no /chat routing.
# ================================================
@router.get("/floats/registry", response_model=FloatRegistryResponse)
def get_float_registry_endpoint():
    """Lightweight dashboard bootstrap endpoint.

    Returns:
    - float_count
    - map_data (latest position per float)
    - available filter values (networks, dacs, variables, statuses)

    Uses DuckDBDataLake directly. Safe for immediate startup use.
    """
    try:
        from floatchat.data_lake.duckdb_lake import DuckDBDataLake
        from floatchat.config import settings
        import pandas as pd

        lake = DuckDBDataLake(
            phase2_root=Path(settings.data_lake_dir) if settings.data_lake_phase2_enabled else None,
            use_phase2=settings.data_lake_phase2_enabled,
        )

        map_data: list[dict] = []
        networks: set[str] = set()
        dacs: set[str] = set()
        variables: set[str] = set()
        statuses: set[str] = set()

        # Prefer float_registry for metadata + status/network
        fr_df = lake.get_float_registry() if hasattr(lake, "get_float_registry") else pd.DataFrame()

        # Get latest position + float list from profile_index (or levels)
        pi_df = pd.DataFrame()
        if hasattr(lake, "get_profile_index"):
            try:
                pi_df = lake.get_profile_index(limit=10000)
            except Exception:
                pi_df = pd.DataFrame()

        if not pi_df.empty:
            # Latest position per float
            latest = pi_df.sort_values("date").groupby("float_id").tail(1)

            for _, row in latest.iterrows():
                fid = str(row.get("float_id", ""))
                lat = float(row.get("lat", row.get("latitude", 0) or 0))
                lon = float(row.get("lon", row.get("longitude", 0) or 0))

                map_data.append({
                    "float_id": fid,
                    "latitude": lat,
                    "longitude": lon,
                    "profile_date": str(row.get("date", ""))[:10] if pd.notna(row.get("date")) else None,
                    "dac": str(row.get("dac", row.get("institution", "")) or ""),
                    "variables": [],
                    "selected": False,
                    "status": "unknown",
                    "network": "Core Argo",
                })

        # Enrich from float_registry
        if not fr_df.empty and len(map_data) > 0:
            fr_map = {}
            for _, r in fr_df.iterrows():
                fid = str(r.get("float_id", ""))
                fr_map[fid] = {
                    "status": str(r.get("status", "unknown")),
                    "sensors": r.get("sensors", []) if isinstance(r.get("sensors"), list) else str(r.get("sensors", "")).split(","),
                    "institution": str(r.get("institution", "")),
                }

            for m in map_data:
                fid = m["float_id"]
                if fid in fr_map:
                    fr = fr_map[fid]
                    m["status"] = fr["status"]
                    sensors = fr["sensors"] or []
                    m["variables"] = [s.strip().upper() for s in sensors if s.strip()]
                    # Derive network
                    sensor_blob = " ".join(s.upper() for s in m["variables"])
                    m["network"] = "BGC Argo" if any(k in sensor_blob for k in ["DOXY", "CHLA", "NITRATE", "BBP", "PH", "PAR"]) else "Core Argo"
                    if fr["institution"]:
                        m["dac"] = fr["institution"]

        # Build unique filter values
        for m in map_data:
            if m.get("network"):
                networks.add(m["network"])
            if m.get("dac"):
                dacs.add(m["dac"])
            for v in m.get("variables", []):
                variables.add(v.upper())
            if m.get("status"):
                statuses.add(m["status"])

        # Sensible fallbacks
        if not networks:
            networks = {"Core Argo", "BGC Argo"}
        if not dacs:
            dacs = {"INCOIS", "Coriolis", "AOML"}
        if not variables:
            variables = {"TEMP", "PSAL", "DOXY", "CHLA"}
        if not statuses:
            statuses = {"active", "inactive"}

        return FloatRegistryResponse(
            float_count=len(map_data),
            map_data=map_data,
            networks=sorted(list(networks)),
            dacs=sorted(list(dacs)),
            variables=sorted(list(variables)),
            statuses=sorted(list(statuses)),
        )
    except Exception as exc:
        logger.exception("Registry endpoint failed: %s", exc)
        # Return empty but valid response so frontend never crashes
        return FloatRegistryResponse(
            float_count=0,
            map_data=[],
            networks=["Core Argo", "BGC Argo"],
            dacs=["INCOIS", "Coriolis", "AOML"],
            variables=["TEMP", "PSAL", "DOXY", "CHLA"],
            statuses=["active", "inactive"],
        )
