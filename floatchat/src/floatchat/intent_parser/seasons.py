"""P3 #3: Season → month-window resolution (provisional).

Maps Indian-Ocean season tokens to the *list of months* they span, so the data
lake can filter a whole season (e.g. "monsoon" → June–September) instead of a
single representative month.

⚠️  PROVISIONAL — pending scientist confirmation.
    These climatological windows reflect typical Indian-Ocean / Indian-subcontinent
    season boundaries. An INCOIS oceanographer should confirm/adjust before
    production use. They are deliberately exposed as a module-level dict so a
    scientist can tune them (or override via settings) without touching code.

Cross-year seasons (e.g. winter = Dec–Feb) are represented as the full month
list [12, 1, 2]; the data-lake ``month IN (...)`` filter applies them within
the selected year, so "winter 2024" matches Dec-2024 but not Jan/Feb-2025
unless the engine later expands the year window. This is a known provisional
limitation, documented for scientist review.
"""

import logging
import re

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# ⚠️ PROVISIONAL — pending scientist confirmation.
# Season → months window for the India region (Northern Indian Ocean).
# --------------------------------------------------------------------------- #
SEASON_MONTH_WINDOWS: dict[str, list[int]] = {
    "monsoon": [6, 7, 8, 9],               # Southwest monsoon (JJAS)
    "southwest monsoon": [6, 7, 8, 9],
    "sw monsoon": [6, 7, 8, 9],
    "northeast monsoon": [10, 11, 12],     # NE monsoon (OND)
    "ne monsoon": [10, 11, 12],
    "post monsoon": [10, 11],
    "post-monsoon": [10, 11],
    "pre monsoon": [3, 4, 5],
    "pre-monsoon": [3, 4, 5],
    "winter": [12, 1, 2],                  # DJF (crosses year boundary)
    "summer": [3, 4, 5],                   # MAM (same as pre-monsoon for NIO)
    "spring": [3, 4, 5],
    "autumn": [10, 11],
    "fall": [10, 11],
    "inter monsoon": [4, 5],
    "inter-monsoon": [4, 5],
}

# Regexes mirror the season detection in RegexIntentParser._extract_season_month.
_REL_SEASON_RE = re.compile(
    r"\b(?:last|previous|past|next|this|current|upcoming)\s+"
    r"(monsoon|southwest\s+monsoon|sw\s+monsoon|"
    r"northeast\s+monsoon|ne\s+monsoon|post[\s-]?monsoon|"
    r"pre[\s-]?monsoon|winter|summer|spring|autumn|fall|"
    r"inter[\s-]?monsoon)\b",
    re.IGNORECASE,
)
_BARE_SEASON_RE = re.compile(
    r"\b(?:during|in\s+(?:the\s+)?)\s+"
    r"(monsoon|southwest\s+monsoon|sw\s+monsoon|"
    r"northeast\s+monsoon|ne\s+monsoon|post[\s-]?monsoon|"
    r"pre[\s-]?monsoon|winter|summer|spring|autumn|fall|"
    r"inter[\s-]?monsoon)\b",
    re.IGNORECASE,
)


def _normalize_season(key: str) -> str:
    return key.strip().lower()


def detect_season_window(text: str) -> list[int] | None:
    """Return the month list for the first season token in *text*, or None.

    Checks relative seasons ("last monsoon") then bare seasons
    ("during monsoon", "in winter"). Returns the window from
    :data:`SEASON_MONTH_WINDOWS`.
    """
    m = _REL_SEASON_RE.search(text) or _BARE_SEASON_RE.search(text)
    if not m:
        return None
    key = _normalize_season(m.group(1))
    window = SEASON_MONTH_WINDOWS.get(key)
    if window is None:
        logger.debug("No month window for season %r (provisional dict)", key)
    return window


def season_start_month(window: list[int] | None) -> int | None:
    """Return the first month of a season window (for backward-compat `month`)."""
    if not window:
        return None
    # For cross-year seasons, the representative start month is the first
    # entry (e.g. winter -> 12).
    return window[0]
