"""Query Engine orchestrator.

Maps :class:`ParsedIntent` through the full pipeline and returns a
:class:`ChatResponse`.

Priority 1A: ALL data intents route EXCLUSIVELY through DuckDBDataLake.
The legacy GDAC pipeline (RetrievalPlanner → metadata_service → repository_service
→ live NetCDF downloads) is ONLY accessible when
FLOATCHAT_ALLOW_REMOTE_GDAC_FALLBACK=True (default: False).

Milestone 4: this module is the thin orchestration shell of the query
engine. It owns construction (dependency injection), the public
:meth:`QueryEngine.execute` contract (validation + deployment gate +
data-intent routing), and lazy data-lake lifecycle management. Execution
responsibilities live in dedicated modules:

* ``floatchat.query_engine.dispatch`` — data-intent vocabulary,
  ``ExecutionDeps`` collaborator bundle, intent→executor routing.
* ``floatchat.query_engine.executors.spatial`` — nearest-float / radius search.
* ``floatchat.query_engine.executors.metadata`` — metadata lookup / counts.
* ``floatchat.query_engine.executors.trajectory`` — trajectory queries.
* ``floatchat.query_engine.executors.profile`` — lake data queries (plots,
  region search, series, comparisons) incl. visualization + explanation.
* ``floatchat.query_engine.executors.legacy`` — gated GDAC fallback pipeline.
* ``floatchat.query_engine.helpers`` / ``floatchat.query_engine.response_builder``
  — shared internal utilities and response construction.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from floatchat.config import settings
from floatchat.metadata_service.base import AbstractMetadataService
from floatchat.models import ChatResponse, ParsedIntent
from floatchat.netcdf_reader.base import AbstractNetCDFReader
from floatchat.ontology.regions import INDIA_QUERY_REGIONS
from floatchat.query_engine import dispatch
from floatchat.query_engine.dispatch import _DATA_INTENTS
from floatchat.repository_service.base import AbstractRepositoryService
from floatchat.retrieval_planner.planner import RetrievalPlanner
from floatchat.scientific_explanation.engine import ScientificExplanationEngine
from floatchat.visualization_engine.base import AbstractVisualizationEngine

if TYPE_CHECKING:
    from floatchat.data_lake.base import AbstractDataLake

logger = logging.getLogger(__name__)

__all__ = ["QueryEngine"]


class QueryEngine:
    """Orchestrates the data retrieval and visualization pipeline.

    Milestone 4: thin dispatcher. Construction and the public
    ``execute(intent)`` contract are unchanged; execution is delegated
    to ``query_engine.executors`` via ``query_engine.dispatch``.

    Priority 1A: All data intents route through DuckDBDataLake by default.
    The legacy GDAC pipeline is only used when FLOATCHAT_ALLOW_REMOTE_GDAC_FALLBACK=True.
    """

    def __init__(
        self,
        metadata_service: AbstractMetadataService,
        repository_service: AbstractRepositoryService,
        netcdf_reader: AbstractNetCDFReader,
        visualization_engine: AbstractVisualizationEngine,
        explanation_engine: ScientificExplanationEngine | None = None,
        data_lake: AbstractDataLake | None = None,
    ) -> None:
        self.metadata = metadata_service
        self.repository = repository_service
        self.reader = netcdf_reader
        self.viz = visualization_engine
        self.explanation_engine = (
            explanation_engine if explanation_engine is not None else ScientificExplanationEngine()
        )
        self.planner = RetrievalPlanner()
        # Runtime lake is normally injected by the application composition
        # root. Keeping lazy fallback preserves direct/test construction.
        self._data_lake: AbstractDataLake | None = data_lake

    def execute(self, intent: ParsedIntent) -> ChatResponse:
        """Run the full pipeline for a single parsed intent.

        Priority 1A: ALL data intents go through the local data lake.
        No GDAC HTTP calls are made unless FLOATCHAT_ALLOW_REMOTE_GDAC_FALLBACK=True.
        """
        pipeline_t0 = time.perf_counter()

        # --- Phase 26: India-only Deployment Gate --- #
        if settings.deployment_mode == "INDIA_ONLY":
            # Ontology 2.0 (Phase 1): the supported-region set lives in the
            # domain ontology (INDIA_QUERY_REGIONS); membership is unchanged.
            supported_india_regions = INDIA_QUERY_REGIONS
            if intent.region and intent.region not in supported_india_regions:
                return ChatResponse(
                    intent=intent.intent,
                    message=(
                        f"Region '{intent.region}' is not supported in the current "
                        "deployment mode. Please request data for the Arabian Sea or Bay of Bengal."
                    ),
                    data_summary={"matched_records": 0},
                )

        # --- Priority 1A: Route ALL data intents through local data lake --- #
        if intent.intent in _DATA_INTENTS:
            return self._execute_via_data_lake_or_explain(intent, pipeline_t0)

        # Non-data intents fall through (small_talk, knowledge_base, etc.)
        logger.warning("Non-data intent reached execute(): %s", intent.intent)
        return ChatResponse(
            intent=intent.intent,
            message="This query type is not handled by the data pipeline.",
            data_summary={"matched_records": 0},
        )

    def _execute_via_data_lake_or_explain(
        self, intent: ParsedIntent, pipeline_t0: float
    ) -> ChatResponse:
        """Route a data intent to its executor through the local DuckDB data lake.

        Milestone 4: resolves the (cached, injected-or-lazy) data lake once,
        bundles the runtime collaborators, and dispatches via
        ``dispatch.route``. Routing semantics are unchanged from the monolith.
        """
        deps = dispatch.ExecutionDeps(
            lake=self._get_data_lake(),
            metadata=self.metadata,
            repository=self.repository,
            reader=self.reader,
            viz=self.viz,
            explanation_engine=self.explanation_engine,
            planner=self.planner,
        )
        return dispatch.route(intent.intent)(deps, intent, pipeline_t0)

    def _get_data_lake(self) -> AbstractDataLake | None:
        """Lazily instantiate the data lake on first use."""
        if self._data_lake is None:
            try:
                from floatchat.data_lake import DuckDBDataLake

                if settings.data_lake_phase2_enabled:
                    phase2_dir = Path(settings.data_lake_dir)
                    lake = DuckDBDataLake(
                        phase2_root=phase2_dir,
                        use_phase2=True,
                    )
                    if lake.is_phase2_available():
                        self._data_lake = lake
                        logger.info("Phase 2 Data Lake initialised: root=%s", phase2_dir)
                    else:
                        logger.warning(
                            "Phase 2 data lake configured but not available at %s. "
                            "Falling back to Phase 1.",
                            phase2_dir,
                        )
                        lake_root = Path(settings.data_lake_root)
                        self._data_lake = DuckDBDataLake(lake_root=lake_root)
                else:
                    lake_root = Path(settings.data_lake_root)
                    self._data_lake = DuckDBDataLake(lake_root=lake_root)

                logger.info(
                    "Data Lake initialised: root=%s available=%s",
                    self._data_lake._lake_root,
                    self._data_lake.is_available(),
                )
            except Exception as exc:
                logger.error("Failed to initialise data lake: %s", exc)
                return None
        return self._data_lake
