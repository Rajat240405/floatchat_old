"""Chat application service — Traffic Cop orchestration and response helpers.

Cleanup M3 (API layer decomposition): the contents of this module were moved
verbatim from the former monolithic ``api/routes.py``. ``handle_chat`` is the
orchestrator behind ``POST /chat``; the route module (``api/routes/chat.py``)
only wires HTTP parameters and dependency injection.

Flow (Phase 6 Traffic Cop):
    1. Classify into 4 buckets via QueryClassifier (rule-based + LLM)
    2. SMALL_TALK      → hardcoded greeting (no LLM)
    3. OUT_OF_DOMAIN   → hardcoded polite bouncer (no LLM)
    4. KNOWLEDGE_QUERY → KB search + strict LLM prompt (or raw KB if LLM disabled)
    5. DATA_QUERY      → intent resolver → planner → query engine → viz

Cleanup M2: the legacy GENERAL_QUERY alias and the QuerySpec/LLMEntityExtractor
fallback architecture were removed. IntentResolver (regex + LLMIntentCompiler)
is the single LLM path.
"""

import json
import logging
import re
import time
from typing import Any

from floatchat.config import settings
from floatchat.conversation.base import AbstractConversationManager
from floatchat.conversation.intelligence import ConversationIntelligence
from floatchat.api.schemas import ChatRequest
from floatchat.api.services.floats_service import build_available_plots_response
from floatchat.exceptions import FloatChatError, IntentParseError
from floatchat.intent_parser.base import AbstractIntentParser
from floatchat.intent_parser.regex import is_available_plots_query
from floatchat.intent_resolution.resolver import IntentResolver
from floatchat.llm_service.base import AbstractLLMService
from floatchat.llm_service.classifier import QueryClassifier
from floatchat.llm_service.knowledge_base import KnowledgeBase
from floatchat.models import ChatResponse, ParsedIntent
from floatchat.ontology.intents import SCIENTIFIC_FOLLOWUP_INTENTS
from floatchat.query_engine.engine import QueryEngine
from floatchat.scientific_response import ScientificResponseLayer
from floatchat.understanding import SemanticClarificationNeeded

logger = logging.getLogger(__name__)

def _is_active_scientific_followup(message: str, context: Any | None) -> bool:
    """Return whether an ambiguous message refers to the active profile.

    This is deliberately state-based. It does not enumerate individual
    follow-up sentences. Explicit definition/knowledge questions remain on
    the knowledge path unless they contain a deictic reference to the active
    observations.
    """
    if context is None:
        return False
    # Ontology 2.0 (Phase 1): the follow-up intent set lives in the domain
    # ontology (SCIENTIFIC_FOLLOWUP_INTENTS); membership is unchanged.
    if getattr(context, "last_intent", None) not in SCIENTIFIC_FOLLOWUP_INTENTS:
        return False
    if not (
        getattr(context, "last_float_id", None)
        or getattr(context, "last_profile_number", None)
        or getattr(context, "last_variables", None)
        or getattr(context, "last_response_summary", None)
    ):
        return False

    text = message.lower()
    independent_scope = bool(
        re.search(r"\b(?:float|wmo)\s*\d{5,}\b|\b\d{7}\b", text)
        or re.search(r"\b(?:in|near|around|within|from)\b", text)
        or re.search(r"[-+]?\d+(?:\.\d+)?\s*,\s*[-+]?\d+(?:\.\d+)?", text)
        or re.search(r"\b(?:19|20)\d{2}\b", text)
    )
    if independent_scope:
        return False

    definition_request = re.search(
        r"\b(?:what\s+is|what\s+are|define|explain)\b", text
    )
    deictic_reference = re.search(
        r"\b(?:this|these|here|it|observations?|findings?|results?)\b", text
    )
    if definition_request and not deictic_reference:
        return False
    return True

