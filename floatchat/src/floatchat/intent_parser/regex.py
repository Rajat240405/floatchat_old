"""Regex-based intent parser (Phase 5 — with gazetteer + expanded synonyms).

Extracts structured intent from natural language using compiled regular
expressions and synonym tables. No external LLM required.

Supports a wide variety of natural-language query patterns including
variable synonyms, optional regions, years, float IDs, and place-name
geocoding (Phase 5 Part D).
"""

import logging
import re

from floatchat.exceptions import IntentParseError
from floatchat.intent_parser.base import AbstractIntentParser
from floatchat.intent_parser.fuzzy import correct_variables_with_fuzzy
from floatchat.intent_parser.gazetteer import resolve_place_name
from floatchat.models import ParsedIntent
from floatchat.query_normalizer import (
    AbstractQueryNormalizer,
    FallbackQueryNormalizer,
)

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Variable synonyms (Phase 5 Part B — expanded)
# --------------------------------------------------------------------------- #
# Maps canonical Argo names → list of natural-language synonyms.
# Synonyms are matched with word boundaries where appropriate.
_VARIABLE_SYNONYMS: dict[str, list[str]] = {
    "DOXY": [
        "oxygen",
        "dissolved oxygen",
        "doxy",
        "o2",
        "dox",
        "oxy",
        "dissolved o2",
    ],
    "CHLA": [
        "chlorophyll",
        "chlorophyll-a",
        "chla",
        "chlorophyll a",
        "chl",
        "chl-a",
        "phytoplankton",
    ],
    "BBP700": [
        "backscattering",
        "bbp700",
        "particle backscattering",
        "backscatter",
        "bbp",
        "particulate backscatter",
    ],
    "NITRATE": [
        "nitrate",
        "no3",
        "nitrogen",
    ],
    "PH_IN_SITU_TOTAL": [
        "ph",
        "acidity",
        "ph in situ total",
        "ph level",
    ],
    "DOWNWELLING_PAR": [
        "par",
        "photosynthetically active radiation",
        "downwelling par",
        "sunlight",
    ],
    "DOWN_IRRADIANCE380": [
        "irradiance 380",
        "down irradiance 380",
        "ir380",
    ],
    "DOWN_IRRADIANCE412": [
        "irradiance 412",
        "down irradiance 412",
        "ir412",
    ],
    "DOWN_IRRADIANCE490": [
        "irradiance 490",
        "down irradiance 490",
        "ir490",
    ],
    "TEMP": [
        "temperature",
        "temp",
        "sst",
        "water temp",
    ],
    "PSAL": [
        "salinity",
        "psal",
        "salt",
    ],
}

# Build regex patterns for each canonical variable.
# Longer synonyms are checked first to avoid partial matches.
_VAR_PATTERNS: list[tuple[str, re.Pattern]] = []
for canonical, synonyms in _VARIABLE_SYNONYMS.items():
    # Sort by length descending so "dissolved oxygen" matches before "oxygen"
    sorted_syns = sorted(synonyms + [canonical.lower()], key=len, reverse=True)
    escaped = [re.escape(s) for s in sorted_syns]
    pattern = re.compile(r"\b(?:" + "|".join(escaped) + r")\b", re.IGNORECASE)
    _VAR_PATTERNS.append((canonical, pattern))

# --------------------------------------------------------------------------- #
# Region synonyms
# --------------------------------------------------------------------------- #
_REGION_SYNONYMS: dict[str, list[str]] = {
    "arabian_sea": ["arabian sea"],
    "bay_of_bengal": ["bay of bengal"],
    "north_atlantic": ["north atlantic"],
    "south_atlantic": ["south atlantic"],
    "north_pacific": ["north pacific"],
    "south_pacific": ["south pacific"],
    "indian_ocean": ["indian ocean"],
    "southern_ocean": ["southern ocean"],
    "mediterranean_sea": ["mediterranean", "mediterranean sea"],
    "red_sea": ["red sea"],
    "gulf_of_mexico": ["gulf of mexico"],
    "tasman_sea": ["tasman sea"],
    "caribbean_sea": ["caribbean sea"],
}

# Build regex patterns for regions (phrases with spaces need special handling).
_REGION_PATTERNS: list[tuple[str, re.Pattern]] = []
for canonical, synonyms in _REGION_SYNONYMS.items():
    all_names = sorted(synonyms + [canonical.replace("_", " ")], key=len, reverse=True)
    escaped = [re.escape(s) for s in all_names]
    pattern = re.compile(r"(?:" + "|".join(escaped) + r")", re.IGNORECASE)
    _REGION_PATTERNS.append((canonical, pattern))

