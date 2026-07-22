"""Geographic polygon definitions and point-in-polygon tests for ocean regions.

Uses the ray-casting algorithm (no external dependencies).
"""

from typing import TypedDict


class PolygonRegion(TypedDict):
    """A named region defined by a closed polygon."""

    name: str
    vertices: list[tuple[float, float]]
    """List of (longitude, latitude) tuples forming a closed polygon."""


# --------------------------------------------------------------------------- #
# Polygon definitions — approximate but accurate enough for Argo metadata.
# Sources: broadly accepted oceanographic boundaries.
# --------------------------------------------------------------------------- #

# Arabian Sea: bounded by India, Pakistan, Iran, Arabian Peninsula, Horn of Africa
_ARABIAN_SEA: list[tuple[float, float]] = [
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
]

# Bay of Bengal: bounded by India, Bangladesh, Myanmar, Andaman Islands, Sumatra
_BAY_OF_BENGAL: list[tuple[float, float]] = [
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
]

# North Atlantic
_NORTH_ATLANTIC: list[tuple[float, float]] = [
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
]

# South Atlantic
_SOUTH_ATLANTIC: list[tuple[float, float]] = [
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
]

# North Pacific
_NORTH_PACIFIC: list[tuple[float, float]] = [
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
]

# South Pacific
_SOUTH_PACIFIC: list[tuple[float, float]] = [
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
]

# Indian Ocean (broader than Arabian Sea + Bay of Bengal)
_INDIAN_OCEAN: list[tuple[float, float]] = [
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
]

# Southern Ocean
_SOUTHERN_OCEAN: list[tuple[float, float]] = [
    (-180.0, -50.0),
    (180.0, -50.0),
    (180.0, -80.0),
    (-180.0, -80.0),
    (-180.0, -50.0),
]

# Mediterranean Sea
_MEDITERRANEAN_SEA: list[tuple[float, float]] = [
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
]

# Red Sea
_RED_SEA: list[tuple[float, float]] = [
    (32.0, 30.0),   # Suez
    (35.0, 28.0),   # Sinai east
    (40.0, 20.0),   # Saudi Arabia west
    (45.0, 12.0),   # Yemen
    (43.0, 12.5),   # Bab-el-Mandeb
    (40.0, 18.0),   # Eritrea
    (37.0, 20.0),   # Sudan
    (35.0, 25.0),   # Egypt east
    (32.0, 30.0),   # close
]

# Gulf of Mexico
_GULF_OF_MEXICO: list[tuple[float, float]] = [
    (-98.0, 26.0),  # Mexico east
    (-96.0, 19.0),  # Mexico south
    (-85.0, 18.0),  # Yucatan
    (-83.0, 22.0),  # Cuba west
    (-80.0, 25.0),  # Florida
    (-82.0, 28.0),  # Florida west
    (-88.0, 30.0),  # Louisiana
    (-95.0, 29.0),  # Texas
    (-98.0, 26.0),  # close
]

# Tasman Sea
_TASMAN_SEA: list[tuple[float, float]] = [
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
]

# Caribbean Sea
_CARIBBEAN_SEA: list[tuple[float, float]] = [
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
]


REGION_POLYGONS: dict[str, list[tuple[float, float]]] = {
    "arabian_sea": _ARABIAN_SEA,
    "bay_of_bengal": _BAY_OF_BENGAL,
    "north_atlantic": _NORTH_ATLANTIC,
    "south_atlantic": _SOUTH_ATLANTIC,
    "north_pacific": _NORTH_PACIFIC,
    "south_pacific": _SOUTH_PACIFIC,
    "indian_ocean": _INDIAN_OCEAN,
    "southern_ocean": _SOUTHERN_OCEAN,
    "mediterranean_sea": _MEDITERRANEAN_SEA,
    "red_sea": _RED_SEA,
    "gulf_of_mexico": _GULF_OF_MEXICO,
    "tasman_sea": _TASMAN_SEA,
    "caribbean_sea": _CARIBBEAN_SEA,
}


def _point_in_polygon(lon: float, lat: float, polygon: list[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon test.

    Args:
        lon: Longitude of the point.
        lat: Latitude of the point.
        polygon: List of (longitude, latitude) vertices.

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
    polygon = REGION_POLYGONS.get(region_name.lower().strip().replace(" ", "_"))
    if polygon is None:
        return True  # Unknown region — don't filter
    return _point_in_polygon(lon, lat, polygon)
