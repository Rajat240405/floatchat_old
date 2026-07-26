"""Named ocean region definitions.

Regions are normalised to lowercase with underscores.
Two filtering strategies are supported:

1. **Bounding-box** (fast, approximate) — used when no polygon is available.
2. **Polygon** (accurate) — used for all defined regions.

Sources: broadly accepted oceanographic boundaries.
"""

from typing import TypedDict

from floatchat.metadata_service.polygons import REGION_POLYGONS, point_in_region
from floatchat.ontology.regions import REGIONS


class _Bounds(TypedDict):
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float


# Bounding boxes kept as coarse pre-filters for performance.
# The polygon test (applied after) is the authoritative filter.
# Ontology 2.0 (Phase 1): bounding boxes live in the domain ontology
# (RegionDefinition.bbox); contents are unchanged.
_BOUNDS: dict[str, _Bounds] = {
    name: definition.bbox
    for name, definition in REGIONS.items()
    if definition.bbox is not None
}


def has_polygon(region_name: str | None) -> bool:
    """Return True if a polygon definition exists for *region_name*."""
    if region_name is None:
        return False
    return region_name.lower().strip().replace(" ", "_") in REGION_POLYGONS


def resolve_region(name: str | None) -> _Bounds | None:
    """Return bounding-box pre-filter for a named region, or ``None``."""
    if name is None:
        return None
    return _BOUNDS.get(name.lower().strip().replace(" ", "_"))


__all__ = [
    "has_polygon",
    "point_in_region",
    "resolve_region",
    "REGION_POLYGONS",
]
