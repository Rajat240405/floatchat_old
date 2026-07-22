"""Place-Name Gazetteer with 3-layer geocoding fallback chain (Phase 5 Part C).

Translates human place names (e.g., "Kerala coast", "Mumbai") into lat/lon
coordinates for use with radius_search and nearest_float intents.

Fallback chain:
1. Local Gazetteer Table — hardcoded dictionary of common Indian coastal locations
2. Fuzzy Matching — Levenshtein-based matching against the local table
3. Live Geocoding Fallback — Nominatim (OpenStreetMap) API with caching
"""

from __future__ import annotations

import difflib
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Local Gazetteer Table — Common Indian coastal locations
# --------------------------------------------------------------------------- #
# Each entry: name -> (lat, lon, default_radius_km)
# Coordinates are approximate centroids for coastal search areas.

_LOCAL_GAZETTEER: dict[str, dict[str, Any]] = {
    # --- Major Cities (West Coast) ---
    "mumbai": {"lat": 19.07, "lon": 72.87, "radius_km": 100},
    "bombay": {"lat": 19.07, "lon": 72.87, "radius_km": 100},
    "goa": {"lat": 15.30, "lon": 73.90, "radius_km": 100},
    "mangalore": {"lat": 12.87, "lon": 74.88, "radius_km": 100},
    "mangaluru": {"lat": 12.87, "lon": 74.88, "radius_km": 100},
    "kochi": {"lat": 9.93, "lon": 76.26, "radius_km": 100},
    "cochin": {"lat": 9.93, "lon": 76.26, "radius_km": 100},
    "kozhikode": {"lat": 11.25, "lon": 75.77, "radius_km": 100},
    "calicut": {"lat": 11.25, "lon": 75.77, "radius_km": 100},
    "kannur": {"lat": 11.87, "lon": 75.37, "radius_km": 100},
    "trivandrum": {"lat": 8.52, "lon": 76.94, "radius_km": 100},
    "thiruvananthapuram": {"lat": 8.52, "lon": 76.94, "radius_km": 100},
    "ratnagiri": {"lat": 16.99, "lon": 73.30, "radius_km": 100},
    "karwar": {"lat": 14.81, "lon": 74.13, "radius_km": 100},
    "uvaasai": {"lat": 19.38, "lon": 72.84, "radius_km": 80},
    "vasai": {"lat": 19.38, "lon": 72.84, "radius_km": 80},
    "alibaug": {"lat": 18.64, "lon": 72.87, "radius_km": 80},
    "alibag": {"lat": 18.64, "lon": 72.87, "radius_km": 80},

    # --- Major Cities (East Coast) ---
    "chennai": {"lat": 13.08, "lon": 80.27, "radius_km": 100},
    "madras": {"lat": 13.08, "lon": 80.27, "radius_km": 100},
    "vizag": {"lat": 17.69, "lon": 83.22, "radius_km": 100},
    "visakhapatnam": {"lat": 17.69, "lon": 83.22, "radius_km": 100},
    "kakinada": {"lat": 16.94, "lon": 82.24, "radius_km": 100},
    "pondicherry": {"lat": 11.94, "lon": 79.81, "radius_km": 80},
    "puducherry": {"lat": 11.94, "lon": 79.81, "radius_km": 80},
    "tuticorin": {"lat": 8.76, "lon": 78.13, "radius_km": 100},
    "thoothukudi": {"lat": 8.76, "lon": 78.13, "radius_km": 100},
    "rameswaram": {"lat": 9.28, "lon": 79.31, "radius_km": 80},
    "kanyakumari": {"lat": 8.08, "lon": 77.55, "radius_km": 80},
    "cape comorin": {"lat": 8.08, "lon": 77.55, "radius_km": 80},
    "nellore": {"lat": 14.44, "lon": 79.99, "radius_km": 100},
    "machilipatnam": {"lat": 16.17, "lon": 81.13, "radius_km": 100},
    "paradip": {"lat": 20.27, "lon": 86.68, "radius_km": 100},
    "bhubaneswar": {"lat": 20.29, "lon": 85.82, "radius_km": 150},
    "kolkata": {"lat": 22.57, "lon": 88.36, "radius_km": 150},
    "calcutta": {"lat": 22.57, "lon": 88.36, "radius_km": 150},

    # --- Regional Coast Names ---
    "kerala coast": {"lat": 9.9, "lon": 76.3, "radius_km": 150},
    "kerala": {"lat": 9.9, "lon": 76.3, "radius_km": 150},
    "tamil nadu coast": {"lat": 11.5, "lon": 79.5, "radius_km": 200},
    "tamil nadu": {"lat": 11.5, "lon": 79.5, "radius_km": 200},
    "andhra coast": {"lat": 15.5, "lon": 81.5, "radius_km": 200},
    "andhra pradesh": {"lat": 15.5, "lon": 81.5, "radius_km": 200},
    "andhra": {"lat": 15.5, "lon": 81.5, "radius_km": 200},
    "odisha coast": {"lat": 20.0, "lon": 86.5, "radius_km": 200},
    "odisha": {"lat": 20.0, "lon": 86.5, "radius_km": 200},
    "orissa coast": {"lat": 20.0, "lon": 86.5, "radius_km": 200},
    "orissa": {"lat": 20.0, "lon": 86.5, "radius_km": 200},
    "goa coast": {"lat": 15.30, "lon": 73.90, "radius_km": 100},
    "karnataka coast": {"lat": 13.5, "lon": 74.5, "radius_km": 200},
    "karnataka": {"lat": 13.5, "lon": 74.5, "radius_km": 200},
    "maharashtra coast": {"lat": 18.0, "lon": 73.0, "radius_km": 200},
    "maharashtra": {"lat": 18.0, "lon": 73.0, "radius_km": 200},
    "gujarat coast": {"lat": 22.0, "lon": 69.0, "radius_km": 200},
    "gujarat": {"lat": 22.0, "lon": 69.0, "radius_km": 200},
    "west coast": {"lat": 15.0, "lon": 74.0, "radius_km": 300},
    "east coast": {"lat": 14.0, "lon": 80.5, "radius_km": 300},
    # Phase 5 fix: "bengal" and related names
    "bengal": {"lat": 21.5, "lon": 88.5, "radius_km": 300},
    "west bengal": {"lat": 21.5, "lon": 88.5, "radius_km": 300},
    "west bengal coast": {"lat": 21.5, "lon": 88.5, "radius_km": 300},
    "bay of bengal": {"lat": 15.0, "lon": 85.0, "radius_km": 500},

    # --- Offshore / Ocean features ---
    "lakshadweep": {"lat": 10.55, "lon": 72.63, "radius_km": 150},
    "andaman": {"lat": 12.5, "lon": 92.7, "radius_km": 200},
    "andaman islands": {"lat": 12.5, "lon": 92.7, "radius_km": 200},
    "nicobar": {"lat": 7.5, "lon": 93.5, "radius_km": 200},
    "nicobar islands": {"lat": 7.5, "lon": 93.5, "radius_km": 200},
    "gulfof mannar": {"lat": 9.0, "lon": 79.0, "radius_km": 150},
    "gulf of mannar": {"lat": 9.0, "lon": 79.0, "radius_km": 150},
    "palk strait": {"lat": 9.5, "lon": 79.5, "radius_km": 100},
    "gulf of khambhat": {"lat": 21.5, "lon": 72.5, "radius_km": 150},
    "gulf of kutch": {"lat": 22.5, "lon": 69.5, "radius_km": 150},
    "sundarbans": {"lat": 21.9, "lon": 89.0, "radius_km": 150},
    "coromandel coast": {"lat": 12.5, "lon": 80.2, "radius_km": 200},
    "malabar coast": {"lat": 11.0, "lon": 75.5, "radius_km": 200},
    "konkan coast": {"lat": 17.0, "lon": 73.3, "radius_km": 200},
    "konkan": {"lat": 17.0, "lon": 73.3, "radius_km": 200},

    # --- International nearby (Sri Lanka etc) ---
    "sri lanka": {"lat": 7.87, "lon": 80.77, "radius_km": 200},
    "colombo": {"lat": 6.93, "lon": 79.86, "radius_km": 100},
    "maldives": {"lat": 3.20, "lon": 73.22, "radius_km": 200},
}


