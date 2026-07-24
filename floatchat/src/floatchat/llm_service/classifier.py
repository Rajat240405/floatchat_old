"""Query classifier — Phase 6: 4-Way Traffic Cop (v2 with improved small-talk & OOD).

Buckets:
1. DATA_QUERY, 2. SMALL_TALK, 3. OUT_OF_DOMAIN, 4. KNOWLEDGE_QUERY
"""

import logging
import re
from typing import Literal

from floatchat.config import settings
from floatchat.llm_service.base import AbstractLLMService

logger = logging.getLogger(__name__)

_CLASSIFIER_SYSTEM = (
    "You are a strict query classifier for FloatChat, an INCOIS oceanographic assistant.\n"
    "Classify into EXACTLY ONE label — output ONLY label:\n"
    "  DATA_QUERY     — ocean data, profiles, plots, float measurements, counts, spatial searches, including 'Actually chlorophyll', 'Nearest float to 15.5, 72.3'.\n"
    "  SMALL_TALK     — hi, hello, greetings, thanks, bye, who are you, what can you do, help, how to use.\n"
    "  OUT_OF_DOMAIN  — sports, politics, entertainment, cooking/recipes, stock market, capital of France, weather in London, coding (python script, sort array), general trivia unrelated to Argo.\n"
    "  KNOWLEDGE_QUERY — Argo program, biogeochemistry, float hardware: What is Argo?, BGC float?, parking depth?, battery lifespan.\n"
    "Examples: hi→SMALL_TALK, who won world cup→OUT_OF_DOMAIN, What is Argo float?→KNOWLEDGE_QUERY, Show oxygen in Arabian Sea→DATA_QUERY\n"
)

QueryType = Literal["DATA_QUERY", "SMALL_TALK", "OUT_OF_DOMAIN", "KNOWLEDGE_QUERY", "GENERAL_QUERY"]

# --------------------------------------------------------------------------- #
# Detectors
# --------------------------------------------------------------------------- #

_SMALL_TALK_REGEXES = [
    re.compile(r"^\s*(hi|hello|hey|howdy|greetings|good morning|good afternoon|good evening|good day)(\s+there)?[\s!.?,]*$", re.IGNORECASE),
    # Greeting + help in same sentence: "Hello, how do I use this?" -> should be small talk if no data
    re.compile(r"\b(hello|hi|hey)\b.*\b(how (do|can) i use|how to use|how does this work|guide me)\b", re.IGNORECASE),
    re.compile(r"\b(who are you|what are you|who made you|what is your name|what are you capable of|what can you do)\b", re.IGNORECASE),
    # Help patterns - not anchored, so "Hello, how do I use this?" matches
    re.compile(r"\b(help|show help|need help|help me|how (do|can) i use|how to use|how does this work|guide me|how (do|should) i start|how (do|should) i use this)\b", re.IGNORECASE),
    re.compile(r"^\s*(thanks|thank you|thankyou|thx|thanks a lot|thank you so much|ok thanks|okay thanks)\s*[!.]*\s*$", re.IGNORECASE),
    re.compile(r"^\s*(bye|goodbye|see you|see ya|adios)\s*[!.]*\s*$", re.IGNORECASE),
]

_OCEAN_RELEVANT_REGEX = re.compile(
    r"\b("
    r"argo|float|wmo|"
    r"temperature|temp|sst|salinity|psal|oxygen|doxy|dissolved oxygen|chlorophyll|chla|chlorophyll-a|"
    r"nitrate|ph|acidity|bbp|backscattering|irradiance|par|"
    r"arabian sea|bay of bengal|indian ocean|kerala|mumbai|chennai|goa|andaman|kochi|"
    r"profile|trajectory|time series|hovmoller|t[-\s]?s diagram|"
    r"nearest|within.*km|radius|"
    r"core|bgc|parking depth|"
    r"sensor|incois"
    r")\b",
    re.IGNORECASE,
)

