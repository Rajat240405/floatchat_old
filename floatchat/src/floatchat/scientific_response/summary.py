"""Deterministic scientific summaries (Phase 5).

Facts only. Every bullet is one of:

1. **Engine-produced interpretation** — the explanation the (frozen)
   executors already appended to their message, carried forward verbatim.
2. **Computed-from-results statements** — statistics derived deterministically
   from the returned payload itself (figure traces, map markers, standard
   ``data_summary`` keys). Where the data is too thin for a statement, the
   statement is omitted — never invented.
3. **Coverage statements** — counts/dates straight from ``data_summary``.
"""

from __future__ import annotations

import math
from typing import Any

from floatchat.models import ParsedIntent
from floatchat.ontology.variables import VARIABLES

from .narration import region_name, variable_phrase

_EPS = 1e-9


def _units(code: str) -> str:
    definition = VARIABLES.get(code)
    return definition.units if definition is not None else ""


def _valid_series(pairs: list[tuple[float, float]]) -> list[tuple[float, float]]:
    return [(x, y) for x, y in pairs if x == x and y == y and abs(x) < 1e38 and abs(y) < 1e38]


def _traces(response: Any) -> list[dict[str, Any]]:
    figure = getattr(response, "figure", None)
    if not isinstance(figure, dict):
        return []
    out = []
    for trace in figure.get("data", []) or []:
        if not isinstance(trace, dict):
            continue
        x, y = trace.get("x"), trace.get("y")
        if isinstance(x, (list, tuple)) and isinstance(y, (list, tuple)) and len(x) == len(y) and x:
            out.append({"x": list(x), "y": list(y), "name": str(trace.get("name") or "")})
    return out


# --------------------------------------------------------------------- #
# 1. Engine interpretation, carried forward                              #
# --------------------------------------------------------------------- #
def engine_interpretation(message: str) -> list[str]:
    """The executor-appended explanation tail (base + blank line + explanation)."""
    _base, sep, tail = message.partition("\n\n")
    if not sep or not tail.strip():
        return []
    lines = [ln.strip("- •\t ") for ln in tail.strip().splitlines()]
    return [ln for ln in lines if ln][:2]


