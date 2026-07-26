"""Canonical intent vocabulary (Domain Ontology, Phase 1).

One canonical location describing every supported intent. This module is
*not* semantic understanding — it is the descriptive vocabulary and the named
intent groupings that were previously re-typed as ad-hoc frozensets across
the classifier, resolver, conversation memory, chat service and dispatcher.

================================  ==============================================
Ontology member                   Previous home(s)
================================  ==============================================
``NON_DATA_INTENTS``              ``query_engine.dispatch._NON_DATA_INTENTS``
``SCIENTIFIC_CONTEXT_INTENTS``    identical 7-name set in
                                  ``llm_service.classifier`` (``scientific_intents``)
                                  and ``intent_resolution.resolver``
                                  (context-enrichment gate)
``SCIENTIFIC_FOLLOWUP_INTENTS``   identical 6-name set (no ``trajectory``) in
                                  ``intent_resolution.resolver`` (follow-up
                                  intent reuse) and
                                  ``api.services.chat_service``
                                  (``_is_active_scientific_followup``)
``FLOAT_CENTRIC_INTENTS``         ``conversation.memory._FLOAT_CENTRIC_INTENTS``
================================  ==============================================

Contract note (Milestone 5, unchanged): the *runtime* intent vocabulary is
single-sourced from the ``Literal`` on ``ParsedIntent.intent``
(``models.intent``). This module documents that contract and attaches
metadata; a contract test (``tests/test_ontology``) asserts the names here
stay congruent with the ``Literal``. The ontology deliberately does not
import ``floatchat.models`` so it remains dependency-free.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Tuple


@dataclass(frozen=True)
class IntentDefinition:
    """Descriptive metadata for one supported intent name."""

    name: str
    kind: Literal["data", "non_data", "response_only"]
    description: str


# --------------------------------------------------------------------------- #
# ParsedIntent vocabulary (mirrors the Literal on models.intent.ParsedIntent)
# --------------------------------------------------------------------------- #

INTENT_DEFINITIONS: dict[str, IntentDefinition] = {
    # --- Data intents (executed deterministically against the data lake) --- #
    "profile_plot": IntentDefinition(
        "profile_plot", "data",
        "Vertical profile plot of one or more variables versus pressure.",
    ),
    "region_search": IntentDefinition(
        "region_search", "data",
        "Discovery query over a named ocean region (profiles for all matching floats).",
    ),
    "time_series": IntentDefinition(
        "time_series", "data",
        "Variable values aggregated over time for a scope.",
    ),
    "comparison_plot": IntentDefinition(
        "comparison_plot", "data",
        "Side-by-side profile comparison across floats or regions.",
    ),
    "comparison": IntentDefinition(
        "comparison", "data",
        "Comparison request (legacy sibling of comparison_plot).",
    ),
    "trajectory": IntentDefinition(
        "trajectory", "data",
        "Float drift trajectory map for a single float.",
    ),
    "hovmoller": IntentDefinition(
        "hovmoller", "data",
        "Depth-time Hovmöller heatmap for one variable.",
    ),
    "ts_diagram": IntentDefinition(
        "ts_diagram", "data",
        "Temperature-salinity (T-S) diagram coloured by pressure.",
    ),
    "nearest_float": IntentDefinition(
        "nearest_float", "data",
        "Find the float(s) nearest to a coordinate or place.",
    ),
    "radius_search": IntentDefinition(
        "radius_search", "data",
        "Find floats within a radius of a coordinate or place.",
    ),
    "metadata_lookup": IntentDefinition(
        "metadata_lookup", "data",
        "Deterministic float metadata card (sensors, status, battery, DAC).",
    ),
    "count_aggregate": IntentDefinition(
        "count_aggregate", "data",
        "Count/existence aggregate over profiles or floats.",
    ),
    # --- Non-data intents (handled before/outside the data pipeline) ------- #
    "general_chat": IntentDefinition(
        "general_chat", "non_data",
        "General conversational message (legacy, pre-Traffic-Cop).",
    ),
    "unknown": IntentDefinition(
        "unknown", "non_data",
        "The request could not be resolved to a supported intent.",
    ),
    "small_talk": IntentDefinition(
        "small_talk", "non_data",
        "Greetings/help chit-chat — hardcoded greeting, no data query.",
    ),
    "out_of_domain": IntentDefinition(
        "out_of_domain", "non_data",
        "Request outside the Argo/oceanography scope — polite bouncer.",
    ),
    "knowledge_base": IntentDefinition(
        "knowledge_base", "non_data",
        "Vetted Argo knowledge question answered from the local knowledge base.",
    ),
}


# --------------------------------------------------------------------------- #
# Response-only pseudo-intents (ChatResponse.intent values that never appear
# in a ParsedIntent; documented here so the full surface has one home).
# --------------------------------------------------------------------------- #

RESPONSE_INTENT_DEFINITIONS: dict[str, IntentDefinition] = {
    "available_plots": IntentDefinition(
        "available_plots", "response_only",
        "Deterministic listing of plottable variables for a float (capability question).",
    ),
    "clarification": IntentDefinition(
        "clarification", "response_only",
        "A critical field was missing; the user is asked a targeted question.",
    ),
    "mixed_query": IntentDefinition(
        "mixed_query", "response_only",
        "Mixed knowledge + data plan executed and combined.",
    ),
    "error": IntentDefinition(
        "error", "response_only",
        "Graceful internal-error response (HTTP 200 with error payload).",
    ),
}


# --------------------------------------------------------------------------- #
# Named intent groupings (verbatim relocations — memberships unchanged)
# --------------------------------------------------------------------------- #

#: Intents handled before/outside the data pipeline (chat routing, guard
#: rails). Consumed by ``query_engine.dispatch`` to derive ``_DATA_INTENTS``.
NON_DATA_INTENTS: frozenset[str] = frozenset({
    "general_chat",
    "unknown",
    "small_talk",
    "out_of_domain",
    "knowledge_base",
})

#: Scientific data intents that establish an active profile conversation.
#: Two legacy copies (classifier + resolver) were identical.
SCIENTIFIC_CONTEXT_INTENTS: frozenset[str] = frozenset({
    "profile_plot",
    "time_series",
    "hovmoller",
    "ts_diagram",
    "comparison_plot",
    "comparison",
    "trajectory",
})

#: Scientific intents eligible for follow-up intent reuse (identical 6-name
#: set in the resolver and the chat service; deliberately excludes
#: ``trajectory``).
SCIENTIFIC_FOLLOWUP_INTENTS: frozenset[str] = frozenset({
    "profile_plot",
    "time_series",
    "hovmoller",
    "ts_diagram",
    "comparison_plot",
    "comparison",
})

#: Float-centric intents — when the previous intent was one of these, "it" in
#: a follow-up resolves to the float_id (conversation memory).
FLOAT_CENTRIC_INTENTS: frozenset[str] = frozenset({
    "trajectory",
    "metadata_lookup",
    "nearest_float",
})