_OOD_TRIGGERS = [
    re.compile(r"\b(messi|ronaldo|virat|kohli|cricket|football|basketball|ipl|world cup|olympics|fifa|nba)\b", re.IGNORECASE),
    re.compile(r"\b(prime minister|president|chief minister|minister of|election|parliament|bjp|congress|aap|politics|modi|rahul)\b", re.IGNORECASE),
    re.compile(r"\b(movie|movies|actor|actress|hollywood|bollywood|netflix|song|singer|music album|oscar)\b", re.IGNORECASE),
    # Cooking / recipe - expanded
    re.compile(r"\b(recipe|cooking|food recipe|how to cook|biryani|curry|butter chicken|butter-chicken|chicken tikka|dal|paneer)\b", re.IGNORECASE),
    re.compile(r"\b(bitcoin|stock market|share price|crypto|ethereum|nifty|sensex)\b", re.IGNORECASE),
    re.compile(r"\b(weather in (london|new york|paris|tokyo|berlin|los angeles|chicago|usa|uk|america|australia|canada|europe))\b", re.IGNORECASE),
    re.compile(r"\b(capital of|who won|age of|how old is|who is messi|who is ronaldo|who is the prime minister|who is president)\b", re.IGNORECASE),
    re.compile(r"\b(what is the capital|who is the president|who is the king|who is the queen)\b", re.IGNORECASE),
    # Coding - expanded for Phase 6 feedback
    re.compile(r"\b(python code|python script|javascript|java code|write a program|write code|write a python|sort an array|sort array|leetcode|algorithm|code snippet|function to sort|array sorting|python.*sort)\b", re.IGNORECASE),
    re.compile(r"\b(write|create|generate)\b.*\b(python|javascript|java|code|script|program)\b", re.IGNORECASE),
]

_KNOWLEDGE_REGEXES = [
    re.compile(r"\b(who|what) is (an? )?(argo|bgc|core)( float)?\b", re.IGNORECASE),
    re.compile(r"\b(what is|what are|who is|who are|explain|describe|tell me about)\b.*\b(argo|bgc|core float|core vs bgc|biogeochemical)\b", re.IGNORECASE),
    re.compile(r"\b(core vs bgc|difference between core and bgc|difference between bgc and core|bgc vs core)\b", re.IGNORECASE),
    re.compile(r"\b(parking depth|profile depth|how deep|how does argo work|how do argo floats work|argo cycle)\b", re.IGNORECASE),
    re.compile(r"\b(telemetry|argos|iridium|how do floats transmit|data transmission|gps fix)\b", re.IGNORECASE),
    re.compile(r"\b(battery|lifespan|how long do.*floats? last|float life|battery life|how long.*argo)\b", re.IGNORECASE),
    re.compile(r"\b(data quality|quality control|qc flag|real[-\s]?time vs delayed|delayed mode|real time mode)\b", re.IGNORECASE),
    re.compile(r"\b(what is wmo|wmo id|what is gdac|gdac|global data assembly)\b", re.IGNORECASE),
    re.compile(r"\b(what sensors|bgc sensors|what.*sensors?.*on.*float|what does.*float.*measure)\b", re.IGNORECASE),
    re.compile(r"\b(what is a profile|what is cycle number|what is pressure|how is depth measured)\b", re.IGNORECASE),
    re.compile(r"\b(why.*argo.*important|argo.*india|incois.*argo)\b", re.IGNORECASE),
    re.compile(r"\b(how many.*floats|global array|number of.*argo)\b", re.IGNORECASE),
    re.compile(r"\b(accuracy of|what is salinity|what is temperature|what is oxygen|what is chlorophyll|what is nitrate|what is ph)\b.*\?", re.IGNORECASE),
    re.compile(r"^\s*what is (argo|bgc|core|parking depth|wmo|gdac|a profile|cycle|pressure|salinity|temperature)\s*\??\s*$", re.IGNORECASE),
]

