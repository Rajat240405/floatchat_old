"""Canonical ocean region vocabulary (Domain Ontology, Phase 1).

Single source of truth for named ocean regions. Contents relocated *verbatim*
from their previous fragmented homes (behaviour-neutral move):

================================  ==============================================
Ontology field / constant         Previous home(s)
================================  ==============================================
``RegionDefinition.aliases``      ``intent_parser.regex._REGION_SYNONYMS``
``RegionDefinition.polygon``      ``metadata_service.polygons.REGION_POLYGONS``
``RegionDefinition.bbox``         ``metadata_service.regions._BOUNDS``
``place_names``                   ``intent_parser.regex`` (``_OCEAN_REGION_PLACES``,
                                  the gazetteer skip-list inside ``parse``)
``point_in_region``               ``metadata_service.polygons`` (ray-casting test)
``tag_india_region``              ``data_lake.duckdb_lake.get_region_tag`` /
                                  ``build_region_tag``,
                                  ``data_lake.ingest._build_region_tag``,
                                  ``data_lake.phase2_builder._classify_region``
``INDIA_QUERY_REGIONS``           ``query_engine.engine`` (``supported_india_regions``),
                                  ``query_engine.executors.profile``
``INDIA_DEPLOYMENT_BBOX``         ``data_lake.ingest._is_india_region``,
                                  ``data_lake.phase2_builder`` (``INDIA_LAT_MIN`` …)
================================  ==============================================

Region insertion order preserves the legacy ``_REGION_SYNONYMS`` order: the
parser's region matcher returns the *first* matching region, so this ordering
is observable and must not change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple


@dataclass(frozen=True)
class RegionDefinition:
    """Canonical definition of a named ocean region."""

    canonical: str
    """Snake_case identifier used across intents, criteria and lake tags."""
    display_name: str
    """Human-readable English name (e.g. ``Arabian Sea``)."""
    aliases: Tuple[str, ...] = ()
    """Natural-language aliases matched by the deterministic parser."""
    polygon: Tuple[Tuple[float, float], ...] | None = None
    """Closed polygon as (longitude, latitude) vertices (approximate bounds)."""
    bbox: dict[str, float] | None = None
    """Coarse bounding-box pre-filter (lat_min/lat_max/lon_min/lon_max)."""
    place_names: Tuple[str, ...] = ()
    """Place-name spellings that refer to this region. Used by the parser's
    gazetteer skip-list so ocean-region names are never forwarded to live
    geocoding. Empty for regions the legacy skip-list did not cover."""


# --------------------------------------------------------------------------- #
# Canonical regions (13). Order is observable (first-match region extraction)
# and preserved verbatim from the legacy tables.
# --------------------------------------------------------------------------- #

REGIONS: dict[str, RegionDefinition] = {
    "arabian_sea": RegionDefinition(
        canonical="arabian_sea",
        display_name="Arabian Sea",
        aliases=("arabian sea",),
        polygon=(
            (68.0, 23.0),   # Pakistan coast
            (62.0, 25.0),   # Iran/Pakistan border
            (56.0, 25.0),   # Iran coast
            (52.0, 23.0),   # Strait of Hormuz
            (56.0, 12.0),   # Gulf of Aden approach
            (60.0, 6.0),    # Somali coast
            (66.0, 6.0),    # near equator, east of Somalia
            (72.0, 6.0),    # Maldives
            (78.0, 8.0),    # Sri Lanka / India south
            (80.0, 14.0),   # India east coast
            (78.0, 20.0),   # India west coast
            (72.0, 22.0),   # Gujarat
            (68.0, 23.0),   # close
        ),
        bbox={"lat_min": 0.0, "lat_max": 30.0, "lon_min": 45.0, "lon_max": 80.0},
        place_names=("arabian sea", "arabian"),
    ),
    "bay_of_bengal": RegionDefinition(
        canonical="bay_of_bengal",
        display_name="Bay of Bengal",
        aliases=("bay of bengal",),
        polygon=(
            (80.0, 22.0),   # India east coast
            (87.0, 22.0),   # West Bengal / Bangladesh
            (92.0, 21.0),   # Bangladesh coast
            (92.0, 16.0),   # Myanmar north
            (98.0, 12.0),   # Myanmar south
            (98.0, 6.0),    # Andaman Sea
            (95.0, 2.0),    # Nicobar Islands
            (92.0, 6.0),    # Sumatra north tip
            (88.0, 8.0),    # deeper bay
            (80.0, 8.0),    # Sri Lanka east
            (80.0, 22.0),   # close
        ),
        bbox={"lat_min": 0.0, "lat_max": 25.0, "lon_min": 78.0, "lon_max": 100.0},
        place_names=("bay of bengal", "bengal"),
    ),
    "north_atlantic": RegionDefinition(
        canonical="north_atlantic",
        display_name="North Atlantic",
        aliases=("north atlantic",),
        polygon=(
            (-80.0, 0.0),   # South America north
            (-60.0, 0.0),   # Atlantic equator
            (-15.0, 0.0),   # Africa west
            (-10.0, 35.0),  # Gibraltar / Mediterranean
            (-5.0, 45.0),   # Bay of Biscay
            (-10.0, 55.0),  # Ireland west
            (-20.0, 65.0),  # Iceland
            (-45.0, 65.0),  # Greenland south
            (-60.0, 50.0),  # Newfoundland
            (-70.0, 45.0),  # Nova Scotia
            (-80.0, 30.0),  # US east coast
            (-80.0, 0.0),   # close
        ),
        bbox={"lat_min": 0.0, "lat_max": 80.0, "lon_min": -80.0, "lon_max": 20.0},
        place_names=("north atlantic",),
    ),
    "south_atlantic": RegionDefinition(
        canonical="south_atlantic",
        display_name="South Atlantic",
        aliases=("south atlantic",),
        polygon=(
            (-70.0, 0.0),   # South America north
            (-35.0, 0.0),   # Africa west equator
            (10.0, 0.0),    # Africa west
            (20.0, -35.0),  # Africa south
            (20.0, -50.0),  # South Africa
            (0.0, -55.0),   # Mid-Atlantic south
            (-30.0, -55.0), # South Atlantic mid
            (-55.0, -50.0), # South Georgia
            (-65.0, -55.0), # Drake Passage east
            (-65.0, -40.0), # Argentina south
            (-65.0, 0.0),   # close
        ),
        bbox={"lat_min": -60.0, "lat_max": 0.0, "lon_min": -70.0, "lon_max": 20.0},
        place_names=("south atlantic",),
    ),
    "north_pacific": RegionDefinition(
        canonical="north_pacific",
        display_name="North Pacific",
        aliases=("north pacific",),
        polygon=(
            (100.0, 0.0),   # SE Asia
            (140.0, 0.0),   # Indonesia
            (160.0, 10.0),  # Micronesia
            (180.0, 20.0),  # Central Pacific
            (-160.0, 20.0), # Hawaii region
            (-130.0, 25.0), # Baja California
            (-120.0, 30.0), # Mexico west
            (-110.0, 45.0), # US west coast
            (-130.0, 55.0), # Alaska south
            (-170.0, 55.0), # Aleutians
            (170.0, 55.0),  # Bering Sea
            (150.0, 45.0),  # Kamchatka
            (140.0, 35.0),  # Japan
            (120.0, 20.0),  # Philippines / Taiwan
            (100.0, 0.0),   # close
        ),
        bbox={"lat_min": 0.0, "lat_max": 65.0, "lon_min": 100.0, "lon_max": -80.0},
        place_names=("north pacific",),
    ),
    "south_pacific": RegionDefinition(
        canonical="south_pacific",
        display_name="South Pacific",
        aliases=("south pacific",),
        polygon=(
            (140.0, 0.0),   # Indonesia
            (180.0, 0.0),   # Equator central
            (-150.0, 0.0),  # Equator east
            (-80.0, 0.0),   # South America west
            (-80.0, -10.0), # Peru
            (-80.0, -30.0), # Chile
            (-75.0, -55.0), # Cape Horn
            (-120.0, -60.0), # South Pacific south
            (150.0, -60.0),  # South Pacific SE
            (170.0, -45.0),  # New Zealand south
            (150.0, -35.0),  # Australia east
            (145.0, -15.0),  # Papua New Guinea
            (140.0, 0.0),    # close
        ),
        bbox={"lat_min": -60.0, "lat_max": 0.0, "lon_min": 120.0, "lon_max": -70.0},
        place_names=("south pacific",),
    ),
    "indian_ocean": RegionDefinition(
        canonical="indian_ocean",
        display_name="Indian Ocean",
        aliases=("indian ocean",),
        polygon=(
            (20.0, -50.0),  # Southern Ocean boundary
            (20.0, -20.0),  # Madagascar south
            (40.0, -10.0),  # Mozambique
            (50.0, 10.0),   # Somalia
            (57.0, 23.0),   # Oman / Arabian Sea north
            (68.0, 23.0),   # Pakistan
            (80.0, 22.0),   # India
            (95.0, 6.0),    # Andaman Sea
            (105.0, -10.0), # Indonesia west
            (115.0, -35.0), # Australia west
            (115.0, -50.0), # Southern Ocean
            (20.0, -50.0),  # close
        ),
        bbox={"lat_min": -50.0, "lat_max": 30.0, "lon_min": 20.0, "lon_max": 150.0},
        place_names=("indian ocean", "indian"),
    ),
    "southern_ocean": RegionDefinition(
        canonical="southern_ocean",
        display_name="Southern Ocean",
        aliases=("southern ocean",),
        polygon=(
            (-180.0, -50.0),
            (180.0, -50.0),
            (180.0, -80.0),
            (-180.0, -80.0),
            (-180.0, -50.0),
        ),
        bbox={"lat_min": -80.0, "lat_max": -50.0, "lon_min": -180.0, "lon_max": 180.0},
        place_names=("southern ocean",),
    ),
    "mediterranean_sea": RegionDefinition(
        canonical="mediterranean_sea",
        display_name="Mediterranean Sea",
        aliases=("mediterranean", "mediterranean sea"),
        polygon=(
            (-6.0, 36.0),   # Gibraltar
            (-5.0, 37.0),   # Spain south
            (0.0, 39.0),    # Spain east
            (3.0, 42.0),    # France south
            (8.0, 44.0),    # Italy west
            (12.0, 38.0),   # Sicily
            (15.0, 37.0),   # Italy south
            (20.0, 40.0),   # Italy east / Adriatic
            (26.0, 40.0),   # Greece
            (30.0, 36.0),   # Turkey south
            (34.0, 32.0),   # Israel / Lebanon
            (35.0, 31.0),   # Sinai
            (32.0, 30.0),   # Egypt north
            (25.0, 32.0),   # Libya
            (12.0, 33.0),   # Tunisia
            (8.0, 33.0),    # Algeria
            (-6.0, 36.0),   # close
        ),
        bbox={"lat_min": 30.0, "lat_max": 47.0, "lon_min": -6.0, "lon_max": 37.0},
        place_names=("mediterranean",),
    ),
    "red_sea": RegionDefinition(
        canonical="red_sea",
        display_name="Red Sea",
        aliases=("red sea",),
        polygon=(
            (32.0, 30.0),   # Suez
            (35.0, 28.0),   # Sinai east
            (40.0, 20.0),   # Saudi Arabia west
            (45.0, 12.0),   # Yemen
            (43.0, 12.5),   # Bab-el-Mandeb
            (40.0, 18.0),   # Eritrea
            (37.0, 20.0),   # Sudan
            (35.0, 25.0),   # Egypt east
            (32.0, 30.0),   # close
        ),
        bbox={"lat_min": 12.0, "lat_max": 32.0, "lon_min": 32.0, "lon_max": 45.0},
        place_names=("red sea",),
    ),
    "gulf_of_mexico": RegionDefinition(
        canonical="gulf_of_mexico",
        display_name="Gulf of Mexico",
        aliases=("gulf of mexico",),
        polygon=(
            (-98.0, 26.0),  # Mexico east
            (-96.0, 19.0),  # Mexico south
            (-85.0, 18.0),  # Yucatan
            (-83.0, 22.0),  # Cuba west
            (-80.0, 25.0),  # Florida
            (-82.0, 28.0),  # Florida west
            (-88.0, 30.0),  # Louisiana
            (-95.0, 29.0),  # Texas
            (-98.0, 26.0),  # close
        ),
        bbox={"lat_min": 18.0, "lat_max": 31.0, "lon_min": -98.0, "lon_max": -80.0},
        place_names=("gulf of mexico",),
    ),
    "tasman_sea": RegionDefinition(
        canonical="tasman_sea",
        display_name="Tasman Sea",
        aliases=("tasman sea",),
        polygon=(
            (150.0, -25.0), # Australia east
            (155.0, -20.0), # Coral Sea
            (165.0, -20.0), # Vanuatu
            (175.0, -25.0), # New Zealand north
            (175.0, -40.0), # New Zealand south
            (170.0, -48.0), # Stewart Island
            (160.0, -50.0), # South of NZ
            (145.0, -45.0), # Tasmania
            (145.0, -38.0), # Australia SE
            (150.0, -25.0), # close
        ),
        bbox={"lat_min": -50.0, "lat_max": -20.0, "lon_min": 145.0, "lon_max": 175.0},
        place_names=(),
    ),
    "caribbean_sea": RegionDefinition(
        canonical="caribbean_sea",
        display_name="Caribbean Sea",
        aliases=("caribbean sea",),
        polygon=(
            (-88.0, 18.0),  # Honduras
            (-83.0, 15.0),  # Nicaragua
            (-77.0, 8.0),   # Panama
            (-80.0, 7.0),   # Colombia
            (-77.0, 10.0),  # Venezuela
            (-62.0, 11.0),  # Trinidad
            (-60.0, 14.0),  # Lesser Antilles
            (-65.0, 18.0),  # Puerto Rico
            (-75.0, 20.0),  # Cuba east
            (-85.0, 23.0),  # Cuba west / Yucatan
            (-88.0, 18.0),  # close
        ),
        bbox={"lat_min": 7.0, "lat_max": 28.0, "lon_min": -88.0, "lon_max": -58.0},
        place_names=(),
    ),
}


# --------------------------------------------------------------------------- #
# Derived constants
# --------------------------------------------------------------------------- #

#: Regions served by the local India-region data lake. Formerly the literal
#: ``{"arabian_sea", "bay_of_bengal"}`` sets in ``query_engine.engine`` and
#: ``query_engine.executors.profile``.
INDIA_QUERY_REGIONS: frozenset[str] = frozenset({"arabian_sea", "bay_of_bengal"})

#: Outer bounding box of the India deployment region. Formerly the duplicated
#: scalars in ``data_lake.ingest._is_india_region`` and
#: ``data_lake.phase2_builder`` (``INDIA_LAT_MIN`` … ``INDIA_LON_MAX``).
INDIA_DEPLOYMENT_BBOX: dict[str, float] = {
    "lat_min": -10.0,
    "lat_max": 30.0,
    "lon_min": 40.0,
    "lon_max": 100.0,
}

#: Place-name spellings that resolve to ocean regions. The parser skips live
#: geocoding for these (verbatim union of the legacy ``_OCEAN_REGION_PLACES``).
OCEAN_REGION_PLACE_NAMES: frozenset[str] = frozenset(
    name for definition in REGIONS.values() for name in definition.place_names
)


# --------------------------------------------------------------------------- #
# Point-in-polygon (relocated from metadata_service.polygons — identical code)
# --------------------------------------------------------------------------- #

def _point_in_polygon(lon: float, lat: float, polygon: tuple[tuple[float, float], ...]) -> bool:
    """Ray-casting point-in-polygon test.

    Args:
        lon: Longitude of the point.
        lat: Latitude of the point.
        polygon: Sequence of (longitude, latitude) vertices.

    Returns:
        True if the point is inside the polygon.
    """
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        # Check if the edge (j -> i) straddles the horizontal line at lat
        if ((yi > lat) != (yj > lat)):
            # Compute x-coordinate of intersection
            x_intersect = xi + (lat - yi) * (xj - xi) / (yj - yi)
            if lon < x_intersect:
                inside = not inside
        j = i
    return inside


def point_in_region(lon: float, lat: float, region_name: str) -> bool:
    """Return True if (lon, lat) lies inside the named region polygon."""
    definition = REGIONS.get(region_name.lower().strip().replace(" ", "_"))
    if definition is None or definition.polygon is None:
        return True  # Unknown region — don't filter
    return _point_in_polygon(lon, lat, definition.polygon)


def tag_india_region(lat: float, lon: float) -> str | None:
    """Classify a coordinate into an India sub-region tag.

    Returns ``"arabian_sea"`` or ``"bay_of_bengal"`` when the coordinate falls
    inside the respective polygon, otherwise ``None`` (the legacy
    ``DuckDBDataLake.get_region_tag`` / module-level ``build_region_tag``
    semantics). ETL builders append their own ``"indian_ocean"`` fallback.
    """
    if point_in_region(lon, lat, "arabian_sea"):
        return "arabian_sea"
    if point_in_region(lon, lat, "bay_of_bengal"):
        return "bay_of_bengal"
    return None
