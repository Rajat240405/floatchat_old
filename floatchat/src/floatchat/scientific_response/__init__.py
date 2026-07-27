"""Scientific Response Layer — deterministic post-execution presentation (Phase 5).

Pipeline position (FloatChat 2.0 — Phase 5):

    Execution Engine → Execution Result (ChatResponse; FROZEN, unmodified)
                 │
                 ▼
    Scientific Response Layer  ← this package (deterministic; no LLM, no SQL,
                 │                no DuckDB, no planner/executor/viz changes)
                 ▼
    Chat Response (same schema; presentation recomposed)

Separation of concerns:
* **Facts** come straight from the execution engine — result statistics,
  map markers, figure traces, and the reasoning/context metadata produced
  upstream (Phase 3/4 traces).
* **Narrative** only describes those facts. Nothing in this package invents
  scientific observations; where data is insufficient for a statement, the
  statement is omitted.
"""

from floatchat.scientific_response.layer import (
    ComposedSections,
    ScientificResponseLayer,
)

__all__ = ["ScientificResponseLayer", "ComposedSections"]