_DATA_FORCING_REGEXES = [
    re.compile(r"\b(float\s+\d{7}|wmo\s+\d{7}|\b\d{7}\b)\b", re.IGNORECASE),
    re.compile(r"\b(nearest|closest|within\s+\d+|radius|\d+\s*km)\b", re.IGNORECASE),
    re.compile(r"\b(show|plot|display|graph|visualize|fetch|get|find|compare)\b.*\b(oxygen|temperature|salinity|chlorophyll|nitrate|ph|bbp|float|profile|trajectory|ts diagram)\b", re.IGNORECASE),
    re.compile(r"\b(how many|count|number of|is there|are there)\b.*\b(profiles?|floats?|data)\b", re.IGNORECASE),
    re.compile(r"\b(in|near|around|for)\b.*\b(arabian sea|bay of bengal|kerala|mumbai|chennai|goa|indian ocean|kochi|andaman)\b", re.IGNORECASE),
    re.compile(r"\b(latitude|longitude|\d+\.?\d*\s*,\s*\d+\.?\d*)\b", re.IGNORECASE),
    # Specific for comparison
    re.compile(r"\bcompare\b.*\bfloat\b", re.IGNORECASE),
    re.compile(r"\btemperature\b.*\bnear\b.*\b(kerala|coast|arabian|bengal)\b", re.IGNORECASE),
]


def _has_data_force(text: str) -> bool:
    return any(p.search(text) for p in _DATA_FORCING_REGEXES)


def _is_small_talk(message: str) -> bool:
    text = message.strip()
    if len(text) > 250:
        return False
    # If strong data force, not small talk unless it's purely greeting + help without data terms
    if _has_data_force(text):
        # Exception: if it's greeting + data request like "Hello, can you show temperature near Kerala?" -> should be DATA, not SMALL_TALK
        # So if data force present, return False -> let DATA handling win
        # But if query is "Hello, how do I use this?" -> no data force, so small talk
        return False

    for pat in _SMALL_TALK_REGEXES:
        if pat.search(text):
            # Guard: if ocean relevant + help with longer query, treat as DATA e.g. "help me with oxygen data in Arabian Sea" (should be DATA)
            if _OCEAN_RELEVANT_REGEX.search(text) and "help" in text.lower() and len(text.split()) > 5:
                # Check if it also has data verb
                if re.search(r"\b(show|plot|find|oxygen|temperature|salinity|chlorophyll)\b", text.lower()):
                    # If help is accompanied by explicit data request, don't treat as small talk
                    # Example: "help me with oxygen data" - should NOT be small talk
                    # But "Hello, how do I use this?" - no data term, so small talk
                    continue
            return True
    return False


def _is_out_of_domain(message: str) -> bool:
    text = message.lower()
    # If contains ocean relevant terms, never OOD
    if _OCEAN_RELEVANT_REGEX.search(text):
        return False
    if _is_small_talk(message):
        return False
    for pat in _KNOWLEDGE_REGEXES:
        if pat.search(text):
            return False

    for pat in _OOD_TRIGGERS:
        if pat.search(text):
            return True

    # Coding heuristic: contains python/script/code/sort array and no ocean
    coding_terms = re.compile(r"\b(python|javascript|java|code|script|algorithm|sort.*array|array.*sort|recipe|butter chicken|biryani|cook)\b", re.IGNORECASE)
    if coding_terms.search(text):
        # Ensure no ocean terms (already checked) and not small talk
        return True

    generic_trivia = re.compile(
        r"^\s*(who|what|when|where|how old|why|age of|who is|who was|what is the|who won|who will)\b",
        re.IGNORECASE,
    )
    if generic_trivia.search(text):
        if not _OCEAN_RELEVANT_REGEX.search(text):
            return True

    return False


