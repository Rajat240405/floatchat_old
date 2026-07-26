"""Geographic polygon definitions and point-in-polygon tests for ocean regions.

Uses the ray-casting algorithm (no external dependencies).

Ontology 2.0 (Phase 1): the polygon data and the ray-casting implementation
moved to the domain ontology (:mod:`floatchat.ontology.regions`) — the single
source of truth for region knowledge. This module keeps the legacy import
path working (``REGION_POLYGONS`` and ``point_in_region`` are re-exported
with identical contents and semantics).
"""

from floatchat.ontology.regions import REGIONS, point_in_region

__all__ = ["REGION_POLYGONS", "point_in_region"]


# Region polygons keyed by canonical region name. Contents are identical to
# the legacy hand-maintained table (verified by tests/test_ontology).
REGION_POLYGONS: dict[str, list[tuple[float, float]]] = {
    name: list(definition.polygon)
    for name, definition in REGIONS.items()
    if definition.polygon is not None
}
