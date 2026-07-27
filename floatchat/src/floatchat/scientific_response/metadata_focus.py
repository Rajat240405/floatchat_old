"""Sprint 4 — field-aware metadata presentation (focus detection + wording).

The execution layer already produces the correct metadata payload; this
module decides *which single field* the scientist asked about (the "focus")
and phrases exactly that answer — deterministically, from the payload only:

    metadata_focus(user_message, intent)  → one of ``FOCUS_VALUES``
    focused_narration(intent, summary, focus) → the one-sentence answer
    secondary_fact(intent, summary, focus)  → optional single extra fact

Honesty rules (mirroring the rest of the Scientific Response Layer):
missing/``"unknown"``/empty payload values are never dressed up — the
answer says the fact is not available in the local metadata index. Nothing
here calls an LLM, runs SQL, or invents values.
"""

from __future__ import annotations

import re
from typing import Any

from floatchat.models import ParsedIntent

#: The metadata fields a scientist can focus on, plus the broad-card form.
FOCUS_VALUES: frozenset[str] = frozenset(
    {
        "operator",
        "status",
        "last_seen",
        "profiles",
        "cycles",
        "sensors",
        "variables",
        "battery",
        "platform",
        "dac",
        "institution",
        "deployment",
        "metadata_summary",
    }
)

#: Unknown/empty payload spellings that must render as "not available".
_UNKNOWN_VALUES = {"", "unknown", "n/a", "none", "null"}