def _is_knowledge_query(message: str) -> bool:
    text = message.lower()
    data_force = _has_data_force(text)

    # Phase 4: Discovery language guard — checked FIRST, before any knowledge
    # regex. If the query contains "floats" + spatial/data-verb language,
    # it's a data query even if "argo" is mentioned.
    has_floats = bool(re.search(r"\bfloats?\b", text))
    has_spatial = bool(re.search(
        r"\b(?:near|around|within|in|off|by|close\s+to|vicinity)\b", text
    ))
    has_data_verb = bool(re.search(
        r"\b(?:show|find|list|get|display|plot|search|locate|identify)\b", text
    ))
    if has_floats and (has_spatial or has_data_verb) and not data_force:
        # Double-check: not asking "what is a float" (conceptual)
        if not re.search(r"\b(what\s+is|what\s+are|who\s+is|explain|describe)\b.*\bfloat\b", text):
            return False

    if data_force:
        conceptual = any(p.search(text) for p in _KNOWLEDGE_REGEXES)
        if conceptual:
            if re.search(r"\b(show|plot|display|nearest|within|how many|count|trajectory|t[-\s]?s diagram|hovmoller|compare)\b", text):
                return False
        else:
            return False

    for pat in _KNOWLEDGE_REGEXES:
        if pat.search(text):
            return True

    # Phase 4: Discovery language guard.
    # If the query contains "floats" (plural) + spatial language, it's a
    # data query even if "argo" is mentioned — the user wants to FIND floats,
    # not learn ABOUT them.
    has_floats = bool(re.search(r"\bfloats?\b", text))
    has_spatial = bool(re.search(
        r"\b(?:near|around|within|in|off|by|close\s+to|vicinity)\b", text
    ))
    has_data_verb = bool(re.search(
        r"\b(?:show|find|list|get|display|plot|search|locate|identify)\b", text
    ))
    if has_floats and (has_spatial or has_data_verb):
        return False

    # General fallback: any question containing "argo" without strong data markers is knowledge
    # This handles variations like "how is argo", "tell me about argo", "why argo", "is argo", etc.
    # without needing to hardcode every phrasing.
    if "argo" in text and not data_force:
        # Avoid small talk that mentions argo? No, if argo mentioned it's not small talk.
        if len(text.split()) <= 12:
            return True
        if re.search(r"\b(what|who|how|why|when|where|which|explain|describe|tell|difference|is|are|does|do|can|could|would|should|was|were)\b", text):
            # Additional guard: if it has data verbs like "show" + "temperature near", it's data, not knowledge (handled above)
            # So if no explicit show/plot with variable+location, treat as knowledge
            if not re.search(r"\b(show|plot|display|find|get|fetch).*(temperature|salinity|oxygen|chlorophyll|nitrate|ph|float|profile)\b", text):
                return True

    # Also handle BGC/Core questions without argo word: "what is BGC?" "what is parking depth?"
    if re.search(r"\b(what|how|why|explain).*\b(bgc|core|parking depth|battery|telemetry|wmo|gdac)\b", text):
        if not data_force:
            return True

    return False


SMALL_TALK_RESPONSE = (
    "👋 Hello! I'm FloatChat, your AI assistant for exploring Argo ocean data in the Indian region, built for INCOIS.\n\n"
    "I can help you:\n"
    "• Find Argo floats near a location or region (Arabian Sea, Bay of Bengal, Kerala, Mumbai, coordinates)\n"
    "• Plot temperature, salinity, oxygen, chlorophyll, nitrate, pH and other BGC variables\n"
    "• Visualize float trajectories, time-series, Hovmöller diagrams, and T-S diagrams\n"
    "• Answer vetted questions about Argo floats themselves (Core vs BGC, parking depth, battery, telemetry, data QC)\n\n"
    "Try these example queries:\n"
    "• \"Show floats near Kerala\"\n"
    "• \"Oxygen profile in Arabian Sea for 2024\"\n"
    "• \"T-S diagram for float 2902403\"\n"
    "• \"What is a BGC float?\"\n\n"
    "Just type your question — I'm scoped to India region (40-100E, -10-30N) for fast local DuckDB queries!"
)