# --------------------------------------------------------------------------- #
# Intent detection patterns
# --------------------------------------------------------------------------- #
_INTENT_PROFILE = re.compile(
    r"\b(profile|plot|show|graph|display|visuali[sz]e|get|fetch)\b", re.IGNORECASE
)
_INTENT_REGION_SEARCH = re.compile(
    r"\b(conditions?|temperature|salinity|oxygen|chlorophyll|doxy|chla|"
    r"nitrate|ph|var|variables?)\s+(?:(?:in|for|over|at|across|within|of)\s+)?(?:the\s+)?"
    r"(arabi(?:an\s+sea)?|bay\s+of\s+bengal|bengal|"
    r"indian\s+ocean|indian)\b",
    re.IGNORECASE,
)
_INTENT_TS = re.compile(r"\b(time.?series|trend|over time|temporal|since|from)\b", re.IGNORECASE)
_INTENT_TRAJ = re.compile(r"\b(traject(?:ory|ories)?|path|track|route|drift)\b", re.IGNORECASE)
_INTENT_COMP = re.compile(r"\b(compar(?:e|ing|ison|isons)?|vs\.?|versus|difference|diff|against)\b", re.IGNORECASE)
_INTENT_HOVMOLLER = re.compile(
    r"\b(hovm[öo]ller|depth.?time|depth.?vs.?time|time.?vs.?depth|contour(?:.?plot)?|heatmap)\b",
    re.IGNORECASE,
)
_INTENT_TS_DIAGRAM = re.compile(
    r"\b(t.?s\s+diagram|temperature.?salinity\s+diagram|t.?s\s+plot|temperature.?salinity\s+plot|ts\s+diagram|t.?s\s+curve)\b",
    re.IGNORECASE,
)

# Phase 3: Spatial and metadata query patterns
_INTENT_NEAREST = re.compile(
    r"\b(nearest|closest)\b.*?\bfloat\b|\bfloat\b.*?\b(nearest|closest)\b|\bclosest float\b|\bnearest float\b|\bnearest to\b|\bclosest to\b",
    re.IGNORECASE,
)
_INTENT_RADIUS = re.compile(
    r"\b(within\s+\d+\s*km|\b\d+\s*km\s*radius|within\s+radius|\bfloats?\s+within|\bfloats?\s+near)\b",
    re.IGNORECASE,
)
_INTENT_METADATA = re.compile(
    r"\b(sensors?|metadata|status|last\s+report|first\s+report|first\s+profile|deployed|deployment|parking\s+depth|profiler|dac|institution|registry|owner|owns?|operated\s+by|managed\s+by|platform\s+(?:type|info|information)|info(?:rmation)?|details|manufacturer|battery)\b",
    re.IGNORECASE,
)
_INTENT_COUNT = re.compile(
    r"\b(how many|count|number of|total profiles|is there|are there|do we have|any data|data exist)\b",
    re.IGNORECASE,
)

# --------------------------------------------------------------------------- #
# Phase 5 Part D: Place-name extraction pattern
# --------------------------------------------------------------------------- #
# Phase 5: Place-name extraction — handles trailing distance patterns
# e.g. "floats near bhandara 1000 km", "floats near bhandara in range of 500km"
_PLACE_SPATIAL_RE = re.compile(
    r"(?:within\s+(?:\d+(?:\.\d+)?)\s*km\s+(?:of|from)\s+|"
    r"nearest\s+(?:float\s+)?(?:to|from|of)\s+|"
    r"closest\s+(?:float\s+)?(?:to|from|of)\s+|"
    r"floats?\s+(?:near|around|off|by)\s+|"
    r"(?:\d+(?:\.\d+)?)\s*km\s+(?:radius\s+)?(?:around|from|of|near)\s+)"
    r"(?:the\s+)?"
    r"([A-Za-z][A-Za-z\s]+?)"
    r"(?:\s*$|\s*[,.]"
    r"|\s+(?:\d+(?:\.\d+)?)\s*k(?:m|ilometers?)\b"
    r"|\s+in\s+(?:range\s+of\s+|the\s+range\s+of\s+)?(?:\d+(?:\.\d+)?)\s*k(?:m|ilometers?)\b"
    r"|\s+(?:within|for|with)\b"
    r"|\s+in\s+(?:the\s+)?(?:arabian|bay)\b"
    r"|\s+during\b"
    # P1 fix: stop the place-name capture at spatial/proximity prepositions and
    # the standalone article "the" so queries like "near Goa around the last
    # monsoon" yield "Goa" instead of "Goa around the".
    r"|\s+(?:around|off|by)\b"
    r"|\s+the\b"
    r"|\s+(?:last|next|this|past|previous|current)\s+(?:monsoon|winter|summer|spring|autumn|fall|pre-?monsoon|post-?monsoon|northeast|ne|sw|southwest|year|month|week)\b"
    r"|(?=\s+\d+\s*k))",
    re.IGNORECASE,
)

