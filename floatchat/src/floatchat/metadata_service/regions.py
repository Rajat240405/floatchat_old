"""Named ocean region definitions.

Regions are normalised to lowercase with underscores.
Two filtering strategies are supported:

1. **Bounding-box** (fast, approximate) — used when no polygon is available.
2. **Polygon** (accurate) — used for all defined regions.

Sources: broadly accepted oceanographic boundaries.
"""

from typing import TypedDict

from floatchat.metadata_service.polygons import REGION_POLYGONS, point_in_region


class _Bounds(TypedDict):
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float


# Bounding boxes kept as coarse pre-filters for performance.
# The polygon test (applied after) is the authoritative filter.
_BOUNDS: dict[str, _Bounds] = {
    "arabian_sea": {
        "lat_min": 0.0,
        "lat_max": 30.0,
        "lon_min": 45.0,
        "lon_max": 80.0,
    },
    "bay_of_bengal": {
        "lat_min": 0.0,
        "lat_max": 25.0,
        "lon_min": 78.0,
        "lon_max": 100.0,
    },
    "north_atlantic": {
        "lat_min": 0.0,
        "lat_max": 80.0,
        "lon_min": -80.0,
        "lon_max": 20.0,
    },
    "south_atlantic": {
        "lat_min": -60.0,
        "lat_max": 0.0,
        "lon_min": -70.0,
        "lon_max": 20.0,
    },
    "north_pacific": {
        "lat_min": 0.0,
        "lat_max": 65.0,
        "lon_min": 100.0,
        "lon_max": -80.0,  # crosses dateline; handled specially
    },
    "south_pacific": {
        "lat_min": -60.0,
        "lat_max": 0.0,
        "lon_min": 120.0,
        "lon_max": -70.0,
    },
    "indian_ocean": {
        "lat_min": -50.0,
        "lat_max": 30.0,
        "lon_min": 20.0,
        "lon_max": 150.0,
    },
    "southern_ocean": {
        "lat_min": -80.0,
        "lat_max": -50.0,
        "lon_min": -180.0,
        "lon_max": 180.0,
    },
    "mediterranean_sea": {
        "lat_min": 30.0,
        "lat_max": 47.0,
        "lon_min": -6.0,
        "lon_max": 37.0,
    },
    "red_sea": {
        "lat_min": 12.0,
        "lat_max": 32.0,
        "lon_min": 32.0,
        "lon_max": 45.0,
    },
    "gulf_of_mexico": {
        "lat_min": 18.0,
        "lat_max": 31.0,
        "lon_min": -98.0,
        "lon_max": -80.0,
    },
    "tasman_sea": {
        "lat_min": -50.0,
        "lat_max": -20.0,
        "lon_min": 145.0,
        "lon_max": 175.0,
    },
    "caribbean_sea": {
        "lat_min": 7.0,
        "lat_max": 28.0,
        "lon_min": -88.0,
        "lon_max": -58.0,
    },
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