def _known(value: Any) -> str | None:
    """The payload value as display text, or ``None`` when it is missing
    or an explicit placeholder ("unknown", "N/A", …)."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in _UNKNOWN_VALUES:
        return None
    return text


# --------------------------------------------------------------------- #
# Focus detection — ordered rules, first match wins                     #
# --------------------------------------------------------------------- #
#: Broad "tell me everything" phrasings → the full metadata card. Checked
#: first so they are not swallowed by a field word inside the sentence
#: (e.g. "tell me about the float" must not hit the status rule).
_BROAD_RE = re.compile(
    r"tell\s+me\s+(?:more\s+)?about\s+(?:the\s+)?float\b"
    r"|describe\s+(?:the\s+)?float\b"
    r"|(?:show|display)(?:\s+me)?\s+(?:the\s+)?(?:full\s+|complete\s+)?"
    r"(?:metadata|info(?:rmation)?|details)\b"
)

#: Ordered (focus, pattern) rules. Deliberate ordering decisions:
#:  * sensors before variables — "which sensors" names hardware;
#:  * dac before operator — "Which DAC manages float X?" is a DAC question
#:    even though "manages" is an operator verb;
#:  * operator before deployment — "Who deployed float X?" asks for the
#:    operator, while "When was float X deployed?" asks for the date;
#:  * last_seen before status — "last report" is recency, "still active"
#:    is status.
_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("sensors", re.compile(r"\bsensors?\b|\binstruments?\b")),
    ("variables", re.compile(r"\bvariables?\b")),
    ("battery", re.compile(r"\bbattery\b|\bvoltage\b|\bpower\b")),
    (
        "platform",
        re.compile(
            r"\bplatform\b|\bprofiler\b|\bmodel\b|\bmanufactur(?:er|ed)\b|\bmake\b"
        ),
    ),
    ("dac", re.compile(r"\bdac\b|\bdata\s+assembly\b")),
    (
        "operator",
        re.compile(
            r"\bwho\s+(?:operates|owns|runs|manages|deployed|launched)\b"
            r"|\boperated\s+by\b|\bowners?\b|\boperators?\b|\bmanaged\s+by\b|\bowns\b"
        ),
    ),
    (
        "institution",
        re.compile(r"\binstitution\b|\borgani[sz]ations?\b"),
    ),
    (
        "last_seen",
        re.compile(
            r"\blast\s+(?:seen|report(?:ed)?|heard|contact|transmission)\b"
            r"|\bmost\s+recent\s+(?:report|contact|transmission)\b"
            r"|\bwhen\s+was\b[^.?!]*\blast\b"
        ),
    ),
    (
        "deployment",
        re.compile(
            r"\bwhen\s+was\b[^.?!]*\bdeployed\b"
            r"|\bdeployment\b|\blaunch(?:ed)?\b|\bfirst\s+profile\b"
        ),
    ),
    (
        "status",
        re.compile(
            r"\bstatus\b|\bstill\s+(?:active|alive|operating|running)\b"
            r"|\bis\b[^.?!]*\b(?:active|alive|dead|operational)\b|\bhealth\b"
        ),
    ),
    (
        "profiles",
        re.compile(
            r"\bhow\s+many\s+profiles?\b|\bprofile\s+count\b|\bnumber\s+of\s+profiles?\b"
        ),
    ),
    (
        "cycles",
        re.compile(
            r"\bhow\s+many\s+cycles?\b|\bnumber\s+of\s+cycles?\b|\bcycles?\s+(?:completed|done)\b"
        ),
    ),
)


def metadata_focus(user_message: str | None, intent: ParsedIntent | None = None) -> str:
    """Which metadata field the scientist's sentence focuses on.

    Deterministic wording-only signal read from the question; every VALUE
    rendered downstream comes from the execution payload. Broad requests
    ("Tell me about float X", "Show metadata for float X") return
    ``"metadata_summary"`` so the full card is composed.

    A float-scoped count ("How many profiles does float X have?") whose
    sentence matches no rule defaults to ``"profiles"`` — profiles are the
    only data unit the count executor counts within one float.
    """
    text = (user_message or "").strip().lower()
    if text:
        if _BROAD_RE.search(text):
            return "metadata_summary"
        for focus, pattern in _RULES:
            if pattern.search(text):
                return focus
    if intent is not None and intent.intent == "count_aggregate":
        return "profiles"
    return "metadata_summary"


# --------------------------------------------------------------------- #
# Focused narration — exactly the field asked about, from the payload   #
# --------------------------------------------------------------------- #
def _float_label(intent: ParsedIntent, info: dict[str, Any]) -> str:
    return str(intent.float_id or info.get("float_id") or "unknown")


def focused_narration(
    intent: ParsedIntent, summary: dict[str, Any], focus: str
) -> str:
    """The one-sentence answer to a focused metadata question.

    Every value comes from ``summary["float_info"]`` (the executor's
    payload). A missing/unknown value produces an honest
    "… not available in the local metadata index." sentence — never a
    guess. ``focus="metadata_summary"`` is handled by the broad narration
    path, not here.
    """
    info = summary.get("float_info") or {}
    fid = _float_label(intent, info)

    if focus == "operator":
        value = _known(info.get("institution")) or _known(info.get("dac"))
        if value:
            return f"Float {fid} is operated by {value}."
        return "The operating institution is not available in the local metadata index."

    if focus == "dac":
        value = _known(info.get("dac")) or _known(info.get("institution"))
        if value:
            return f"Float {fid} is managed by {value} (its data assembly centre)."
        return "The data assembly centre is not available in the local metadata index."

    if focus == "institution":
        value = _known(info.get("institution"))
        if value:
            return f"Float {fid} is registered to {value}."
        return "The registered institution is not available in the local metadata index."

    if focus == "status":
        value = _known(info.get("status"))
        if value:
            return f"Float {fid} is currently {value}."
        return "The operational status is not available in the local metadata index."

    if focus == "last_seen":
        value = _known(info.get("last_report_date"))
        if value:
            return f"Float {fid} was last reported on {value}."
        return "The last reported date is not available in the local metadata index."

    if focus == "profiles":
        count = info.get("profile_count")
        if count:
            return f"Float {fid} has {int(count):,} profiles on record."
        return "The profile count is not available in the local metadata index."

    if focus == "cycles":
        count = info.get("profile_count")
        if count:
            return f"Float {fid} has completed {int(count):,} cycles."
        return "The cycle count is not available in the local metadata index."

    if focus in ("sensors", "variables"):
        sensors = [
            str(s).strip()
            for s in (info.get("sensors") or [])
            if str(s).strip()
        ]
        if not sensors:
            if focus == "sensors":
                return "The installed sensor list is not available in the local metadata index."
            return "The available variable list is not available in the local metadata index."
        listing = "\n".join(f"• {s}" for s in sensors)
        if focus == "sensors":
            return f"Float {fid} carries:\n{listing}"
        # The local index records measured variables as the sensor payload.
        return f"Float {fid} measures (sensor payload):\n{listing}"

    if focus == "battery":
        voltage = info.get("battery_voltage")
        pct = info.get("battery_percentage")
        if voltage is None:
            return "Battery information is not available in the local metadata index."
        text = f"{voltage} V"
        if pct is not None:
            text += f" (~{pct}%)"
        status = _known(info.get("battery_status"))
        if status:
            text += f" — {status}"
        # The executor derives voltage from operational data (no tech.nc
        # reading exists), so the estimate is disclosed as such.
        return f"Float {fid} battery (estimated): {text}."

    if focus == "platform":
        value = _known(info.get("platform_type"))
        if value:
            return f"Float {fid} is a {value} platform."
        return "The platform type is not available in the local metadata index."

    if focus == "deployment":
        value = _known(info.get("deployment_date")) or _known(
            info.get("first_profile_date")
        )
        if value:
            # No dedicated deployment date exists in the index — the first
            # profile on record is the documented proxy (duckdb_lake).
            return f"Float {fid} was deployed around {value} (first profile on record)."
        return "The deployment date is not available in the local metadata index."

    # Unknown focus strings fall back to the broad-card opening line.
    return f"Metadata summary for Float {fid} from the local Argo metadata index."


def secondary_fact(
    intent: ParsedIntent, summary: dict[str, Any], focus: str
) -> str | None:
    """At most one secondary fact that adds context to a focused answer.

    Never repeats the field already stated in the narration; ``None`` when
    nothing meaningful is available. Rules:

      operator / dac / institution → operational status, else profile count
      last_seen                    → operational status
      status                       → last reported date
      everything else              → no secondary fact
    """
    info = summary.get("float_info") or {}
    status = _known(info.get("status"))
    last_seen = _known(info.get("last_report_date"))
    count = info.get("profile_count")

    if focus in ("operator", "dac", "institution"):
        if status:
            return f"It is currently {status}."
        if count:
            return f"It has {int(count):,} profiles on record."
        return None
    if focus == "last_seen":
        if status:
            return f"It is currently {status}."
        return None
    if focus == "status":
        if last_seen:
            return f"It was last reported on {last_seen}."
        return None
    return None
