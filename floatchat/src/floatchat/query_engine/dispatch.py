"""Intent → executor routing for the QueryEngine execution layer.

Extracted from the pre-M4 ``query_engine/engine.py`` monolith (Milestone 4
decomposition). Owns:

* the data-intent vocabulary (``_DATA_INTENTS``) that ``QueryEngine.execute``
  validates against, and
* ``ExecutionDeps`` — the frozen bundle of runtime collaborators handed to
  every executor — and the intent→executor route table.

Routing semantics (unchanged from the monolith): the five explicitly named
intents route to their dedicated executors; every other data intent
(region_search, profile_plot, time_series, hovmoller, ts_diagram,
comparison, comparison_plot) falls through to the general lake data-query
executor.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, get_args

if TYPE_CHECKING:
    from floatchat.data_lake.base import AbstractDataLake
    from floatchat.metadata_service.base import AbstractMetadataService
    from floatchat.netcdf_reader.base import AbstractNetCDFReader
    from floatchat.repository_service.base import AbstractRepositoryService
    from floatchat.retrieval_planner.planner import RetrievalPlanner
    from floatchat.scientific_explanation.engine import ScientificExplanationEngine
    from floatchat.visualization_engine.base import AbstractVisualizationEngine

from floatchat.models import ChatResponse, ParsedIntent
from floatchat.query_engine.executors import metadata as _metadata_executors
from floatchat.query_engine.executors import profile as _profile_executor
from floatchat.query_engine.executors import spatial, trajectory


# Milestone 5 (contract tightening): the intent vocabulary is single-sourced
# from the authoritative contract — the Literal on ``ParsedIntent.intent`` —
# instead of duplicating the intent names here. The derived set is identical
# to the hand-maintained one it replaces (verified by test_dispatch.py).
_INTENT_VOCABULARY = frozenset(get_args(ParsedIntent.model_fields["intent"].annotation))

# Intents handled before/outside the data pipeline (chat routing, guard rails).
_NON_DATA_INTENTS = frozenset({
    "general_chat",
    "unknown",
    "small_talk",
    "out_of_domain",
    "knowledge_base",
})

# All data intents that MUST go through the local data lake
_DATA_INTENTS = _INTENT_VOCABULARY - _NON_DATA_INTENTS


Executor = Callable[["ExecutionDeps", ParsedIntent, float], ChatResponse]


@dataclass(frozen=True)
class ExecutionDeps:
    """Runtime collaborators handed from ``QueryEngine`` to every executor.

    ``lake`` is the already-resolved (dependency-injected or lazily built and
    cached by the engine) data lake instance; it may be ``None`` when no lake
    could be initialised — executors preserve the monolith's ``None`` guards.

    Field types are declared against the abstract service contracts
    (Milestone 5): executors depend on these interfaces, never on concrete
    implementations.
    """

    lake: AbstractDataLake | None
    metadata: AbstractMetadataService
    repository: AbstractRepositoryService
    reader: AbstractNetCDFReader
    viz: AbstractVisualizationEngine
    explanation_engine: ScientificExplanationEngine
    planner: RetrievalPlanner


# Explicit intent → executor routes (the monolith's if-chain, unchanged).
_EXECUTOR_ROUTES: dict[str, Executor] = {
    "nearest_float": spatial.execute_nearest_float,
    "radius_search": spatial.execute_radius_search,
    "metadata_lookup": _metadata_executors.execute_metadata_lookup,
    "count_aggregate": _metadata_executors.execute_count_aggregate,
    "trajectory": trajectory.execute_trajectory,
}

# All remaining data intents use the general lake data-query executor.
_DEFAULT_EXECUTOR: Executor = _profile_executor.execute_data_query_via_lake


def route(intent_name: str) -> Executor:
    """Return the executor for a data intent (default: lake data query)."""
    return _EXECUTOR_ROUTES.get(intent_name, _DEFAULT_EXECUTOR)