# --------------------------------------------------------------------------- #
# Conversational follow-up patterns
# --------------------------------------------------------------------------- #
_CONVERSATIONAL_VARIABLE = re.compile(
    r"\b(actually|instead|now|what about|how about|and)\b.*?(oxygen|dissolved oxygen|doxy|o2|"
    r"chlorophyll|chlorophyll-a|chla|chlorophyll a|"
    r"backscattering|bbp700|particle backscattering|backscatter|"
    r"nitrate|no3|ph|acidity|ph in situ total|"
    r"par|photosynthetically active radiation|downwelling par|"
    r"irradiance 380|down irradiance 380|irradiance 412|down irradiance 412|"
    r"irradiance 490|down irradiance 490|"
    r"temperature|temp|salinity|psal|salt|explain)",
    re.IGNORECASE,
)
_CONVERSATIONAL_COMPARISON = re.compile(
    r"\b(compar(?:e|ing)?\s+(?:with|against)|vs\.?|versus)\b", re.IGNORECASE
)
_CONVERSATIONAL_REGION = re.compile(
    r"\b(now|instead)\s+in\b", re.IGNORECASE
)
_CONVERSATIONAL_SAME_FLOAT = re.compile(
    r"\b(same float|that float|this float)\b", re.IGNORECASE
)
_CONVERSATIONAL_SAME_REGION = re.compile(
    r"\b(same region|same area|same place)\b", re.IGNORECASE
)
_CONVERSATIONAL_SAME_VARIABLE = re.compile(
    r"\b(same variable|same thing)\b", re.IGNORECASE
)
_CONVERSATIONAL_LATEST_PROFILE = re.compile(
    r"\b(latest|most recent|last)\s+(?:profile|cycle)\b", re.IGNORECASE
)
_CONVERSATIONAL_LATEST_FLOAT = re.compile(
    r"\b(latest|newest|most recent|recent)\s+float\b", re.IGNORECASE
)
_CONVERSATIONAL_PREVIOUS_PROFILE = re.compile(
    r"\b(previous|earlier|last)\s+(?:profile|cycle)\b", re.IGNORECASE
)
_CONVERSATIONAL_NEXT_PROFILE = re.compile(
    r"\b(next|following)\s+(?:profile|cycle)\b", re.IGNORECASE
)
_CONVERSATIONAL_FOR_YEAR = re.compile(
    r"\bfor\s+(19|20)\d{2}\b", re.IGNORECASE
)

# --------------------------------------------------------------------------- #
# Value extraction patterns
# --------------------------------------------------------------------------- #
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_FLOAT_RE = re.compile(r"\bfloat\s+(\d{7,})\b", re.IGNORECASE)
_WMO_RE = re.compile(r"\bWMO\s+(\d{7,})\b", re.IGNORECASE)
# Phase 5: Bare 7-digit number (no "float"/"WMO" prefix) — used as fallback
# when metadata keywords are present in the query (e.g. "battery status of 5907180")
_BARE_FLOAT_RE = re.compile(r"\b(\d{7})\b")
_PROFILE_NUMBER_RE = re.compile(
    r"\b(?:profile|cycle)\s*#?\s*(\d{1,3})\b", re.IGNORECASE
)