# --------------------------------------------------------------------- #
# 2. Computed statements                                                 #
# --------------------------------------------------------------------- #
def _profile_bullets(intent: ParsedIntent, traces: list[dict[str, Any]]) -> list[str]:
    """Depth-profile statistics from the plotted trace (x=value, y=pressure)."""
    if not traces or not intent.variables:
        return []
    var = intent.variables[0]
    phrase = variable_phrase(var)
    units = _units(var)
    pairs = _valid_series(
        [(float(x), float(y)) for x, y in zip(traces[0]["x"], traces[0]["y"]) if _is_num(x) and _is_num(y)]
    )
    if len(pairs) < 8:
        return []
    values = [v for v, _ in pairs]
    bullets: list[str] = []
    # Range + extremes (always computable when a profile exists)
    v_lo_i = min(range(len(values)), key=lambda i: values[i])
    v_hi_i = max(range(len(values)), key=lambda i: values[i])
    bullets.append(
        f"{phrase.capitalize()} spans {_fmt(values[v_lo_i])}–{_fmt(values[v_hi_i])} {units} "
        f"over the profile (minimum {_fmt(values[v_lo_i])} {units} near {_fmt(pairs[v_lo_i][1], 0)} dbar, "
        f"maximum {_fmt(values[v_hi_i])} {units} near {_fmt(pairs[v_hi_i][1], 0)} dbar)."
    )
    # Surface vs deep means + strongest-gradient depth (temperature structure)
    if var == "TEMP":
        surface = [v for v, p in pairs if p <= 50]
        deep = [v for v, p in pairs if p >= 1000]
        span = max(p for _, p in pairs) - min(p for _, p in pairs)
        if surface and deep and span >= 300:
            # bin means over 25 dbar, strongest adjacent-bin gradient
            bins: dict[int, list[float]] = {}
            for v, p in pairs:
                bins.setdefault(int(p // 25) * 25, []).append(v)
            ordered = sorted((k, sum(vs) / len(vs)) for k, vs in bins.items() if vs)
            grad, grad_at = 0.0, None
            for (p0, m0), (p1, m1) in zip(ordered, ordered[1:]):
                g = abs(m1 - m0) / max(p1 - p0, _EPS)
                if g > grad:
                    grad, grad_at = g, (p0 + p1) / 2
            sentence = (
                f"Temperature decreases from {_fmt(sum(surface) / len(surface))} {units} "
                f"near the surface (≤50 dbar) to {_fmt(sum(deep) / len(deep))} {units} "
                f"at depth (≥1000 dbar)"
            )
            if grad_at and grad >= 0.02:  # °C per dbar — documented threshold
                sentence += f", with the strongest change centred near {_fmt(grad_at, 0)} dbar"
            bullets.append(sentence + ".")
    return bullets[:2]


def _comparison_bullets(intent: ParsedIntent, traces: list[dict[str, Any]]) -> list[str]:
    """Per-group surface statistics from comparison traces."""
    if not intent.variables or len(traces) < 2:
        return []
    var = intent.variables[0]
    units = _units(var)
    groups: list[tuple[str, float, list[tuple[float, float]]]] = []
    for trace in traces[:2]:
        pairs = _valid_series(
            [(float(x), float(y)) for x, y in zip(trace["x"], trace["y"]) if _is_num(x) and _is_num(y)]
        )
        surface = [v for v, p in pairs if p <= 100]
        if len(surface) >= 3 and trace["name"]:
            groups.append((trace["name"], sum(surface) / len(surface), pairs))
    if len(groups) != 2:
        return []
    (n0, m0, _), (n1, m1, _) = groups
    phrase = variable_phrase(var)
    higher, lower = (n0, m0), (n1, m1) if m0 >= m1 else ((n1, m1), (n0, m0))
    return [
        f"Near-surface {phrase} (≤100 dbar mean): "
        f"{n0} ≈ {_fmt(m0)} {units}, {n1} ≈ {_fmt(m1)} {units} — "
        f"{higher[0]} sits higher in this comparison."
    ]


def _time_series_bullets(intent: ParsedIntent, traces: list[dict[str, Any]]) -> list[str]:
    if not traces or not intent.variables:
        return []
    var = intent.variables[0]
    units = _units(var)
    vals = [float(v) for v in traces[0]["y"] if _is_num(v) and _valid_series([(float(v), 0.0)])]
    if len(vals) < 8:
        return []
    k = max(1, len(vals) // 4)
    first = sum(vals[:k]) / k
    last = sum(vals[-k:]) / k
    mean = sum(vals) / len(vals)
    var_s = sum((v - mean) ** 2 for v in vals) / len(vals)
    std = math.sqrt(var_s)
    phrase = variable_phrase(var)
    if std > _EPS and abs(last - first) > max(0.25 * std, abs(mean) * 0.01, 0.01):
        direction = "increases" if last > first else "decreases"
        return [
            f"{phrase.capitalize()} {direction} over the period "
            f"(first-quarter mean {_fmt(first)} {units} → last-quarter mean {_fmt(last)} {units})."
        ]
    return [f"{phrase.capitalize()} remains broadly stable over the period (mean {_fmt(mean)} {units}, σ {_fmt(std)} {units})."]


_COMPASS = ("north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest")


def _trajectory_bullets(intent: ParsedIntent, response: Any, summary: dict[str, Any]) -> list[str]:
    markers = [m for m in (getattr(response, "map_data", None) or []) if getattr(m, "profile_date", None)]
    if len(markers) < 2:
        return []
    ordered = sorted(markers, key=lambda m: str(m.profile_date))
    start, end = ordered[0], ordered[-1]
    dist_net = _haversine_km(start.latitude, start.longitude, end.latitude, end.longitude)
    bearing = _bearing_deg(start.latitude, start.longitude, end.latitude, end.longitude)
    direction = _COMPASS[int((bearing + 22.5) // 45) % 8] if dist_net >= 1.0 else None
    parts = [
        f"The float moved from ({_fmt(start.latitude, 2)}, {_fmt(start.longitude, 2)}) "
        f"to ({_fmt(end.latitude, 2)}, {_fmt(end.longitude, 2)})"
    ]
    span = summary.get("date_range") or {}
    if span.get("min") and span.get("max"):
        parts.append(f" between {span['min']} and {span['max']}")
    details: list[str] = []
    if dist_net >= 1.0 and direction:
        details.append(f"net displacement ≈ {_fmt(dist_net, 0)} km, predominantly {direction}ward")
    total = summary.get("distance_km")
    if total:
        details.append(f"total path ≈ {_fmt(float(total), 0)} km")
    if details:
        parts.append(" — " + "; ".join(details))
    return ["".join(parts) + "."]


def _coverage_bullet(summary: dict[str, Any]) -> str | None:
    floats = summary.get("unique_floats")
    profiles = summary.get("unique_profiles")
    measurements = summary.get("total_measurements")
    span = summary.get("date_range") or {}
    bits = []
    if floats:
        bits.append(f"{floats} float{'s' if floats != 1 else ''}")
    if profiles:
        bits.append(f"{profiles} profile{'s' if profiles != 1 else ''}")
    if measurements:
        bits.append(f"{measurements} measurements")
    if not bits:
        return None
    text = "Coverage: " + " · ".join(bits)
    if span.get("min") and span.get("max"):
        text += f" ({span['min']} → {span['max']})"
    return text + "."


def _metadata_bullets(summary: dict[str, Any]) -> list[str]:
    info = summary.get("float_info") or {}
    bullets: list[str] = []
    fields = [
        ("status", lambda v: f"Operational status: {v}."),
        ("dac", lambda v: f"Data assembly centre: {v}."),
        ("network", lambda v: f"Argo network: {v}."),
        ("profile_count", lambda v: f"Profiles on record: {v}."),
    ]
    for key, render in fields:
        value = info.get(key)
        if value not in (None, "", 0):
            bullets.append(render(value))
    lat, lon = info.get("latitude"), info.get("longitude")
    if _is_num(lat) and _is_num(lon):
        bullets.append(f"Last known position: ({_fmt(float(lat), 2)}, {_fmt(float(lon), 2)}).")
    return bullets[:4]


# --------------------------------------------------------------------- #
# Public entry point                                                     #
# --------------------------------------------------------------------- #
def summarize(response: Any, intent: ParsedIntent, original_message: str) -> list[str]:
    """Ordered summary bullets: engine interpretation → computed → coverage."""
    summary = getattr(response, "data_summary", None) or {}
    bullets: list[str] = engine_interpretation(original_message)

    traces = _traces(response)
    if intent.intent in ("profile_plot", "region_search", "ts_diagram", "hovmoller"):
        bullets += _profile_bullets(intent, traces)
    elif intent.intent in ("comparison_plot", "comparison"):
        bullets += _comparison_bullets(intent, traces)
    elif intent.intent == "time_series":
        bullets += _time_series_bullets(intent, traces)
    elif intent.intent == "trajectory":
        bullets += _trajectory_bullets(intent, response, summary)
        coverage = _coverage_bullet(summary)
        if coverage:
            bullets.append(coverage)
    elif intent.intent == "metadata_lookup":
        bullets += _metadata_bullets(summary)
    elif intent.intent in ("nearest_float", "radius_search"):
        coverage = _coverage_bullet(summary)
        if not coverage:
            span = summary.get("date_range") or {}
            markers = len(getattr(response, "map_data", None) or [])
            if markers:
                coverage = f"Coverage: {markers} float location{'s' if markers != 1 else ''}."
        if coverage:
            bullets.append(coverage)
    else:
        coverage = _coverage_bullet(summary)
        if coverage and intent.intent != "count_aggregate":
            bullets.append(coverage)

    # De-duplicate while preserving order; never overwhelm (cap 4).
    seen: set[str] = set()
    unique: list[str] = []
    for b in bullets:
        if b and b not in seen:
            seen.add(b)
            unique.append(b)
    return unique[:4]


# --------------------------------------------------------------------- #
# Numeric helpers                                                        #
# --------------------------------------------------------------------- #
def _is_num(value: Any) -> bool:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return False
    return f == f and abs(f) < 1e38


def _fmt(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}"


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(a)))


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0
