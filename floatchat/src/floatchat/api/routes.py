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
        # Check if it's a known IO leaf or the indian_ocean alias
        from floatchat.metadata_service.region_model import all_recognisable_io_names

        known_regions = set(all_recognisable_io_names())
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
# Dedicated lightweight registry endpoint
# Returns ALL floats from Phase 2 float_registry + latest positions
# from profile_index. No LIMIT truncation. No LLM.
# ================================================
@router.get("/floats/registry", response_model=FloatRegistryResponse)
def get_float_registry_endpoint():
    """Lightweight dashboard bootstrap endpoint.

    Returns every float in the local lake with:
    - latest known position
    - registry status (active / inactive / drifted) — authoritative
    - region_tag for Quick Region filters
    - network / DAC / sensors for sidebar filters

    IMPORTANT: Must NOT apply an arbitrary profile LIMIT. A previous
    ``get_profile_index(limit=10000)`` only saw floats present in the
    newest 10k profiles, which collapsed a ~1300-float registry to ~269.
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

        fr_df = (
            lake.get_float_registry()
            if hasattr(lake, "get_float_registry")
            else pd.DataFrame()
        )

        # Latest position per float — NO row limit. Aggregate in DuckDB so we
        # never load the full profile_index into Python.
        latest_by_float: dict[str, dict] = {}
        try:
            conn = lake._get_connection()
            pi_path = None
            levels_path = None
            if lake._phase2_root and (lake._phase2_root / "parquet" / "profile_index").exists():
                pi_path = (
                    lake._phase2_root / "parquet" / "profile_index" / "**" / "*.parquet"
                ).as_posix()
            if lake._phase2_root and (lake._phase2_root / "parquet" / "levels").exists():
                levels_path = (
                    lake._phase2_root / "parquet" / "levels" / "**" / "*.parquet"
                ).as_posix()
            elif lake._lake_root.exists():
                levels_path = (lake._lake_root / "**" / "*.parquet").as_posix()

            if pi_path:
                # Detect lat/lon column names from a 1-row sample
                sample = conn.execute(
                    f"SELECT * FROM read_parquet('{pi_path}', hive_partitioning=true) LIMIT 1"
                ).fetchdf()
                cols = {c.lower(): c for c in sample.columns}
                lat_col = cols.get("latitude") or cols.get("lat") or "latitude"
                lon_col = cols.get("longitude") or cols.get("lon") or "longitude"
                region_col = cols.get("region_tag")
                dac_col = cols.get("dac") or cols.get("institution")

                region_select = (
                    f"arg_max({region_col}, date) AS region_tag"
                    if region_col
                    else "CAST(NULL AS VARCHAR) AS region_tag"
                )
                dac_select = (
                    f"arg_max({dac_col}, date) AS dac"
                    if dac_col
                    else "CAST('' AS VARCHAR) AS dac"
                )

                sql = f"""
                SELECT
                    CAST(float_id AS VARCHAR) AS float_id,
                    arg_max({lat_col}, date) AS lat,
                    arg_max({lon_col}, date) AS lon,
                    max(date) AS profile_date,
                    {region_select},
                    {dac_select}
                FROM read_parquet('{pi_path}', hive_partitioning=true)
                GROUP BY float_id
                """
                pos_df = conn.execute(sql).fetchdf()
                for _, row in pos_df.iterrows():
                    fid = str(row["float_id"])
                    latest_by_float[fid] = {
                        "lat": float(row["lat"]) if pd.notna(row.get("lat")) else None,
                        "lon": float(row["lon"]) if pd.notna(row.get("lon")) else None,
                        "profile_date": (
                            str(row["profile_date"])[:10]
                            if pd.notna(row.get("profile_date"))
                            else None
                        ),
                        "region_tag": (
                            str(row["region_tag"])
                            if pd.notna(row.get("region_tag")) and row.get("region_tag")
                            else None
                        ),
                        "dac": str(row["dac"]) if pd.notna(row.get("dac")) else "",
                    }
            elif levels_path:
                sql = f"""
                SELECT
                    CAST(float_id AS VARCHAR) AS float_id,
                    arg_max(lat, date) AS lat,
                    arg_max(lon, date) AS lon,
                    max(date) AS profile_date,
                    arg_max(region_tag, date) AS region_tag,
                    COALESCE(arg_max(dac, date), '') AS dac
                FROM read_parquet('{levels_path}', hive_partitioning=true)
                GROUP BY float_id
                """
                pos_df = conn.execute(sql).fetchdf()
                for _, row in pos_df.iterrows():
                    fid = str(row["float_id"])
                    latest_by_float[fid] = {
                        "lat": float(row["lat"]) if pd.notna(row.get("lat")) else None,
                        "lon": float(row["lon"]) if pd.notna(row.get("lon")) else None,
                        "profile_date": (
                            str(row["profile_date"])[:10]
                            if pd.notna(row.get("profile_date"))
                            else None
                        ),
                        "region_tag": (
                            str(row["region_tag"])
                            if pd.notna(row.get("region_tag")) and row.get("region_tag")
                            else None
                        ),
                        "dac": str(row["dac"]) if pd.notna(row.get("dac")) else "",
                    }
        except Exception as exc:
            logger.warning("Registry position aggregation failed: %s", exc)

        _BGC_MARKERS = (
            "DOXY", "CHLA", "NITRATE", "BBP", "PH", "PAR",
            "OPTODE", "FLUOROMETER", "BACKSCATTER", "SUNA", "ISUS", "OCR",
        )

        # Prefer iterating float_registry (authoritative membership + status).
        # Fall back to positions-only if registry file is missing.
        source_ids: list[str]
        fr_map: dict[str, dict] = {}
        if not fr_df.empty:
            for _, r in fr_df.iterrows():
                fid = str(r.get("float_id", "")).strip()
                if not fid:
                    continue
                raw_sensors = r.get("sensors", "")
                if isinstance(raw_sensors, list):
                    sensors = [str(s).strip().upper() for s in raw_sensors if str(s).strip()]
                elif isinstance(raw_sensors, str) and raw_sensors:
                    sensors = [s.strip().upper() for s in raw_sensors.split(",") if s.strip()]
                else:
                    sensors = []
                sensor_blob = " ".join(sensors)
                network = (
                    "BGC Argo"
                    if any(k in sensor_blob for k in _BGC_MARKERS)
                    else "Core Argo"
                )
                region_tag = (
                    str(r.get("region_tag"))
                    if pd.notna(r.get("region_tag")) and r.get("region_tag")
                    else None
                )
                # Authoritative status from registry ETL (active/inactive/drifted)
                status = str(r.get("status", "unknown") or "unknown").lower()
                if status not in ("active", "inactive", "drifted", "unknown"):
                    status = "unknown"
                institution = str(r.get("institution", "") or "")
                fr_map[fid] = {
                    "status": status,
                    "sensors": sensors,
                    "institution": institution,
                    "network": network,
                    "region_tag": region_tag,
                    "last_report_date": (
                        str(r.get("last_report_date"))[:10]
                        if pd.notna(r.get("last_report_date"))
                        else None
                    ),
                    "profiler_type": str(r.get("profiler_type", "") or "") or None,
                    "manufacturer": str(r.get("manufacturer", "") or "") or None,
                }
            source_ids = list(fr_map.keys())
        else:
            source_ids = list(latest_by_float.keys())

        for fid in source_ids:
            pos = latest_by_float.get(fid, {})
            fr = fr_map.get(fid, {})
            lat = pos.get("lat")
            lon = pos.get("lon")
            # Skip floats with no usable coordinates
            if lat is None or lon is None:
                continue
            if not (-90.0 <= float(lat) <= 90.0 and -180.0 <= float(lon) <= 180.0):
                continue
            if float(lat) == 0.0 and float(lon) == 0.0:
                continue

            status = fr.get("status") or "unknown"
            sensors = fr.get("sensors") or []
            network = fr.get("network") or "Core Argo"
            region_tag = fr.get("region_tag") or pos.get("region_tag")
            dac = fr.get("institution") or pos.get("dac") or ""
            profile_date = pos.get("profile_date") or fr.get("last_report_date")

            map_data.append({
                "float_id": fid,
                "latitude": float(lat),
                "longitude": float(lon),
                "profile_date": profile_date,
                "dac": dac,
                "variables": sensors,
                "selected": False,
                "status": status,
                "network": network,
                "region_tag": region_tag,
                "wmo_id": fid,
                "profiler_type": fr.get("profiler_type"),
                "manufacturer": fr.get("manufacturer"),
            })

        for m in map_data:
            if m.get("network"):
                networks.add(m["network"])
            if m.get("dac"):
                dacs.add(m["dac"])
            for v in m.get("variables") or []:
                variables.add(str(v).upper())
            if m.get("status"):
                statuses.add(m["status"])

        if not networks:
            networks = {"Core Argo", "BGC Argo"}
        if not dacs:
            dacs = {"INCOIS", "Coriolis", "AOML"}
        if not variables:
            variables = {"TEMP", "PSAL", "DOXY", "CHLA"}
        if not statuses:
            statuses = {"active", "inactive", "drifted"}

        logger.info(
            "Registry endpoint: %d floats (registry_rows=%d, positions=%d)",
            len(map_data),
            len(fr_map),
            len(latest_by_float),
        )

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
        return FloatRegistryResponse(
            float_count=0,
            map_data=[],
            networks=["Core Argo", "BGC Argo"],
            dacs=["INCOIS", "Coriolis", "AOML"],
            variables=["TEMP", "PSAL", "DOXY", "CHLA"],
            statuses=["active", "inactive", "drifted"],
        )


# ================================================
# Deterministic float resources — NO LLM, NO chat
# Used by UI actions: marker click, float search,
# View Trajectory, Show Latest Profile, cycle history.
# ================================================


class FloatMetadataAPIResponse(BaseModel):
    float_info: dict[str, Any]
    map_data: list[dict] = Field(default_factory=list)


class FloatTrajectoryAPIResponse(BaseModel):
    float_id: str
    cycle_count: int
    map_data: list[dict] = Field(default_factory=list)
    distance_km: float | None = None
    date_range: dict[str, Any] = Field(default_factory=dict)


class FloatProfileAPIResponse(BaseModel):
    float_id: str
    intent: str = "profile_plot"
    message: str = ""
    figure: dict[str, Any] | None = None
    figures: list[dict[str, Any]] | None = None
    data_summary: dict[str, Any] = Field(default_factory=dict)
    map_data: list[dict] = Field(default_factory=list)


def _get_lake():
    """Shared DuckDB lake helper for deterministic endpoints."""
    from floatchat.data_lake.duckdb_lake import DuckDBDataLake
    from floatchat.config import settings

    return DuckDBDataLake(
        phase2_root=Path(settings.data_lake_dir) if settings.data_lake_phase2_enabled else None,
        use_phase2=settings.data_lake_phase2_enabled,
    )


@router.get("/floats/{float_id}/metadata", response_model=FloatMetadataAPIResponse)
def get_float_metadata(float_id: str):
    """Deterministic metadata lookup. No LLM. No chat routing."""
    clean = str(float_id).strip()
    try:
        if clean.endswith(".0") and float(clean) == int(float(clean)):
            clean = str(int(float(clean)))
    except (TypeError, ValueError):
        pass
    lake = _get_lake()
    info = lake.query_metadata_lookup(clean) if lake else {"found": False, "float_id": clean}
    # Guarantee float_id is the clean form
    if isinstance(info, dict):
        info["float_id"] = clean
        info["wmo_id"] = clean

    map_data: list[dict] = []
    if info.get("last_lat") is not None and info.get("last_lon") is not None:
        map_data.append(
            {
                "float_id": clean,
                "latitude": float(info["last_lat"]),
                "longitude": float(info["last_lon"]),
                "profile_date": info.get("last_report_date"),
                "dac": info.get("dac") or info.get("institution") or "",
                "variables": info.get("sensors") or [],
                "selected": True,
                "status": info.get("status") or "unknown",
                "network": info.get("network") or "Core Argo",
                "wmo_id": clean,
                "region_tag": info.get("region_tag"),
                "manufacturer": info.get("manufacturer"),
                "profiler_type": info.get("profiler_type"),
            }
        )

    return FloatMetadataAPIResponse(float_info=info, map_data=map_data)


@router.get("/floats/{float_id}/trajectory", response_model=FloatTrajectoryAPIResponse)
def get_float_trajectory(float_id: str):
    """Deterministic trajectory + full cycle history. No LLM. No chat routing.

    Returns ALL cycles for the float (safety cap 50_000). Cycles without valid
    coordinates are still included so Cycle History is complete; the map simply
    skips plotting those points.
    """
    import math
    import pandas as pd

    clean = str(float_id).strip()
    # Normalize "7902190.0" → "7902190"
    try:
        if clean.endswith(".0") and float(clean) == int(float(clean)):
            clean = str(int(float(clean)))
    except (TypeError, ValueError):
        pass

    lake = _get_lake()
    df = pd.DataFrame()

    if lake and (lake.is_available() or lake.is_phase2_available()):
        if hasattr(lake, "get_profile_index"):
            df = lake.get_profile_index(float_id=clean, limit=50000)
            # Retry with alternate string forms if empty (id type mismatch)
            if df.empty:
                for alt in (f"{clean}.0", clean.lstrip("0") or clean):
                    if alt != clean:
                        df = lake.get_profile_index(float_id=alt, limit=50000)
                        if not df.empty:
                            break
        if df.empty and hasattr(lake, "_lake_root") and lake._lake_root.exists():
            try:
                conn = lake._get_connection()
                pi_path = (
                    (lake._phase2_root / "parquet" / "profile_index" / "**" / "*.parquet").as_posix()
                    if lake._phase2_root
                    and (lake._phase2_root / "parquet" / "profile_index").exists()
                    else (lake._lake_root / "**" / "*.parquet").as_posix()
                )
                sample = conn.execute(
                    f"SELECT * FROM read_parquet('{pi_path}', hive_partitioning=true) LIMIT 1"
                ).fetchdf()
                cols = [c.lower() for c in sample.columns]
                lat_col = "lat" if "lat" in cols else ("latitude" if "latitude" in cols else "lat")
                lon_col = "lon" if "lon" in cols else ("longitude" if "longitude" in cols else "lon")
                has_cycle = "cycle_number" in cols
                has_av = "available_variables" in cols
                cycle_sel = "cycle_number" if has_cycle else "CAST(NULL AS INTEGER) AS cycle_number"
                av_sel = (
                    "COALESCE(available_variables, '') AS available_variables"
                    if has_av
                    else "CAST('' AS VARCHAR) AS available_variables"
                )
                # One row per cycle when cycle_number exists; else one per date
                if has_cycle:
                    sql = (
                        f"SELECT CAST(float_id AS VARCHAR) AS float_id, "
                        f"cycle_number, "
                        f"min(date) AS date, "
                        f"arg_max({lat_col}, date) AS lat, "
                        f"arg_max({lon_col}, date) AS lon, "
                        f"COALESCE(arg_max(dac, date), '') AS dac, "
                        f"{av_sel.replace('available_variables', 'arg_max(available_variables, date)') if has_av else av_sel} "
                        f"FROM read_parquet('{pi_path}', hive_partitioning=true) "
                        f"WHERE regexp_replace(CAST(float_id AS VARCHAR), '\\.0$', '') = ? "
                        f"GROUP BY float_id, cycle_number "
                        f"ORDER BY min(date) ASC"
                    )
                else:
                    sql = (
                        f"SELECT CAST(float_id AS VARCHAR) AS float_id, date, "
                        f"arg_max({lat_col}, date) AS lat, arg_max({lon_col}, date) AS lon, "
                        f"COALESCE(arg_max(dac, date), '') AS dac, "
                        f"CAST(NULL AS INTEGER) AS cycle_number, "
                        f"CAST('' AS VARCHAR) AS available_variables "
                        f"FROM read_parquet('{pi_path}', hive_partitioning=true) "
                        f"WHERE regexp_replace(CAST(float_id AS VARCHAR), '\\.0$', '') = ? "
                        f"GROUP BY float_id, date ORDER BY date ASC"
                    )
                df = conn.execute(sql, [clean]).fetchdf()
            except Exception as exc:
                logger.warning("Trajectory endpoint lake query failed: %s", exc)

    if df.empty:
        return FloatTrajectoryAPIResponse(
            float_id=clean, cycle_count=0, map_data=[], distance_km=0.0, date_range={}
        )

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.sort_values(
            by=["cycle_number", "date"] if "cycle_number" in df.columns else ["date"],
            ascending=True,
        )

    # Authoritative status from registry
    status = "unknown"
    network = "Core Argo"
    try:
        fr = lake.get_float_registry(float_id=clean) if lake else None
        if fr is not None and not fr.empty:
            status = str(fr.iloc[0].get("status", "unknown") or "unknown").lower()
            sensors_raw = fr.iloc[0].get("sensors", "")
            sensor_blob = str(sensors_raw).upper()
            if any(
                k in sensor_blob
                for k in ("DOXY", "CHLA", "NITRATE", "BBP", "PH", "OPTODE", "FLUOROMETER")
            ):
                network = "BGC Argo"
    except Exception:
        pass

    # Optional per-cycle stats from levels (max depth, surface TEMP/PSAL)
    cycle_stats: dict[int, dict] = {}
    try:
        levels_path = None
        if lake._phase2_root and (lake._phase2_root / "parquet" / "levels").exists():
            levels_path = (lake._phase2_root / "parquet" / "levels" / "**" / "*.parquet").as_posix()
        elif lake._lake_root.exists():
            levels_path = (lake._lake_root / "**" / "*.parquet").as_posix()
        if levels_path:
            conn = lake._get_connection()
            stats_sql = f"""
            SELECT
                CAST(cycle_number AS INTEGER) AS cycle_number,
                max(pressure) AS max_depth,
                avg(CASE WHEN pressure <= 20 THEN COALESCE(temp_adjusted, temp) END) AS temp_surface,
                avg(CASE WHEN pressure <= 20 THEN COALESCE(psal_adjusted, psal) END) AS psal_surface
            FROM read_parquet('{levels_path}', hive_partitioning=true)
            WHERE regexp_replace(CAST(float_id AS VARCHAR), '\\.0$', '') = ?
            GROUP BY cycle_number
            """
            sdf = conn.execute(stats_sql, [clean]).fetchdf()
            for _, r in sdf.iterrows():
                try:
                    cn = int(r["cycle_number"])
                except Exception:
                    continue
                cycle_stats[cn] = {
                    "max_depth": float(r["max_depth"]) if pd.notna(r.get("max_depth")) else None,
                    "temp": float(r["temp_surface"]) if pd.notna(r.get("temp_surface")) else None,
                    "salinity": float(r["psal_surface"]) if pd.notna(r.get("psal_surface")) else None,
                }
    except Exception as exc:
        logger.debug("cycle stats from levels failed: %s", exc)

    lat_col = "lat" if "lat" in df.columns else "latitude"
    lon_col = "lon" if "lon" in df.columns else "longitude"

    # Distance only over consecutive valid points
    valid_coords = []
    for _, row in df.iterrows():
        try:
            la = float(row[lat_col]) if pd.notna(row.get(lat_col)) else None
            lo = float(row[lon_col]) if pd.notna(row.get(lon_col)) else None
        except Exception:
            la = lo = None
        if la is not None and lo is not None and math.isfinite(la) and math.isfinite(lo):
            if not (la == 0.0 and lo == 0.0):
                valid_coords.append((la, lo))
    total_dist_km = 0.0
    for i in range(len(valid_coords) - 1):
        lat1, lon1 = valid_coords[i]
        lat2, lon2 = valid_coords[i + 1]
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(math.radians(lat1))
            * math.cos(math.radians(lat2))
            * math.sin(dlon / 2) ** 2
        )
        c = 2 * math.asin(math.sqrt(max(0.0, min(1.0, a))))
        total_dist_km += 6371.0 * c

    map_data: list[dict] = []
    for idx_count, (_, row) in enumerate(df.iterrows()):
        try:
            lat_val = float(row[lat_col]) if pd.notna(row.get(lat_col)) else None
            lon_val = float(row[lon_col]) if pd.notna(row.get(lon_col)) else None
        except Exception:
            lat_val = lon_val = None
        if lat_val is not None and (not math.isfinite(lat_val) or (lat_val == 0.0 and lon_val == 0.0)):
            lat_val = None
        if lon_val is not None and not math.isfinite(lon_val):
            lon_val = None

        date_val = None
        if "date" in df.columns and pd.notna(row.get("date")) and str(row.get("date")) != "NaT":
            d = row["date"]
            if hasattr(d, "strftime"):
                date_val = d.strftime("%Y-%m-%d")
            else:
                date_val = str(d)[:10]

        p_num = None
        for col in ("cycle_number", "profile_number"):
            if col in df.columns and pd.notna(row.get(col)):
                try:
                    p_num = int(float(row[col]))
                    break
                except Exception:
                    pass
        # Do NOT invent sequential numbers that skip real cycle 1 —
        # only fall back when the source has no cycle_number column at all.
        if p_num is None and "cycle_number" not in df.columns:
            p_num = idx_count + 1

        cycle_vars: list[str] = []
        if "available_variables" in df.columns and pd.notna(row.get("available_variables")):
            cycle_vars = [
                v
                for v in str(row.get("available_variables")).split()
                if v and v.upper() not in {"NAN", "NONE"}
            ]

        stats = cycle_stats.get(p_num or -1, {})

        map_data.append(
            {
                "float_id": clean,
                "latitude": lat_val if lat_val is not None else 0.0,
                "longitude": lon_val if lon_val is not None else 0.0,
                "has_position": lat_val is not None and lon_val is not None,
                "profile_date": date_val,
                "profile_number": p_num,
                "dac": str(row.get("dac", "") or ""),
                "variables": cycle_vars,
                "selected": idx_count == len(df) - 1,
                "status": status,
                "network": network,
                "wmo_id": clean,
                "max_depth": stats.get("max_depth"),
                "temp": stats.get("temp"),
                "salinity": stats.get("salinity"),
            }
        )

    min_d = None
    max_d = None
    if "date" in df.columns and not df["date"].isna().all():
        try:
            min_d = pd.to_datetime(df["date"].min()).strftime("%Y-%m-%d")
            max_d = pd.to_datetime(df["date"].max()).strftime("%Y-%m-%d")
        except Exception:
            pass

    return FloatTrajectoryAPIResponse(
        float_id=clean,
        cycle_count=len(map_data),
        map_data=map_data,
        distance_km=round(total_dist_km, 1),
        date_range={"min": min_d, "max": max_d},
    )


@router.get("/floats/{float_id}/latest-profile", response_model=FloatProfileAPIResponse)
def get_float_latest_profile(float_id: str):
    """Deterministic latest-profile plot. No LLM. No chat routing.

    Builds a ParsedIntent and runs the lake-only QueryEngine path with the
    scientific narrator forced off so this UI action never invokes an LLM.
    """
    from floatchat.models import ParsedIntent
    from floatchat.query_engine.engine import QueryEngine
    from floatchat.visualization_engine.profile import ProfileVisualizationEngine
    from floatchat.metadata_service.gdac import GDACMetadataService
    from floatchat.repository_service.gdac_http import GDACRepositoryService
    from floatchat.netcdf_reader.bgc_reader import BGCNetCDFReader
    from floatchat.config import settings

    clean = str(float_id).strip()
    intent = ParsedIntent(
        intent="profile_plot",
        float_id=clean,
        variables=["TEMP", "PSAL", "DOXY", "CHLA"],
        limit=1,
    )

    # Force narrator off for this request (restore afterward)
    prev_flag = getattr(settings, "sci_narrator_enabled", True)
    settings.sci_narrator_enabled = False
    try:
        engine = QueryEngine(
            GDACMetadataService(),
            GDACRepositoryService(),
            BGCNetCDFReader(),
            ProfileVisualizationEngine(),
        )

        class _SilentExplainer:
            """Drop-in that never calls an LLM."""

            def generate_explanation(self, *a, **k):
                return ""

            def _narration_is_enabled(self):
                return False

        engine.explanation_engine = _SilentExplainer()  # type: ignore[assignment]
        response = engine.execute(intent)
    finally:
        settings.sci_narrator_enabled = prev_flag

    msg = response.message or f"Latest profile for float {clean}."
    # Strip trailing empty explanation separators
    while msg.endswith("\n"):
        msg = msg[:-1]
    if msg.endswith("\n\n"):
        msg = msg.rstrip()

    return FloatProfileAPIResponse(
        float_id=clean,
        intent=response.intent,
        message=msg,
        figure=response.figure,
        figures=response.figures,
        data_summary=response.data_summary or {},
        map_data=[
            m.model_dump() if hasattr(m, "model_dump") else m
            for m in (response.map_data or [])
        ],
    )
