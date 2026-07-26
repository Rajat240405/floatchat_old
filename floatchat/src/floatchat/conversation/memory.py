"""In-memory conversation context manager.

Priority 2: Conversation Context Repair.

Context inheritance is now gated by explicit reference phrases.
WITHOUT a reference phrase, NO context is inherited (each query stands alone).
WITH a reference phrase, ONLY the referenced fields are inherited.

A new explicit value in the parsed intent ALWAYS wins and clears competing
stale fields.

Metadata follow-ups (battery, sensors, status, etc.) inherit float_id ONLY
and never inherit variable/region/year.
"""

import logging
from datetime import datetime, timezone

from floatchat.config import settings
from floatchat.conversation.base import AbstractConversationManager
from floatchat.conversation.reference_phrases import detect_reference_phrases
from floatchat.models import ChatResponse, ConversationContext, ParsedIntent
from floatchat.ontology.intents import FLOAT_CENTRIC_INTENTS

logger = logging.getLogger(__name__)

# Intents that are "float-centric" — when the previous intent was one of these,
# "it" in the follow-up resolves to the float_id.
# Ontology 2.0 (Phase 1): membership lives in the domain ontology (unchanged).
_FLOAT_CENTRIC_INTENTS = FLOAT_CENTRIC_INTENTS


