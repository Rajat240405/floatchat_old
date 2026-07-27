"""FloatChat 2.0 — Phase 2: Semantic Understanding Layer.

"The LLM understands. Deterministic software executes."

This package replaces the *understanding* half of the NL → execution
boundary. The LLM only produces a :class:`SemanticUnderstanding` (the
**understanding contract**) grounded in the Phase 1 domain ontology; a
deterministic converter turns that into ``ParsedIntent`` (the **execution
contract**, unchanged) or a structured clarification request. The execution
engine — Planner, QueryEngine, Executors, DuckDB, Visualization, Scientific
Narration, API contracts — is untouched.

The legacy regex parser remains fully available as the fallback/compatibility
path (feature flag: ``FLOATCHAT_SEMANTIC_UNDERSTANDING_ENABLED``); the
:class:`~floatchat.intent_resolution.resolver.IntentResolver` wires:

    semantic layer ── success ──▶ ParsedIntent
                   └─ failure ──▶ legacy regex parser (+ its compiler chain)

Phase 3 inserts the deterministic **Semantic Reasoner** between grounding and
assembly: it is the single authority for execution-intent selection, deciding
the scientist's objective (discovery vs measurement, metadata vs data,
comparisons, specificity precedence, ambiguity ranking) from grounded facts —
never from keywords.

Public API:

* :class:`SemanticUnderstanding` + mention models — understanding contract.
* :class:`SemanticUnderstandingService` — the single LLM call + conversion.
* :class:`SemanticConverter` — deterministic ontology-grounded conversion.
* :class:`SemanticReasoner`, :class:`GroundedUtterance`,
  :class:`ReasoningDecision`, :class:`ReasonedClarification` — Phase 3
  deterministic objective reasoning.
* :class:`ConversionOutcome`, :class:`ClarificationRequest` — results.
* :class:`SemanticUnavailableError` — benign fallback signal.
* :class:`SemanticClarificationNeeded` — ask-instead-of-guess signal.
"""

from floatchat.understanding.converter import (
    ClarificationRequest,
    ConversionOutcome,
    SemanticConverter,
    convert_to_parsed_intent,
    ground_intent_name,
    ground_region_mention,
    ground_variable_mention,
)
from floatchat.understanding.exceptions import (
    SemanticClarificationNeeded,
    SemanticUnavailableError,
)
from floatchat.understanding.models import (
    Ambiguity,
    ComparisonMention,
    DepthMention,
    SemanticUnderstanding,
    SpatialMention,
    TemporalMention,
)
from floatchat.understanding.prompt import build_system_prompt, build_user_prompt
from floatchat.understanding.reasoner import (
    GroundedUtterance,
    ReasonedClarification,
    ReasoningDecision,
    SemanticReasoner,
)
from floatchat.understanding.service import SemanticUnderstandingService

__all__ = [
    "SemanticUnderstanding",
    "TemporalMention",
    "DepthMention",
    "SpatialMention",
    "ComparisonMention",
    "Ambiguity",
    "SemanticUnderstandingService",
    "SemanticConverter",
    "ConversionOutcome",
    "ClarificationRequest",
    "convert_to_parsed_intent",
    "ground_variable_mention",
    "ground_region_mention",
    "ground_intent_name",
    "SemanticReasoner",
    "GroundedUtterance",
    "ReasoningDecision",
    "ReasonedClarification",
    "SemanticUnavailableError",
    "SemanticClarificationNeeded",
    "build_system_prompt",
    "build_user_prompt",
]
