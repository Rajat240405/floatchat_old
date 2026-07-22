"""Deterministic temporal resolver for Priority 3.

Converts semantic time tokens from LLM extraction into concrete date ranges.
All mappings are CONFIGURABLE via FLOATCHAT_SEASON_OVERRIDES env var.

Examples:
    "monsoon"     → (June 1, September 30)
    "winter"      → (December 1, February 28)
    "last summer" → (March 1, May 31) of previous year
    "pre-monsoon" → (March 1, May 31)
"""

import logging
from datetime import date, timedelta
from typing import NamedTuple

from floatchat.config import settings

logger = logging.getLogger(__name__)


class DateRange(NamedTuple):
    start: date
    end: date


# Default season definitions for India region (Northern Indian Ocean).
# Each entry: (start_month, start_day, end_month, end_day)
# These are climatological seasons for the Indian Ocean / Indian subcontinent.
_DEFAULT_SEASONS: dict[str, tuple[int, int, int, int]] = {
    "monsoon": (6, 1, 9, 30),           # Southwest monsoon (JJAS)
    "southwest_monsoon": (6, 1, 9, 30),
    "sw_monsoon": (6, 1, 9, 30),
    "post_monsoon": (10, 1, 11, 30),    # Northeast monsoon transition (ON)
    "northeast_monsoon": (10, 1, 12, 31), # Northeast monsoon (OND)
    "ne_monsoon": (10, 1, 12, 31),
    "winter": (12, 1, 2, 28),           # Winter (DJF)
    "pre_monsoon": (3, 1, 5, 31),       # Pre-monsoon / summer (MAM)
    "summer": (3, 1, 5, 31),            # Same as pre-monsoon for Indian Ocean
    "spring": (3, 1, 5, 31),
    "inter_monsoon": (4, 1, 5, 31),     # Spring inter-monsoon
    "autumn": (10, 1, 11, 30),          # Post-monsoon
    "fall": (10, 1, 11, 30),
}

# Relative time tokens that shift the year
_RELATIVE_TOKENS = {
    "last": -1,
    "previous": -1,
    "past": -1,
    "this": 0,
    "current": 0,
    "next": 1,
    "upcoming": 1,
}


def _get_season_defs() -> dict[str, tuple[int, int, int, int]]:
    """Get season definitions, allowing runtime overrides from config."""
    seasons = dict(_DEFAULT_SEASONS)
    # Allow overrides via settings (e.g., from env FLOATCHAT_SEASON_OVERRIDES)
    overrides = getattr(settings, "season_overrides", None)
    if overrides and isinstance(overrides, dict):
        seasons.update(overrides)
    return seasons


def resolve_season_token(
    season: str,
    relative: str | None = None,
    reference_year: int | None = None,
) -> DateRange | None:
    """Resolve a semantic season token to a concrete DateRange.

    Args:
        season: The season name (e.g., "monsoon", "winter").
        relative: Optional relative modifier (e.g., "last", "next").
        reference_year: The reference year for resolution. Defaults to current year.

    Returns:
        A DateRange with start and end dates, or None if the season is unknown.
    """
    seasons = _get_season_defs()
    key = season.lower().replace("-", "_").replace(" ", "_")

    if key not in seasons:
        logger.debug("Unknown season token: %r", season)
        return None

    sm, sd, em, ed = seasons[key]
    ref_year = reference_year or date.today().year

    # Apply relative year shift
    if relative and relative.lower() in _RELATIVE_TOKENS:
        ref_year += _RELATIVE_TOKENS[relative.lower()]

    # Handle seasons that cross calendar year boundaries (e.g., winter = Dec-Feb)
    if sm > em:
        # Season spans year boundary: start in ref_year, end in ref_year+1
        # But if "last winter", shift start to ref_year-1
        start = date(ref_year, sm, sd)
        end = date(ref_year + 1, em, ed)
    else:
        start = date(ref_year, sm, sd)
        end = date(ref_year, em, ed)

    logger.info(
        "Resolved season %r (relative=%s, ref_year=%s) → %s to %s",
        season, relative, reference_year, start, end,
    )
    return DateRange(start, end)


def resolve_temporal_filter(
    time_filter: str | None,
    reference_year: int | None = None,
) -> dict | None:
    """Resolve a semantic temporal filter from the LLM QuerySpec.

    The LLM may return:
        - A year: "2024"
        - A season: "monsoon"
        - A relative season: "last monsoon"
        - A date range: "2023-06-01 to 2023-09-30"
        - A month: "January"

    Returns a dict with:
        - "year": int (if single year)
        - "date_start": str (ISO date if range)
        - "date_end": str (ISO date if range)
        - "season": str (original season token)
    """
    if not time_filter:
        return None

    text = time_filter.strip().lower()

    # 1. Try bare year
    import re
    year_match = re.match(r"^(19|20)\d{2}$", text)
    if year_match:
        return {"year": int(year_match.group())}

    # 2. Try "last/next/this <season>"
    rel_season_match = re.match(
        r"^(last|previous|past|this|current|next|upcoming)\s+(\w+)$", text
    )
    if rel_season_match:
        relative = rel_season_match.group(1)
        season = rel_season_match.group(2)
        dr = resolve_season_token(season, relative, reference_year)
        if dr:
            return {
                "date_start": dr.start.isoformat(),
                "date_end": dr.end.isoformat(),
                "season": season,
            }

    # 3. Try bare season
    dr = resolve_season_token(text, reference_year=reference_year)
    if dr:
        return {
            "date_start": dr.start.isoformat(),
            "date_end": dr.end.isoformat(),
            "season": text,
        }

    # 4. Try "YYYY-MM-DD to YYYY-MM-DD"
    range_match = re.match(
        r"^(\d{4}-\d{2}-\d{2})\s*(?:to|–|-|through)\s*(\d{4}-\d{2}-\d{2})$", text
    )
    if range_match:
        return {
            "date_start": range_match.group(1),
            "date_end": range_match.group(2),
        }

    # 5. Try month name
    month_names = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
        "jan": 1, "feb": 2, "mar": 3, "apr": 4,
        "jun": 6, "jul": 7, "aug": 8, "sep": 9,
        "oct": 10, "nov": 11, "dec": 12,
    }
    if text in month_names:
        ref_year = reference_year or date.today().year
        m = month_names[text]
        start = date(ref_year, m, 1)
        # End of month
        if m == 12:
            end = date(ref_year, 12, 31)
        else:
            end = date(ref_year, m + 1, 1) - timedelta(days=1)
        return {
            "date_start": start.isoformat(),
            "date_end": end.isoformat(),
            "month": m,
        }

    # 6. Try "YYYY-MM" (year-month)
    ym_match = re.match(r"^(\d{4})-(\d{2})$", text)
    if ym_match:
        y, m = int(ym_match.group(1)), int(ym_match.group(2))
        start = date(y, m, 1)
        if m == 12:
            end = date(y, 12, 31)
        else:
            end = date(y, m + 1, 1) - timedelta(days=1)
        return {
            "date_start": start.isoformat(),
            "date_end": end.isoformat(),
            "year": y,
            "month": m,
        }

    logger.warning("Could not resolve temporal filter: %r", time_filter)
    return None