OUT_OF_DOMAIN_RESPONSE = (
    "I am a specialized oceanographic assistant built for INCOIS. "
    "I can only answer questions related to Argo floats, ocean data, and marine variables "
    "(temperature, salinity, oxygen, chlorophyll, nitrate, pH, backscattering, irradiance) "
    "in the India region (Arabian Sea, Bay of Bengal, North Indian Ocean). For example, you can ask about float locations, "
    "profiles, trajectories, or what a BGC float is. "
    "How can I help you explore the ocean today?"
)


class QueryClassifier:
    def __init__(self, llm_service: AbstractLLMService) -> None:
        self._llm = llm_service

    @staticmethod
    def _active_scientific_context(context: object | None) -> bool:
        if context is None:
            return False
        last_intent = getattr(context, "last_intent", None)
        scientific_intents = {
            "profile_plot", "time_series", "hovmoller", "ts_diagram",
            "comparison_plot", "comparison", "trajectory",
        }
        return bool(
            last_intent in scientific_intents
            and (
                getattr(context, "last_float_id", None)
                or getattr(context, "last_profile_number", None)
                or getattr(context, "last_variables", None)
                or getattr(context, "last_response_summary", None)
            )
        )

    @staticmethod
    def _explicit_out_of_domain(message: str) -> bool:
        text = message.lower()
        return any(pattern.search(text) for pattern in _OOD_TRIGGERS) or bool(
            re.search(
                r"\b(python|javascript|java|code|script|algorithm|recipe|cook|sort.*array|array.*sort)\b",
                text,
                re.IGNORECASE,
            )
        )

    def classify(self, message: str, conversation_context: object | None = None) -> QueryType:
        if not message or not message.strip():
            return "SMALL_TALK"

        try:
            if _is_small_talk(message):
                logger.debug("Rule-based SMALL_TALK: %r", message)
                return "SMALL_TALK"
            if _is_out_of_domain(message):
                # Generic question forms are ambiguous in isolation. When a
                # scientific profile is active, route them into the data
                # conversation unless an explicit out-of-domain trigger is
                # present. This is state-based, not phrase-list based.
                if self._active_scientific_context(conversation_context) and not self._explicit_out_of_domain(message):
                    logger.info("Active scientific context overrides ambiguous OOD classification")
                    return "DATA_QUERY"
                logger.debug("Rule-based OUT_OF_DOMAIN: %r", message)
                return "OUT_OF_DOMAIN"
            if _is_knowledge_query(message):
                logger.debug("Rule-based KNOWLEDGE_QUERY: %r", message)
                return "KNOWLEDGE_QUERY"
        except Exception:
            logger.exception("Rule-based failed")

        if not settings.llm_enabled:
            return "DATA_QUERY"

        prompt = f'Classify:\n\"{message}\"\n\nOutput ONLY: DATA_QUERY, SMALL_TALK, OUT_OF_DOMAIN, KNOWLEDGE_QUERY'
        try:
            raw = self._llm.generate(prompt, system=_CLASSIFIER_SYSTEM)
        except Exception:
            return "DATA_QUERY"

        cleaned = raw.strip().upper()
        if "SMALL_TALK" in cleaned:
            return "SMALL_TALK"
        if "OUT_OF_DOMAIN" in cleaned or "OUT-OF-DOMAIN" in cleaned:
            return "OUT_OF_DOMAIN"
        if "KNOWLEDGE_QUERY" in cleaned or "KNOWLEDGE" in cleaned:
            return "KNOWLEDGE_QUERY"
        if "GENERAL_QUERY" in cleaned:
            return "KNOWLEDGE_QUERY"
        if "DATA_QUERY" in cleaned:
            return "DATA_QUERY"
        logger.warning("Unexpected classifier output %r", raw)
        return "DATA_QUERY"

    @staticmethod
    def get_small_talk_response() -> str:
        return SMALL_TALK_RESPONSE

    @staticmethod
    def get_out_of_domain_response() -> str:
        return OUT_OF_DOMAIN_RESPONSE