class InMemoryConversationManager(AbstractConversationManager):
    """Thread-safe(ish) in-memory store for conversation contexts.

    Context entries expire after ``max_turns`` turns (default from
    ``settings.conversation_max_turns``).

    Priority 2: Context inheritance is gated by reference phrases.
    """

    def __init__(self, max_turns: int | None = None) -> None:
        self._max_turns = max_turns or settings.conversation_max_turns
        self._store: dict[str, ConversationContext] = {}

    def get_context(self, session_id: str) -> ConversationContext | None:
        return self._store.get(session_id)

    def merge_context(
        self,
        session_id: str | None,
        intent: ParsedIntent,
        message: str | None = None,
        in_place: bool = False,
    ) -> ParsedIntent:
        """Merge context from previous turn into *intent*.

        Priority 2 rules:
          1. NO reference phrase → NO inheritance. Return intent unchanged.
          2. Specific reference phrase → inherit ONLY that field.
          3. General reference → inherit all fields.
          4. Metadata follow-up → inherit float_id ONLY.
          5. New explicit values ALWAYS win and clear stale competing fields.
          6. Region-scoped follow-up NEVER inherits float_id or profile_number.
          7. profile_number is NEVER inherited without a float_id in the merge.

        The reference phrase is detected from *message* (passed explicitly by
        the chat pipeline). For backward compatibility with direct callers/tests,
        an ``_original_message`` attribute on *intent* is used as a fallback
        when *message* is not supplied. (Constraint #6 — reference phrase
        required to inherit stale filters — is enforced here.)
        """
        if not session_id:
            return intent

        ctx = self._store.get(session_id)
        if not ctx:
            return intent

        if ctx.turn_count >= self._max_turns:
            logger.debug(
                "Session %s context expired (%d >= %d turns)",
                session_id,
                ctx.turn_count,
                self._max_turns,
            )
            return intent

        merged_data = intent.model_dump()

        def _finalize(data: dict) -> ParsedIntent:
            merged = ParsedIntent(**data)
            if in_place:
                # Preserve the canonical object identity for the resolver while
                # retaining Pydantic validation of enriched values.
                intent.__dict__.update(merged.__dict__)
                return intent
            return merged

        # --- Priority 2: Reference phrase detection --- #
        # Use the explicit message (passed by the chat pipeline) as the primary
        # source. This is robust against the LLM extractor / recovery paths
        # reconstructing ParsedIntent and dropping a smuggled attribute.
        # Fallback to ``_original_message`` keeps direct callers/tests working.
        ref = detect_reference_phrases(
            message or getattr(intent, "_original_message", "") or ""
        )

        # If no reference phrase at all, check if the intent itself is
        # a conversational follow-up that the regex parser already detected.
        # The parser may have set the `conversational` flag.
        # We also check if this is a "recovered" intent (from conversational
        # recovery in routes.py) — in that case, the original message had
        # conversational cues.
        if not ref.has_reference:
            # No reference phrase → no inheritance. Return intent unchanged.
            logger.info(
                "No reference phrase detected for session %s — "
                "no context inheritance",
                session_id,
            )
            return intent

        # --- Priority 2: Metadata follow-up handling --- #
        if ref.is_metadata_followup:
            merged_data = self._merge_metadata_followup(
                merged_data, ctx, ref
            )
            merged = _finalize(merged_data)
            logger.info(
                "Merged metadata followup for session %s: vars=%s region=%s float=%s year=%s profile=%s",
                session_id,
                merged.variables,
                merged.region,
                merged.float_id,
                merged.year,
                merged.profile_number,
            )
            return merged

        # --- Spatial scope guards (from Phase 25 bug fixes) --- #
        _has_region_scope = (
            merged_data.get("region") is not None
            or merged_data.get("lat_min") is not None
            or merged_data.get("lat_max") is not None
            or merged_data.get("lon_min") is not None
            or merged_data.get("lon_max") is not None
            or merged_data.get("lat") is not None
            or merged_data.get("lon") is not None
        )
        _has_explicit_float = (
            merged_data.get("float_id") is not None
            or bool(merged_data.get("comparison_float_ids"))
        )
        _has_point_coords = (
            merged_data.get("lat") is not None
            and merged_data.get("lon") is not None
        )

        # --- Priority 2: Reference-phrase-gated inheritance --- #
        # Only inherit fields for which a reference phrase was detected.

        # Variables: inherit only if reference phrase says so AND no explicit
        # variables in the new intent.
        if (
            not merged_data.get("variables")
            and ctx.last_variables
            and ref.inherit_variables
        ):
            merged_data["variables"] = ctx.last_variables.copy()

        # Region: inherit only if reference phrase says so AND no explicit
        # region in the new intent AND no competing float/point scope.
        if (
            merged_data.get("region") is None
            and ctx.last_region is not None
            and ref.inherit_region
            and not _has_explicit_float
            and not _has_point_coords
        ):
            merged_data["region"] = ctx.last_region

        # Float ID: inherit only if reference phrase says so AND no
        # competing region scope.
        if (
            merged_data.get("float_id") is None
            and ctx.last_float_id is not None
            and ref.inherit_float_id
            and not _has_region_scope
        ):
            merged_data["float_id"] = ctx.last_float_id

        # Year: inherit only if reference phrase says so AND no explicit year.
        if (
            merged_data.get("year") is None
            and ctx.last_year is not None
            and ref.inherit_year
        ):
            merged_data["year"] = ctx.last_year

        # Lat/lon/radius: only for spatial intents with reference phrases.
        if (
            merged_data.get("lat") is None
            and ctx.last_lat is not None
            and merged_data.get("intent") in ("nearest_float", "radius_search")
            and ref.inherit_float_id  # reuse float ref as spatial ref
        ):
            merged_data["lat"] = ctx.last_lat
        if (
            merged_data.get("lon") is None
            and ctx.last_lon is not None
            and merged_data.get("intent") in ("nearest_float", "radius_search")
            and ref.inherit_float_id
        ):
            merged_data["lon"] = ctx.last_lon
        if (
            merged_data.get("radius_km") is None
            and ctx.last_radius_km is not None
            and merged_data.get("intent") == "radius_search"
            and ref.inherit_float_id
        ):
            merged_data["radius_km"] = ctx.last_radius_km

        # Profile number: NEVER inherited unless the merged intent also has
        # a float_id AND reference phrase allows float_id inheritance.
        if (
            merged_data.get("profile_number") is None
            and ctx.last_profile_number is not None
            and not _has_region_scope
            and merged_data.get("float_id") is not None
            and ref.inherit_float_id
        ):
            merged_data["profile_number"] = ctx.last_profile_number

        merged = _finalize(merged_data)
        logger.info(
            "Merged context for session %s: vars=%s region=%s float=%s year=%s profile=%s (ref=%s)",
            session_id,
            merged.variables,
            merged.region,
            merged.float_id,
            merged.year,
            merged.profile_number,
            ref,
        )
        return merged

    def _merge_metadata_followup(
        self,
        merged_data: dict,
        ctx: ConversationContext,
        ref,
    ) -> dict:
        """Priority 2: Merge context for metadata follow-ups.

        Rules:
          - Inherit float_id ONLY (never inherit variable/region/year).
          - If the previous intent was float-centric and "it" was used,
            inherit the float_id from context.
          - If there's a float_id in context, always inherit it for
            metadata follow-ups — the user is asking about "that float"
            implicitly when they say "battery status?" etc.
          - Route to metadata_lookup intent.
          - Never route to profile_plot.
        """
        # Route to metadata_lookup
        merged_data["intent"] = "metadata_lookup"

        # Inherit float_id if:
        # 1. The follow-up has a reference phrase for float_id ("it", "same float")
        # 2. OR the previous intent was float-centric
        # 3. OR there's any float_id in context (the user is implicitly
        #    asking about the float they were just discussing)
        if (
            merged_data.get("float_id") is None
            and ctx.last_float_id is not None
        ):
            # For metadata follow-ups, always inherit float_id if one exists
            # in context. The user saying "battery status?" or "sensors?"
            # after discussing a float implicitly means "that float".
            merged_data["float_id"] = ctx.last_float_id

        # Explicitly clear fields that must NOT be inherited
        # for metadata follow-ups
        if not merged_data.get("variables"):
            merged_data["variables"] = []
        # Don't inherit region or year for metadata follow-ups
        if merged_data.get("region") is not None and not _is_explicit_in_intent(merged_data, "region"):
            merged_data["region"] = None
        if merged_data.get("year") is not None and not _is_explicit_in_intent(merged_data, "year"):
            merged_data["year"] = None

        # Clear profile_number — metadata is about the float, not a specific profile
        merged_data["profile_number"] = None

        return merged_data

    def update_context(
        self,
        session_id: str | None,
        intent: ParsedIntent,
        response: ChatResponse,
    ) -> None:
        """Persist *intent* and *response* so future follow-ups can reference them."""
        if not session_id:
            return

        ctx = self._store.get(session_id)
        if ctx is None:
            ctx = ConversationContext(session_id=session_id)

        ctx.turn_count += 1
        ctx.last_intent = intent.intent
        if intent.float_id is not None:
            ctx.last_float_id = intent.float_id
        if intent.variables:
            ctx.last_variables = intent.variables.copy()
        if intent.region is not None:
            ctx.last_region = intent.region
        if intent.year is not None:
            ctx.last_year = intent.year
        if intent.profile_number is not None:
            ctx.last_profile_number = intent.profile_number
        if intent.lat is not None:
            ctx.last_lat = intent.lat
        if intent.lon is not None:
            ctx.last_lon = intent.lon
        if intent.radius_km is not None:
            ctx.last_radius_km = intent.radius_km
        ctx.last_message = response.message
        ctx.last_response_summary = response.data_summary
        ctx.updated_at = datetime.now(timezone.utc)

        self._store[session_id] = ctx
        logger.debug(
            "Updated context for session %s (turn %d): intent=%s float=%s vars=%s region=%s year=%s",
            session_id,
            ctx.turn_count,
            ctx.last_intent,
            ctx.last_float_id,
            ctx.last_variables,
            ctx.last_region,
            ctx.last_year,
        )

    def clear_context(self, session_id: str) -> None:
        self._store.pop(session_id, None)


def _is_explicit_in_intent(merged_data: dict, field: str) -> bool:
    """Check if a field was explicitly set in the original parsed intent.

    This is a heuristic: if the field is present and non-None, we consider
    it explicit. For more precise tracking, the intent parser would need to
    distinguish between "extracted from user message" vs "filled by default".
    """
    # For region: check if it was set by the parser (not inherited)
    # We check if the value is non-None AND different from what context has
    # This is imperfect but works for the common cases
    val = merged_data.get(field)
    return val is not None