def _check_critical_fields(intent: ParsedIntent, has_context: bool) -> str | None:
    """Phase 3: Return a clarification message if critical fields are missing.

    Intent-specific rules — only asks for what's genuinely needed:
      - Data queries (profile_plot, region_search, etc.): need variables + spatial scope
      - Float discovery (radius_search, nearest_float): need location, NOT variables
      - Metadata/trajectory: need float_id
      - Count: need region, location, float, or temporal scope
        (Sprint 1 Bug 2; Sprint 4 — a float is a valid counting scope:
        "How many profiles does float 5906969 have?")

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
        # Sprint 1 (Bug 2): a resolved temporal scope (exact year or an
        # open-ended date window) is a valid counting scope — "floats
        # deployed after 2023" must execute (the executor labels the
        # whole-lake scope "India Region"), not bounce back as a region
        # clarification.
        has_temporal_scope = (
            intent.year is not None
            or bool(intent.temporal_date_start)
            or bool(intent.temporal_date_end)
        )
        # Sprint 4: a float id is a complete counting scope on its own —
        # "How many profiles does float 5906969 have?" must execute (the
        # count executor already handles float-scoped counts), not bounce
        # back asking "Which region?".
        if (
            not intent.region
            and intent.lat is None
            and not intent.float_id
            and not has_temporal_scope
            and not has_context
        ):
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
    """Build a rich context prompt for KNOWLEDGE_QUERY explanations."""
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


def handle_chat(
    request: ChatRequest,
    classifier: QueryClassifier,
    llm_service: AbstractLLMService,
    intent_parser: AbstractIntentParser,
    intent_resolver: IntentResolver,
    query_engine: QueryEngine,
    conversation_manager: AbstractConversationManager,
    knowledge_base: KnowledgeBase,
    *,
    conversation_intelligence: "ConversationIntelligence | None" = None,
    response_layer: "ScientificResponseLayer | None" = None,
) -> ChatResponse:
    """Convert a natural-language message into a data visualization or answer.

    Flow (Phase 6 Traffic Cop):
        1. Classify into 4 buckets via QueryClassifier (rule-based + LLM)
        2. SMALL_TALK      → hardcoded greeting (no LLM)
        3. OUT_OF_DOMAIN   → hardcoded polite bouncer (no LLM)
        4. KNOWLEDGE_QUERY → KB search + strict LLM prompt (or raw KB if LLM disabled)
        5. DATA_QUERY      → intent parser → merge context → query engine → viz
    """
    request_t0 = time.perf_counter()
    logger.info(
        "POST /chat received: %r session_id=%s",
        request.message,
        request.session_id,
    )

    # --- Step 0: Conversation control commands (Phase 4) ---------------- #
    # Deterministic session management (e.g. "Clear context.") — not intent
    # routing: it never reaches classification, parsing, or the engine.
    if conversation_intelligence is not None:
        control = conversation_intelligence.handle_control(
            request.message, request.session_id
        )
        if control is not None:
            conversation_manager.clear_context(request.session_id)
            response = ChatResponse(
                intent="general_chat",
                message=control.acknowledgment,
                figure=None,
                data_summary={"action": control.action, "source": "conversation_intelligence"},
                map_data=[],
            )
            _log_response(response, request_t0)
            return response

    try:
        # --- Step 1: Classify ------------------------------------------- #
        classify_t0 = time.perf_counter()
        prior_context = (
            conversation_manager.get_context(request.session_id)
            if request.session_id
            else None
        )
        try:
            query_type = QueryClassifier.classify(
                classifier,
                request.message,
                conversation_context=prior_context,
            )
        except TypeError:
            # Preserve compatibility with injected/test classifiers that still
            # implement the original one-argument contract.
            query_type = QueryClassifier.classify(classifier, request.message)
        classify_t1 = time.perf_counter()
        logger.info(
            "Query classified as %s in %.3fs", query_type, classify_t1 - classify_t0
        )

        active_scientific_followup = _is_active_scientific_followup(
            request.message, prior_context
        )
        if active_scientific_followup:
            logger.info(
                "Active scientific context takes precedence over classifier result %s",
                query_type,
            )
            query_type = "DATA_QUERY"

        # --- Step 1.5: Conversational Override -------------------------- #
        # Priority 2: Also override OUT_OF_DOMAIN when the message contains
        # a reference phrase — "what about 2022?" is NOT out of domain if
        # the user was just discussing ocean data.
        if query_type in ("KNOWLEDGE_QUERY", "OUT_OF_DOMAIN"):
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

        # --- Step 5: DATA_QUERY — canonical intent pipeline ------------- #
        # Semantic understanding (Phase 2), optional compiler fallback,
        # validation, and context enrichment are owned by one resolver.
        # The route only plans and executes.
        try:
            intent = intent_resolver.resolve(request.message, request.session_id)
        except SemanticClarificationNeeded as exc:
            # Phase 2: the semantic layer determined that the request is
            # ambiguous/incomplete and produced a targeted clarification
            # question instead of guessing values. Answered with the existing
            # "clarification" response pseudo-intent (schema unchanged).
            logger.info("Semantic clarification requested: %s", exc.message[:80])
            return ChatResponse(
                intent="clarification",
                message=exc.message,
                figure=None,
                data_summary={"source": "semantic_understanding"},
                map_data=[],
            )
        except IntentParseError as exc:
            ctx = (
                conversation_manager.get_context(request.session_id)
                if request.session_id
                else None
            )
            logger.info("Canonical intent resolution failed: %s", exc.message)
            return ChatResponse(
                intent="unknown",
                message=_build_suggestion_message(ctx),
                figure=None,
                data_summary={},
                map_data=[],
            )
        logger.info(
            "Resolved canonical intent: intent=%s vars=%s region=%s year=%s float=%s profile=%s",
            intent.intent,
            intent.variables,
            intent.region,
            intent.year,
            intent.float_id,
            intent.profile_number,
        )

        from floatchat.retrieval_planner.operation_planner import plan_from_intent
        plan = plan_from_intent(
            intent,
            message="" if active_scientific_followup else request.message,
        )
        logger.info("Phase 5 plan: %s", plan)

        if plan.is_mixed and plan.has("explain_topic"):
            response = _execute_mixed_plan(
                plan, intent, request, query_engine,
                conversation_manager, knowledge_base, llm_service,
            )
            conversation_manager.update_context(request.session_id, intent, response)
            _log_response(response, request_t0)
            return response

        # Sprint 1 (Bug 2): deterministic interception of float *capability*
        # questions ("What plots are available for float 2903467?"). These are
        # routed to metadata_lookup by the parser; without this interception
        # the metadata card is returned (or, pre-fix, a profile plot with
        # every numeric column attempted — crashing Plotly). Respond with the
        # deterministic capability listing instead: only variables that have
        # at least one profile, no visualization. Mixed queries (e.g. "…and
        # explain X") are handled by the mixed pipeline above.
        if (
            intent.intent == "metadata_lookup"
            and intent.float_id
            and is_available_plots_query(request.message)
        ):
            try:
                availability = build_available_plots_response(intent.float_id)
                variables = [item.variable for item in availability.plots]
                if variables:
                    message = (
                        f"Available plots for Float {availability.float_id}: "
                        f"{', '.join(variables)}."
                    )
                else:
                    message = (
                        f"No plottable variables were found for Float "
                        f"{availability.float_id} in the local data lake."
                    )
                response = ChatResponse(
                    intent="available_plots",
                    message=message,
                    figure=None,
                    data_summary={
                        "matched_records": 0,
                        "float_id": availability.float_id,
                        "available_plots": [
                            item.model_dump() for item in availability.plots
                        ],
                    },
                    map_data=[],
                )
            except Exception:
                logger.exception(
                    "available-plots interception failed for float %s",
                    intent.float_id,
                )
                response = ChatResponse(
                    intent="available_plots",
                    message=(
                        f"Could not determine the available plots for Float "
                        f"{intent.float_id}."
                    ),
                    figure=None,
                    data_summary={"matched_records": 0},
                    map_data=[],
                )
            conversation_manager.update_context(request.session_id, intent, response)
            _log_response(response, request_t0)
            return response

        clarification = _check_critical_fields(
            intent,
            has_context=bool(
                request.session_id
                and conversation_manager.get_context(request.session_id)
            ),
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
        # --- Step 6: Scientific Response Layer (Phase 5) ---------------- #
        # Deterministic, post- execution presentation: recomposes only the
        # message/data_summary envelope. The engine's result (figure, map
        # data, query stats) passes through byte-identical; the original
        # engine message is preserved under data_summary["engine_message"].
        if response_layer is not None:
            outcome = getattr(intent_resolver, "last_semantic_outcome", None)
            response = response_layer.compose(
                response,
                intent=intent,
                context_resolutions=getattr(outcome, "context_resolutions", ()) if outcome else (),
                reasoning_rule=getattr(outcome, "reasoning_rule", None) if outcome else None,
                reasoning_resolutions=getattr(outcome, "reasoning_resolutions", ()) if outcome else (),
                # Sprint 1 (Bugs 1/4): lets the layer match count wording to
                # the entity the scientist asked about; wording only, never
                # computation.
                user_message=request.message,
            )
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

    figures = []
    if response.figure is not None:
        figures.append(response.figure)
    figures.extend(response.figures or [])
    trace_count = sum(len(f.get("data", []) or []) for f in figures)
    plotted_points = sum(
        max(len(t.get("x", []) or []), len(t.get("y", []) or []))
        for f in figures
        for t in (f.get("data", []) or [])
    )
    logger.info(
        "PIPELINE application_response_serialization: %.3fs total_to_route_return=%.3fs "
        "payload=%.2fKB traces=%d plotted_points=%d rows_returned=%s "
        "intent=%s map_markers=%d has_figure=%s",
        serialize_t1 - serialize_t0,
        total_time,
        len(json_bytes) / 1024,
        trace_count,
        plotted_points,
        response.data_summary.get("total_measurements"),
        response.intent,
        len(response.map_data),
        response.figure is not None,
    )