# --------------------------------------------------------------------------- #
# Cache file for Nominatim results (persisted to avoid re-querying)
# --------------------------------------------------------------------------- #

_CACHE_DIR = Path(".data_lake") / ".gazetteer_cache"


def _get_cache_path() -> Path:
    """Return the path to the JSON cache file."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR / "nominatim_cache.json"


def _load_cache() -> dict[str, dict[str, Any]]:
    """Load the Nominatim results cache from disk."""
    cache_path = _get_cache_path()
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load gazetteer cache: %s", exc)
    return {}


def _save_cache(cache: dict[str, dict[str, Any]]) -> None:
    """Save the Nominatim results cache to disk."""
    cache_path = _get_cache_path()
    try:
        cache_path.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.warning("Failed to save gazetteer cache: %s", exc)


# --------------------------------------------------------------------------- #
# Fuzzy matching against local gazetteer
# --------------------------------------------------------------------------- #

def _fuzzy_match_local(place_name: str, cutoff: float = 0.8) -> str | None:
    """Try fuzzy matching a place name against the local gazetteer keys.
    
    Returns the best match key if similarity is above cutoff, else None.
    """
    lower = place_name.lower().strip()
    
    # Exact match first
    if lower in _LOCAL_GAZETTEER:
        return lower
    
    # Try substring matching (e.g., "Keral coast" contains "keral" which is close to "kerala")
    keys = list(_LOCAL_GAZETTEER.keys())
    
    # difflib close matches
    matches = difflib.get_close_matches(lower, keys, n=1, cutoff=cutoff)
    if matches:
        return matches[0]
    
    # Try removing "coast", "region" etc. and matching
    stripped = lower.replace("coast", "").replace("region", "").replace("area", "").replace("near", "").strip()
    if stripped and stripped != lower:
        if stripped in _LOCAL_GAZETTEER:
            return stripped
        matches = difflib.get_close_matches(stripped, keys, n=1, cutoff=cutoff)
        if matches:
            return matches[0]
    
    return None


# --------------------------------------------------------------------------- #
# Nominatim API fallback
# --------------------------------------------------------------------------- #

def _nominatim_geocode(place_name: str) -> dict[str, Any] | None:
    """Query OpenStreetMap Nominatim API for place coordinates.
    
    Returns dict with lat, lon, display_name or None if not found.
    Follows Nominatim usage policy: 1 request/second, custom User-Agent.

    P4 #1: Gated by FLOATCHAT_ALLOW_LIVE_GEOCODING (default: True). When False,
    this function is a no-op (returns None) so the chat pipeline stays fully
    offline — only the local gazetteer table + cache are used.
    """
    from floatchat.config import settings
    if not settings.allow_live_geocoding:
        logger.info(
            "Live geocoding disabled (FLOATCHAT_ALLOW_LIVE_GEOCODING=False) — "
            "skipping Nominatim for %r",
            place_name,
        )
        return None

    import httpx
    
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": place_name,
        "format": "json",
        "limit": 1,
        "countrycodes": "in,lk,mv,bd,pk",  # India + nearby countries
    }
    headers = {
        "User-Agent": "FloatChat-ArgoBot/1.0 (INCOIS internship project)"
    }
    
    try:
        with httpx.Client(timeout=10, follow_redirects=True) as client:
            resp = client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            results = resp.json()
            
            if results and len(results) > 0:
                result = results[0]
                return {
                    "lat": float(result["lat"]),
                    "lon": float(result["lon"]),
                    "radius_km": 100,  # default radius for Nominatim results
                    "display_name": result.get("display_name", place_name),
                    "source": "nominatim",
                }
            else:
                logger.info("Nominatim: no results for '%s'", place_name)
                return None
                
    except Exception as exc:
        logger.warning("Nominatim geocoding failed for '%s': %s", place_name, exc)
        return None


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def resolve_place_name(place_name: str) -> dict[str, Any] | None:
    """Resolve a human place name to coordinates via 3-layer fallback.
    
    Args:
        place_name: Human-readable place name (e.g., "Kerala coast", "Mumbai")
    
    Returns:
        dict with keys: lat, lon, radius_km, place_name (resolved), source
        or None if the place cannot be resolved.
    """
    if not place_name or not place_name.strip():
        return None
    
    lower = place_name.lower().strip()
    
    # Layer 1: Exact local gazetteer match
    if lower in _LOCAL_GAZETTEER:
        entry = _LOCAL_GAZETTEER[lower]
        logger.info("Gazetteer: exact match '%s' -> (%s, %s)", lower, entry["lat"], entry["lon"])
        return {
            "lat": entry["lat"],
            "lon": entry["lon"],
            "radius_km": entry["radius_km"],
            "place_name": lower,
            "source": "local_gazetteer",
        }
    
    # Layer 1b: Check Nominatim cache
    cache = _load_cache()
    if lower in cache:
        cached = cache[lower]
        logger.info("Gazetteer: cache hit '%s' -> (%s, %s)", lower, cached["lat"], cached["lon"])
        return {
            "lat": cached["lat"],
            "lon": cached["lon"],
            "radius_km": cached.get("radius_km", 100),
            "place_name": cached.get("display_name", lower),
            "source": "nominatim_cache",
        }
    
    # Layer 2: Fuzzy match against local gazetteer
    fuzzy_key = _fuzzy_match_local(lower)
    if fuzzy_key:
        entry = _LOCAL_GAZETTEER[fuzzy_key]
        logger.info("Gazetteer: fuzzy match '%s' -> '%s' -> (%s, %s)", lower, fuzzy_key, entry["lat"], entry["lon"])
        return {
            "lat": entry["lat"],
            "lon": entry["lon"],
            "radius_km": entry["radius_km"],
            "place_name": fuzzy_key,
            "source": "local_gazetteer_fuzzy",
        }
    
    # Layer 3: Nominatim API fallback
    result = _nominatim_geocode(place_name)
    if result is not None:
        # Cache the result for future use
        cache[lower] = result
        _save_cache(cache)
        logger.info("Gazetteer: Nominatim resolved '%s' -> (%s, %s) [cached]", 
                    place_name, result["lat"], result["lon"])
        return {
            "lat": result["lat"],
            "lon": result["lon"],
            "radius_km": result.get("radius_km", 100),
            "place_name": result.get("display_name", place_name),
            "source": "nominatim",
        }
    
    # All layers exhausted — return None
    logger.info("Gazetteer: could not resolve '%s' through any layer", place_name)
    return None


def get_gazetteer_entries() -> list[str]:
    """Return all place names in the local gazetteer (for testing/debugging)."""
    return sorted(_LOCAL_GAZETTEER.keys())