class RegexIntentParser(AbstractIntentParser):
    """Deterministic parser using regular expressions and synonym tables."""

    def __init__(self, normalizer: AbstractQueryNormalizer | None = None) -> None:
        # Phase 20.2: Normalization is opt-in to preserve backward compatibility
        self.normalizer = normalizer  # can be None or explicit instance

    def parse(self, message: str) -> ParsedIntent:
        """Parse *message* via regex heuristics."""
        logger.debug("RegexIntentParser processing: %r", message)

        # Phase 20.2: Query Normalization stage (before any parsing)
        text = message.lower()
        if self.normalizer is not None:
            normalized = self.normalizer.normalize(message)
            if normalized != message:
                logger.info("Original query: %r", message)
                logger.info("Normalized query: %r", normalized)
            text = normalized.lower()

        variables = correct_variables_with_fuzzy(self._extract_variables(text))
        region = self._extract_region(text)
        year = self._extract_year(text)
        float_id = self._extract_float_id(text)
        profile_number = self._extract_profile_number(text)
        lat, lon = self._extract_coordinates(text)
        radius_km = self._extract_radius_km(text)
        existence_check = self._extract_existence_check(text)
        # P3 #1: Depth extraction (deterministic — no LLM needed for these).
        depth_min, depth_max = self._extract_depth(text)
        # P3 #2: Operational filter extraction (deterministic — "alive" is a keyword).
        operational_filter = self._extract_operational_filter(text)

        # Priority 3: If year was extracted from a season token (not a bare year),
        # also extract the representative month for more precise data lake filtering.
        month = self._extract_month_explicit(text)
        if month is None and year is not None:
            # Year came from season resolution (not from a 4-digit number in text)
            if not _YEAR_RE.search(text):
                month = self._extract_season_month(text)
        # P3 #3: resolve the full season month-window (e.g. monsoon → [6,7,8,9])
        # so the data lake filters the WHOLE season, not just the start month.
        # Provisional definitions — pending scientist confirmation (see seasons.py).
        from floatchat.intent_parser.seasons import detect_season_window, season_start_month
        month_window = detect_season_window(text)
        if month_window is not None and month is None:
            month = season_start_month(month_window)

        # Phase 5 Part D: Place-name geocoding fallback
        # If we don't have coordinates yet, try to extract a place name
        # Phase 6 fix: Skip gazetteer if region already detected (e.g., "near arabian sea" should use region, not Nominatim)
        # and skip if extracted place is itself a known ocean region synonym (prevents Nominatim mis-resolving "arabian sea" to Pakistan)
        _OCEAN_REGION_PLACES = {
            "arabian sea", "arabian", "bay of bengal", "bengal", "indian ocean", "indian",
            "north atlantic", "south atlantic", "north pacific", "south pacific",
            "southern ocean", "mediterranean", "red sea", "gulf of mexico",
        }
        place_resolved = None
        place_attempted = False
        if lat is None and lon is None:
            # If region already found, don't use gazetteer for spatial queries that are actually region queries
            if region is not None:
                # Don't attempt gazetteer if region is present - let region handling take over
                logger.debug("Skipping gazetteer because region '%s' already detected", region)
            else:
                place_name = self._extract_place_name(text)
                if place_name:
                    # Skip if place is actually an ocean region name
                    if place_name.lower().strip() in _OCEAN_REGION_PLACES:
                        logger.info("Place '%s' is ocean region synonym, skipping gazetteer", place_name)
                    else:
                        place_attempted = True
                        place_resolved = resolve_place_name(place_name)
                        if place_resolved:
                            lat = place_resolved["lat"]
                            lon = place_resolved["lon"]
                            logger.info(
                                "Phase 5 gazetteer: '%s' resolved to (%s, %s) via %s",
                                place_name, lat, lon, place_resolved.get("source"),
                            )
                        else:
                            logger.warning(
                                "Phase 5 gazetteer: could not resolve place name '%s'",
                                place_name,
                            )

        intent = self._detect_intent(
            text,
            float_id=float_id,
            lat=lat,
            lon=lon,
            radius_km=radius_km,
        )

        # Architectural decision: variables + spatial constraint = measurement
        # query, not float discovery. If the user asked for a specific variable
        # (e.g. "temperature near Goa"), override radius_search to profile_plot
        # so the measurement pipeline (temporal filtering, visualization, multi-
        # float profiles) is used instead of the float-listing pipeline.
        # _detect_intent stays a pure linguistic classifier — this override is
        # a semantic routing decision that requires variable knowledge.
        # Phase 3: Smarter routing override.
        # When variables are present + spatial constraint, override to
        # profile_plot ONLY if the user is asking for measurements.
        # If the query contains "floats" (discovery language), keep as
        # radius_search — the user wants to FIND floats, not PLOT data.
        if intent == "radius_search" and variables:
            has_discovery_language = bool(
                re.search(r'\bfloats?\b', text, re.IGNORECASE)
            )
            if has_discovery_language:
                logger.info(
                    "Keeping radius_search despite variables "
                    "(discovery language: 'floats' detected)"
                )
            else:
                logger.info(
                    "Routing override: radius_search -> profile_plot "
                    "(variables present: %s, no discovery language)", variables
                )
                intent = "profile_plot"

        # Default radius for radius search if not specified (Phase 5: 500km)
        if intent == "radius_search" and radius_km is None:
            radius_km = 500.0

        # Check for conversational follow-up indicators that signal intent
        # even when variables/float are absent (context will fill gaps).
        is_conversational = self._is_conversational_follow_up(text)

        has_coords = lat is not None and lon is not None
        has_region = region is not None

        # Extract comparison targets if comparison query
        comparison_float_ids: list[str] = []
        comparison_regions: list[str] = []
        if intent in ("comparison_plot", "comparison"):
            all_floats = re.findall(r"\b(?:float|wmo)\s*(\d{7,})\b|\b(\d{7,})\b", text, re.IGNORECASE)
            comparison_float_ids = sorted(list({m[0] or m[1] for m in all_floats if (m[0] or m[1])}))
            if not float_id and comparison_float_ids:
                float_id = comparison_float_ids[0]

            for canonical, _ in _REGION_PATTERNS:
                canonical_spaced = canonical.replace("_", " ")
                if canonical_spaced in text or canonical in text:
                    if canonical not in comparison_regions:
                        comparison_regions.append(canonical)
            if not region and comparison_regions:
                region = comparison_regions[0]

        if intent == "ts_diagram" and not variables:
            variables = ["TEMP", "PSAL"]
        elif intent in ("time_series", "hovmoller") and not variables:
            variables = ["TEMP"]
        elif intent in ("comparison_plot", "comparison") and not variables:
            # Priority 2: If the message is a conversational follow-up (e.g.,
            # "compare that with Bay of Bengal"), do NOT fill default variables.
            # Leave variables empty so merge_context can inherit from the
            # previous turn (e.g., just TEMP instead of all 8 vars).
            # Only fill the full variable list for standalone comparisons.
            if is_conversational:
                logger.info(
                    "Priority 2: Skipping default comparison variables for "
                    "conversational follow-up — context will fill variables"
                )
            else:
                # Phase 6 fix: User request "show all possible graphs" for compare.
                # If Core: TEMP, PSAL. If BGC: also DOXY, CHLA, BBP700, NITRATE, PH, PAR.
                # We request all core + common BGC so DataFrame contains whatever exists.
                # Visualization will auto-filter to those present.
                variables = ["TEMP", "PSAL", "DOXY", "CHLA", "BBP700", "NITRATE", "PH_IN_SITU_TOTAL", "DOWNWELLING_PAR"]

        if (
            not variables
            and not float_id
            and not has_coords
            and not (intent == "count_aggregate" and has_region)
            and intent not in ("nearest_float", "radius_search", "metadata_lookup", "count_aggregate", "trajectory")
            and not is_conversational
            and not (has_region and re.search(r"\bfloats?\b", text, re.IGNORECASE))
        ):
            logger.warning("Regex parser could not extract variables or identifiers")
            raise IntentParseError(
                "Could not determine requested variables, float, or coordinates from message.",
                details={"message": message},
            )

        # Phase 5: If a place name was detected for a spatial query but geocoding
        # failed, raise a helpful error rather than letting conversation context
        # silently inherit stale coordinates from a previous query.
        if place_attempted and not has_coords:
            place_name_for_msg = self._extract_place_name(text) or "the specified location"
            raise IntentParseError(
                f"Could not resolve location '{place_name_for_msg}'. "
                "Please provide exact coordinates (e.g., '15.5, 72.3') or try a "
                "well-known coastal city name (e.g., 'Mumbai', 'Chennai', 'Kochi').",
                details={"message": message, "place_name": place_name_for_msg},
            )

        parsed = ParsedIntent(
            intent=intent,
            region=region,
            variables=variables,
            comparison_float_ids=comparison_float_ids,
            comparison_regions=comparison_regions,
            year=year,
            month=month,
            month_window=month_window,
            float_id=float_id,
            profile_number=profile_number,
            lat=lat,
            lon=lon,
            radius_km=radius_km,
            existence_check=existence_check,
            depth_min=depth_min,
            depth_max=depth_max,
            operational_filter=operational_filter,
            limit=5,
        )
        logger.info(
            "RegexIntentParser resolved intent=%s vars=%s region=%s year=%s month=%s float=%s profile=%s lat=%s lon=%s radius=%s conversational=%s place=%s",
            intent,
            variables,
            region,
            year,
            month,
            float_id,
            profile_number,
            lat,
            lon,
            radius_km,
            is_conversational,
            place_resolved,
        )
        return parsed

    @staticmethod
    def _is_conversational_follow_up(text: str) -> bool:
        """Return True if *text* is a conversational follow-up phrase.

        Priority 2: Also detects reference phrases like "same", "that",
        "there", "it", "what about", "how about", "compare that".
        """
        patterns = [
            _CONVERSATIONAL_VARIABLE,
            _CONVERSATIONAL_COMPARISON,
            _CONVERSATIONAL_REGION,
            _CONVERSATIONAL_SAME_FLOAT,
            _CONVERSATIONAL_SAME_REGION,
            _CONVERSATIONAL_SAME_VARIABLE,
            _CONVERSATIONAL_LATEST_PROFILE,
            _CONVERSATIONAL_LATEST_FLOAT,
            _CONVERSATIONAL_PREVIOUS_PROFILE,
            _CONVERSATIONAL_NEXT_PROFILE,
            _CONVERSATIONAL_FOR_YEAR,
            _INTENT_METADATA,
            # Priority 2: Reference phrase patterns
            re.compile(r"\bsame\b", re.IGNORECASE),
            re.compile(r"\bthat\b", re.IGNORECASE),
            re.compile(r"\bthere\b", re.IGNORECASE),
            re.compile(r"\bit\b", re.IGNORECASE),
            re.compile(r"\bwhat\s+about\b", re.IGNORECASE),
            re.compile(r"\bhow\s+about\b", re.IGNORECASE),
            re.compile(r"\bcompare\s+(that|those|the)\b", re.IGNORECASE),
        ]
        return any(p.search(text) is not None for p in patterns)

    @staticmethod
    def _detect_intent(
        text: str,
        float_id: str | None = None,
        lat: float | None = None,
        lon: float | None = None,
        radius_km: float | None = None,
    ) -> str:
        # Priority 2: Metadata keywords ALWAYS route to metadata_lookup,
        # even without an explicit float_id. The float_id will be inherited
        # from context via reference phrase detection in merge_context.
        # Previous logic required float_id OR "same float" OR "float" in text,
        # which missed "what sensors does it have?" and "battery status?"
        if _INTENT_METADATA.search(text):
            return "metadata_lookup"
        if _INTENT_HOVMOLLER.search(text):
            return "hovmoller"
        if _INTENT_TS_DIAGRAM.search(text):
            return "ts_diagram"
        if _CONVERSATIONAL_COMPARISON.search(text) or _INTENT_COMP.search(text):
            return "comparison_plot"
        if _INTENT_TS.search(text):
            return "time_series"
        if _INTENT_TRAJ.search(text):
            return "trajectory"
        if _INTENT_NEAREST.search(text) or ("nearest" in text and lat is not None and lon is not None) or ("closest" in text and lat is not None and lon is not None):
            return "nearest_float"
        if _INTENT_RADIUS.search(text) or (radius_km is not None) or ("near" in text and lat is not None and lon is not None):
            return "radius_search"
        if _INTENT_COUNT.search(text):
            return "count_aggregate"
        if (
            (RegexIntentParser._extract_region(text) or _INTENT_REGION_SEARCH.search(text))
            and not _INTENT_PROFILE.search(text)
        ):
            return "region_search"
        if _INTENT_PROFILE.search(text):
            return "profile_plot"
        return "profile_plot"

    @staticmethod
    def _extract_coordinates(text: str) -> tuple[float | None, float | None]:
        """Extract latitude and longitude coordinate pair from text."""
        lbl_match = re.search(
            r"(?:lat|latitude)\s*:?\s*(-?\d+(?:\.\d+)?)\s*([NS])?[\s,;]+"
            r"(?:lon|long|longitude)\s*:?\s*(-?\d+(?:\.\d+)?)\s*([EW])?",
            text,
            re.IGNORECASE,
        )
        if lbl_match:
            lat = float(lbl_match.group(1))
            if lbl_match.group(2) and lbl_match.group(2).upper() == "S":
                lat = -abs(lat)
            lon = float(lbl_match.group(3))
            if lbl_match.group(4) and lbl_match.group(4).upper() == "W":
                lon = -abs(lon)
            return lat, lon

        dir_match = re.search(
            r"(-?\d+(?:\.\d+)?)\s*°?\s*([NS])[\s,;]+(-?\d+(?:\.\d+)?)\s*°?\s*([EW])",
            text,
            re.IGNORECASE,
        )
        if dir_match:
            lat = float(dir_match.group(1))
            if dir_match.group(2).upper() == "S":
                lat = -abs(lat)
            lon = float(dir_match.group(3))
            if dir_match.group(4).upper() == "W":
                lon = -abs(lon)
            return lat, lon

        pair_matches = re.finditer(
            r"(-?\d{1,2}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)",
            text,
        )
        for m in pair_matches:
            lat = float(m.group(1))
            lon = float(m.group(2))
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return lat, lon

        return None, None

    @staticmethod
    def _extract_radius_km(text: str) -> float | None:
        """Extract radius in kilometers from text."""
        match = re.search(
            r"\b(\d+(?:\.\d+)?)\s*(?:km|kilometer|kilometers|kilometres)\b",
            text,
            re.IGNORECASE,
        )
        if match:
            return float(match.group(1))
        return None

    @staticmethod
    def _extract_depth(text: str) -> tuple[float | None, float | None]:
        """P3 #1: Extract depth filters deterministically.

        Assumptions (documented for scientist review):
          - "deep"            -> depth_min = 1000 (mesopelagic-and-below).
            A common oceanographic shorthand; adjust via _DEEP_DEPTH_M if needed.
          - "below Nm" / "below N m" / "deeper than Nm" -> depth_min = N
          - "above Nm" / "shallower than Nm" / "shallower than Nm" -> depth_max = N
          - "surface"         -> depth_max = 20 (near-surface layer, dbar ~ metres)

        Returns (depth_min, depth_max); each is None when not specified.
        """
        _DEEP_DEPTH_M = 1000.0
        _SURFACE_DEPTH_M = 20.0
        depth_min: float | None = None
        depth_max: float | None = None

        # Explicit "below/deeper than <N> m"  -> depth_min
        m = re.search(
            r"\b(?:below|deeper\s+than)\s+(\d+(?:\.\d+)?)\s*m(?:eters?)?\b",
            text, re.IGNORECASE,
        )
        if m:
            depth_min = float(m.group(1))
        else:
            m = re.search(
                r"\b(\d+(?:\.\d+)?)\s*m(?:eters)?\s+(?:and\s+)?(?:below|deeper)\b",
                text, re.IGNORECASE,
            )
            if m:
                depth_min = float(m.group(1))

        # Explicit "above/shallower than <N> m"  -> depth_max
        m = re.search(
            r"\b(?:above|shallower\s+than)\s+(\d+(?:\.\d+)?)\s*m(?:eters?)?\b",
            text, re.IGNORECASE,
        )
        if m:
            depth_max = float(m.group(1))

        # Word-based tokens
        if re.search(r"\bdeep\b", text, re.IGNORECASE):
            if depth_min is None:
                depth_min = _DEEP_DEPTH_M
        if re.search(r"\bsurface\b", text, re.IGNORECASE):
            if depth_max is None:
                depth_max = _SURFACE_DEPTH_M

        return depth_min, depth_max

    @staticmethod
    def _extract_operational_filter(text: str) -> str | None:
        """Phase 6: Extract operational + float-class filters deterministically.

        Returns a filter string that the engine can use to narrow results:
        - "alive" / "active" -> float has recent profiles
        - "inactive" -> float has no recent profiles
        - "bgc" -> BGC Argo float (has biogeochemical sensors)
        - "core" -> Core Argo float (CTD only)
        - "latest" / "newest" / "recent" -> sort by most recent (informational)
        """
        if re.search(r"\b(?:alive|active|operational)\b", text, re.IGNORECASE):
            return "alive"
        if re.search(r"\binactive\b", text, re.IGNORECASE):
            return "inactive"
        if re.search(r"\bbgc\b", text, re.IGNORECASE):
            return "bgc"
        if re.search(r"\bcore\s+float", text, re.IGNORECASE):
            return "core"
        return None

    @staticmethod
    def _extract_existence_check(text: str) -> bool:
        """Check if query is an existence question (is there data vs count)."""
        return bool(
            re.search(
                r"\b(is there|are there|do we have|any data|data exist|exists)\b",
                text,
                re.IGNORECASE,
            )
        )

    @staticmethod
    def _extract_variables(text: str) -> list[str]:
        found: set[str] = set()
        for canonical, pattern in _VAR_PATTERNS:
            if pattern.search(text):
                found.add(canonical)
        return sorted(found)

    @staticmethod
    def _extract_region(text: str) -> str | None:
        for canonical, pattern in _REGION_PATTERNS:
            if pattern.search(text):
                return canonical
        return None

    @staticmethod
    def _extract_year(text: str) -> int | None:
        # For "between 2022 and 2024" or "from 2022 to 2024", use the first year
        # as the primary filter. The downstream engine can expand if needed.
        match = _YEAR_RE.search(text)
        if match:
            return int(match.group(0))

        # Priority 3: Deterministic season → year resolution.
        # Handles: "during monsoon", "last monsoon", "next winter", etc.
        # This avoids the LLM call entirely for the most common seasonal queries.
        from datetime import date as _date

        # Relative season: "last/next/this/past monsoon", "previous winter", etc.
        _REL_SEASON_RE = re.compile(
            r'\b(last|previous|past|next|this|current|upcoming)\s+'
            r'(monsoon|southwest\s+monsoon|sw\s+monsoon|'
            r'northeast\s+monsoon|ne\s+monsoon|post[\s-]?monsoon|'
            r'pre[\s-]?monsoon|winter|summer|spring|autumn|fall|'
            r'inter[\s-]?monsoon)\b',
            re.IGNORECASE,
        )
        rel_match = _REL_SEASON_RE.search(text)
        if rel_match:
            relative = rel_match.group(1).lower()
            current_year = _date.today().year
            shift = {"last": -1, "previous": -1, "past": -1,
                     "this": 0, "current": 0,
                     "next": 1, "upcoming": 1}.get(relative, 0)
            return current_year + shift

        # Bare season with "during" or "in": "during monsoon", "in winter"
        _BARE_SEASON_RE = re.compile(
            r'\b(?:during|in\s+(?:the\s+)?)\s+'
            r'(monsoon|southwest\s+monsoon|sw\s+monsoon|'
            r'northeast\s+monsoon|ne\s+monsoon|post[\s-]?monsoon|'
            r'pre[\s-]?monsoon|winter|summer|spring|autumn|fall|'
            r'inter[\s-]?monsoon)\b',
            re.IGNORECASE,
        )
        bare_match = _BARE_SEASON_RE.search(text)
        if bare_match:
            # Bare season = current year (e.g., "during monsoon" = this year's monsoon)
            return _date.today().year

        return None

    @staticmethod
    def _extract_season_month(text: str) -> int | None:
        """Priority 3: Extract a representative month from season tokens.

        Maps Indian Ocean seasons to their starting month for more precise
        data lake filtering. Returns None if no season detected.
        """
        _SEASON_MONTH_MAP = {
            "monsoon": 6, "southwest monsoon": 6, "sw monsoon": 6,
            "northeast monsoon": 10, "ne monsoon": 10,
            "post monsoon": 10, "post-monsoon": 10,
            "pre monsoon": 3, "pre-monsoon": 3,
            "winter": 12, "summer": 3, "spring": 3,
            "autumn": 10, "fall": 10, "inter monsoon": 4, "inter-monsoon": 4,
        }
        # Check relative seasons first: "last monsoon", "next winter"
        _REL_SEASON_RE = re.compile(
            r'\b(?:last|previous|past|next|this|current|upcoming)\s+'
            r'(monsoon|southwest\s+monsoon|sw\s+monsoon|'
            r'northeast\s+monsoon|ne\s+monsoon|post[\s-]?monsoon|'
            r'pre[\s-]?monsoon|winter|summer|spring|autumn|fall|'
            r'inter[\s-]?monsoon)\b',
            re.IGNORECASE,
        )
        rel_match = _REL_SEASON_RE.search(text)
        if rel_match:
            season_key = rel_match.group(1).lower().strip()
            return _SEASON_MONTH_MAP.get(season_key)

        # Check bare seasons: "during monsoon", "in winter"
        _BARE_SEASON_RE = re.compile(
            r'\b(?:during|in\s+(?:the\s+)?)\s+'
            r'(monsoon|southwest\s+monsoon|sw\s+monsoon|'
            r'northeast\s+monsoon|ne\s+monsoon|post[\s-]?monsoon|'
            r'pre[\s-]?monsoon|winter|summer|spring|autumn|fall|'
            r'inter[\s-]?monsoon)\b',
            re.IGNORECASE,
        )
        bare_match = _BARE_SEASON_RE.search(text)
        if bare_match:
            season_key = bare_match.group(1).lower().strip()
            return _SEASON_MONTH_MAP.get(season_key)

        return None

    @staticmethod
    def _extract_float_id(text: str) -> str | None:
        # First try explicit prefixes: "float 5907180", "WMO 5907180"
        for pattern in (_FLOAT_RE, _WMO_RE):
            match = pattern.search(text)
            if match:
                return match.group(1)
        # Phase 5 / Priority 2: Bare 7-digit number fallback when metadata or
        # trajectory keywords are present. Handles:
        #   "battery status of 5907180"
        #   "sensors on 5907180"
        #   "trajectory of 7901128"
        #   "show trajectory 7901128"
        if _INTENT_METADATA.search(text) or _INTENT_TRAJ.search(text):
            match = _BARE_FLOAT_RE.search(text)
            if match:
                return match.group(1)
        return None

    @staticmethod
    def _extract_profile_number(text: str) -> int | None:
        match = _PROFILE_NUMBER_RE.search(text)
        return int(match.group(1)) if match else None

    @staticmethod
    def _extract_month_explicit(text: str) -> int | None:
        """Extract an explicitly mentioned month number or name from text.

        Only matches numeric months (e.g., "month 6") or month names
        (e.g., "January", "Jun"). Does NOT interpret season tokens —
        that's handled by _extract_season_month.
        """
        # Numeric month: "month 6", "in month 07"
        num_match = re.search(r'\bmonth\s+(\d{1,2})\b', text, re.IGNORECASE)
        if num_match:
            m = int(num_match.group(1))
            if 1 <= m <= 12:
                return m

        # Month names
        _MONTH_MAP = {
            "january": 1, "february": 2, "march": 3, "april": 4,
            "may": 5, "june": 6, "july": 7, "august": 8,
            "september": 9, "october": 10, "november": 11, "december": 12,
            "jan": 1, "feb": 2, "mar": 3, "apr": 4,
            "jun": 6, "jul": 7, "aug": 8, "sep": 9,
            "oct": 10, "nov": 11, "dec": 12,
        }
        for name, num in _MONTH_MAP.items():
            if re.search(r'\b' + re.escape(name) + r'\b', text, re.IGNORECASE):
                return num

        return None

    @staticmethod
    def _extract_place_name(text: str) -> str | None:
        """Phase 5 Part D: Extract a place name from spatial query text.
        
        Looks for patterns like:
        - "within 100km of Chennai"
        - "floats near Mumbai"
        - "nearest float to Kerala coast"
        - "oxygen data near Mumbai" (generic data near)
        """
        match = _PLACE_SPATIAL_RE.search(text)
        if match:
            place = match.group(1).strip()
            # Remove trailing words that aren't part of place names
            place = re.sub(r'\s+(within|for|in|and|with|show|get|find)\s*$', '', place, flags=re.IGNORECASE)
            # P1 fix: strip from the first proximity preposition / standalone
            # article "the" to the end — e.g. "goa around the" → "goa".
            place = re.sub(r'\s+(?:around|off|by|the)(?:\s+.*)?$', '', place, flags=re.IGNORECASE)
            # Priority 3 fix: Strip temporal tokens that the regex may have captured
            # e.g., "goa during last monsoon" → "goa"
            place = re.sub(r'\s+during\s+.*$', '', place, flags=re.IGNORECASE)
            place = re.sub(r'\s+(?:last|next|this|past|previous|current)\s+(?:monsoon|winter|summer|spring|autumn|fall|pre-?monsoon|post-?monsoon|northeast|ne|sw|southwest|year|month|week)\s*$', '', place, flags=re.IGNORECASE)
            place = place.strip()
            if len(place) >= 2:
                return place

        # Secondary: generic "near <place>" for existence/count queries like "oxygen data near Mumbai"
        _PLACE_GENERIC_RE = re.compile(
            r"(?:near|around|off|by|from)\s+(?:the\s+)?([A-Za-z][A-Za-z\s]{2,30}?)(?:\s*$|\s*[,.]|\s+(?:\d+(?:\.\d+)?)\s*k|\s+in\s+|\s+for\s+|\s*\?|$)",
            re.IGNORECASE,
        )
        generic_match = _PLACE_GENERIC_RE.search(text)
        if generic_match:
            place = generic_match.group(1).strip()
            # Clean trailing generic words
            place = re.sub(r'\s+(within|for|in|and|with|show|get|find|data|oxygen|temperature|salinity|any)\s*$', '', place, flags=re.IGNORECASE)
            # P1 fix: strip from the first proximity preposition / standalone
            # article "the" to the end — covers the generic-regex path which
            # has weaker tail-stops (e.g. "goa around the last monsoon" → "goa").
            place = re.sub(r'\s+(?:around|off|by|the)(?:\s+.*)?$', '', place, flags=re.IGNORECASE)
            # Priority 3 fix: Strip temporal tokens
            place = re.sub(r'\s+during\s+.*$', '', place, flags=re.IGNORECASE)
            place = re.sub(r'\s+(?:last|next|this|past|previous|current)\s+(?:monsoon|winter|summer|spring|autumn|fall|pre-?monsoon|post-?monsoon|northeast|ne|sw|southwest|year|month|week)\s*$', '', place, flags=re.IGNORECASE)
            place = place.strip()
            if len(place) >= 3 and place.lower() not in {"arabian sea", "bay of bengal", "indian ocean", "arabian", "bengal"}:
                return place
        return None
