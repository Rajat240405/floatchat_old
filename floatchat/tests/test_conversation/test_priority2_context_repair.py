"""Priority 2: Conversation Context Repair — Regression Tests.

Tests for the reference-phrase-gated context inheritance system.

Rules under test:
  1. NO reference phrase → NO context inheritance. Each query stands alone.
  2. Specific reference phrase → inherit ONLY the referenced field.
  3. General reference ("same", "that", "what about") → inherit ALL fields.
  4. "it" after a float-centric query → inherit float_id ONLY.
  5. Metadata follow-up patterns → inherit float_id ONLY, route to metadata_lookup.
  6. New explicit values ALWAYS win and clear stale competing fields.
  7. Region-scoped follow-up NEVER inherits float_id or profile_number.
  8. profile_number is NEVER inherited without a float_id in the merge.
"""

import pytest

from floatchat.conversation.memory import InMemoryConversationManager
from floatchat.conversation.reference_phrases import detect_reference_phrases
from floatchat.models import ChatResponse, ParsedIntent


def _seed(mgr, session, **fields):
    """Helper: write one prior turn into ctx with the given intent fields."""
    intent = ParsedIntent(intent=fields.pop("intent", "profile_plot"), **fields)
    mgr.update_context(
        session, intent, ChatResponse(intent=intent.intent, message="ok")
    )


def _merge_with_message(mgr, session, message, **intent_fields):
    """Helper: merge context with the original message for reference detection."""
    intent = ParsedIntent(intent=intent_fields.pop("intent", "profile_plot"), **intent_fields)
    intent.__dict__["_original_message"] = message
    return mgr.merge_context(session, intent)


# =========================================================================== #
# Reference Phrase Detection Unit Tests
# =========================================================================== #

class TestReferencePhraseDetection:
    """Unit tests for detect_reference_phrases()."""

    def test_no_reference_phrase(self) -> None:
        ref = detect_reference_phrases("temperature in Arabian Sea 2024")
        assert not ref.has_reference

    def test_spatial_reference_there(self) -> None:
        ref = detect_reference_phrases("chlorophyll there")
        assert ref.inherit_region
        assert not ref.inherit_year
        assert not ref.inherit_float_id

    def test_spatial_reference_same_region(self) -> None:
        ref = detect_reference_phrases("same region different variable")
        assert ref.inherit_region

    def test_temporal_reference_same_year(self) -> None:
        ref = detect_reference_phrases("same year but Bay of Bengal")
        assert ref.inherit_year
        assert not ref.inherit_region

    def test_float_reference_same_float(self) -> None:
        ref = detect_reference_phrases("same float different variable")
        assert ref.inherit_float_id

    def test_variable_reference_same_thing(self) -> None:
        ref = detect_reference_phrases("same thing for Bay of Bengal")
        assert ref.inherit_variables

    def test_general_reference_same(self) -> None:
        ref = detect_reference_phrases("same for Bay of Bengal")
        assert ref.has_general_ref
        assert ref.inherit_region
        assert ref.inherit_year
        assert ref.inherit_variables
        assert ref.inherit_float_id

    def test_general_reference_what_about(self) -> None:
        ref = detect_reference_phrases("what about 2022?")
        assert ref.has_general_ref
        assert ref.inherit_region
        assert ref.inherit_year

    def test_general_reference_compare_that(self) -> None:
        ref = detect_reference_phrases("compare that with Bay of Bengal")
        assert ref.has_general_ref

    def test_it_reference(self) -> None:
        ref = detect_reference_phrases("what sensors does it have?")
        assert ref.has_it_ref
        assert ref.inherit_float_id

    def test_metadata_followup_battery(self) -> None:
        ref = detect_reference_phrases("battery status?")
        assert ref.is_metadata_followup
        assert not ref.inherit_region
        assert not ref.inherit_year
        assert not ref.inherit_variables

    def test_metadata_followup_sensors(self) -> None:
        ref = detect_reference_phrases("what sensors does it have?")
        assert ref.is_metadata_followup
        assert ref.inherit_float_id  # "it" triggers float_id inheritance

    def test_metadata_followup_manufacturer(self) -> None:
        ref = detect_reference_phrases("who is the manufacturer?")
        assert ref.is_metadata_followup

    def test_no_false_positive_metadata(self) -> None:
        """'temperature in Arabian Sea' should NOT trigger metadata followup."""
        ref = detect_reference_phrases("temperature in Arabian Sea 2024")
        assert not ref.is_metadata_followup


# =========================================================================== #
# Context Inheritance Regression Tests
# =========================================================================== #

class TestNoReferencePhraseNoInheritance:
    """Priority 2 Rule 1: No reference phrase → no inheritance."""

    def test_fresh_query_no_inherit_region(self) -> None:
        mgr = InMemoryConversationManager()
        _seed(mgr, "s", variables=["TEMP"], region="arabian_sea", year=2024)

        # No reference phrase → no inheritance
        merged = _merge_with_message(
            mgr, "s", "oxygen in Bay of Bengal",
            variables=["DOXY"], region="bay_of_bengal",
        )
        # Explicit values preserved
        assert merged.region == "bay_of_bengal"
        assert merged.variables == ["DOXY"]
        # Year NOT inherited (no reference phrase)
        assert merged.year is None

    def test_fresh_query_no_inherit_float(self) -> None:
        mgr = InMemoryConversationManager()
        _seed(mgr, "s", variables=["DOXY"], float_id="2902403")

        # Fresh query without reference → no float_id inheritance
        merged = _merge_with_message(
            mgr, "s", "temperature in Arabian Sea",
            variables=["TEMP"], region="arabian_sea",
        )
        assert merged.float_id is None

    def test_fresh_query_no_inherit_year(self) -> None:
        mgr = InMemoryConversationManager()
        _seed(mgr, "s", variables=["TEMP"], region="arabian_sea", year=2024)

        # "oxygen in Arabian Sea" (no year, no reference) → year NOT inherited
        merged = _merge_with_message(
            mgr, "s", "oxygen in Arabian Sea",
            variables=["DOXY"], region="arabian_sea",
        )
        assert merged.year is None

    def test_show_floats_near_sri_lanka_standalone(self) -> None:
        mgr = InMemoryConversationManager()
        _seed(mgr, "s", variables=["TEMP"], region="arabian_sea", year=2024)

        # Radius search without reference phrase → no context leak
        merged = _merge_with_message(
            mgr, "s", "show floats near Sri Lanka",
            intent="radius_search", lat=7.87, lon=80.77,
        )
        assert merged.region is None  # No region inherited
        assert merged.year is None    # No year inherited
        assert merged.variables == [] # No variables inherited


class TestSameForBayOfBengal:
    """Bug 1: 'same for Bay of Bengal' must inherit variable+year, use NEW region."""

    def test_same_for_bay_of_bengal(self) -> None:
        mgr = InMemoryConversationManager()
        _seed(mgr, "s", variables=["TEMP"], region="arabian_sea", year=2024)

        # "same for Bay of Bengal" — "same" is a general reference,
        # parser extracts region=bay_of_bengal
        merged = _merge_with_message(
            mgr, "s", "same for Bay of Bengal",
            variables=[], region="bay_of_bengal",
        )
        # New region wins (explicit value)
        assert merged.region == "bay_of_bengal"
        # Variable inherited via "same"
        assert merged.variables == ["TEMP"]
        # Year inherited via "same"
        assert merged.year == 2024


class TestWhatAbout2022:
    """Bug 2: 'what about 2022?' must inherit variable+region, use NEW year."""

    def test_what_about_2022(self) -> None:
        mgr = InMemoryConversationManager()
        _seed(mgr, "s", variables=["TEMP"], region="arabian_sea", year=2024)

        # "what about 2022?" — "what about" is a general reference
        merged = _merge_with_message(
            mgr, "s", "what about 2022?",
            variables=[], year=2022,
        )
        # Variable inherited
        assert merged.variables == ["TEMP"]
        # Region inherited
        assert merged.region == "arabian_sea"
        # New year wins
        assert merged.year == 2022


class TestWhatSensorsDoesItHave:
    """Bug 3: 'what sensors does it have?' after float query → metadata_lookup."""

    def test_sensors_after_trajectory(self) -> None:
        mgr = InMemoryConversationManager()
        _seed(mgr, "s", variables=[], float_id="2902403", intent="trajectory")

        # "what sensors does it have?" — metadata followup with "it"
        merged = _merge_with_message(
            mgr, "s", "what sensors does it have?",
            intent="metadata_lookup",
        )
        # Must route to metadata_lookup
        assert merged.intent == "metadata_lookup"
        # Must inherit float_id via "it"
        assert merged.float_id == "2902403"
        # Must NOT inherit variable/region/year
        assert merged.variables == []
        assert merged.region is None
        assert merged.year is None

    def test_sensors_after_region_search_no_float(self) -> None:
        """'what sensors?' after region search with no float → no float to inherit."""
        mgr = InMemoryConversationManager()
        _seed(mgr, "s", variables=["TEMP"], region="arabian_sea", year=2024)

        merged = _merge_with_message(
            mgr, "s", "what sensors?",
            intent="metadata_lookup",
        )
        assert merged.intent == "metadata_lookup"
        # No float_id in context → can't inherit
        assert merged.float_id is None


class TestBatteryStatus:
    """Bug 4: 'battery status?' must route to metadata_lookup, NOT profile_plot."""

    def test_battery_after_oxygen_query(self) -> None:
        mgr = InMemoryConversationManager()
        _seed(mgr, "s", variables=["DOXY"], region="arabian_sea", year=2024)

        # "battery status?" — metadata followup
        merged = _merge_with_message(
            mgr, "s", "battery status?",
            intent="metadata_lookup",
        )
        assert merged.intent == "metadata_lookup"
        # Must NOT inherit DOXY, arabian_sea, 2024
        assert merged.variables == []
        assert merged.region is None
        assert merged.year is None

    def test_battery_after_float_discussion(self) -> None:
        mgr = InMemoryConversationManager()
        _seed(mgr, "s", variables=["DOXY"], float_id="2902403", region="arabian_sea")

        # "battery status?" after discussing float 2902403
        merged = _merge_with_message(
            mgr, "s", "battery status?",
            intent="metadata_lookup",
        )
        assert merged.intent == "metadata_lookup"
        # float_id inherited via metadata followup (previous was float-centric)
        assert merged.float_id == "2902403"
        # Must NOT inherit variable/region/year
        assert merged.variables == []
        assert merged.region is None


class TestCompareThatWithBayOfBengal:
    """Bug 5: 'compare that with Bay of Bengal' must inherit ONLY TEMP, not ALL vars."""

    def test_compare_that_inherits_only_relevant_vars(self) -> None:
        mgr = InMemoryConversationManager()
        _seed(mgr, "s", variables=["TEMP"], region="arabian_sea")

        # "compare that with Bay of Bengal" — "that" inherits context
        merged = _merge_with_message(
            mgr, "s", "compare that with Bay of Bengal",
            intent="comparison_plot", region="bay_of_bengal",
        )
        # Should inherit TEMP only, not all 8 variables
        assert merged.variables == ["TEMP"]
        # Region from new query
        assert merged.region == "bay_of_bengal"


class TestChlorophyllThere:
    """'chlorophyll there' — 'there' inherits region only."""

    def test_chlorophyll_there(self) -> None:
        mgr = InMemoryConversationManager()
        _seed(mgr, "s", variables=["PSAL"], region="bay_of_bengal", year=2023)

        # "chlorophyll there" — "there" is a spatial reference
        merged = _merge_with_message(
            mgr, "s", "chlorophyll there",
            variables=["CHLA"],
        )
        # Variable from new query
        assert merged.variables == ["CHLA"]
        # Region inherited via "there"
        assert merged.region == "bay_of_bengal"
        # Year NOT inherited (only region is referenced by "there")
        assert merged.year is None


class TestShowTemperature:
    """'show temperature' without reference → NO context inheritance."""

    def test_show_temperature_no_inherit(self) -> None:
        mgr = InMemoryConversationManager()
        _seed(mgr, "s", variables=["PSAL"], region="bay_of_bengal")

        # "show temperature" — no reference phrase
        merged = _merge_with_message(
            mgr, "s", "show temperature",
            variables=["TEMP"],
        )
        # Variable from new query
        assert merged.variables == ["TEMP"]
        # Region NOT inherited (no reference phrase)
        assert merged.region is None


class TestExplicitValueOverridesStaleContext:
    """Priority 2 Rule 6: New explicit values ALWAYS win."""

    def test_new_region_overrides_stale_region(self) -> None:
        mgr = InMemoryConversationManager()
        _seed(mgr, "s", variables=["TEMP"], region="arabian_sea", year=2024)

        # "same for Bay of Bengal" — new region overrides old
        merged = _merge_with_message(
            mgr, "s", "same for Bay of Bengal",
            variables=[], region="bay_of_bengal",
        )
        assert merged.region == "bay_of_bengal"

    def test_new_variable_overrides_stale_variable(self) -> None:
        mgr = InMemoryConversationManager()
        _seed(mgr, "s", variables=["PSAL"], region="bay_of_bengal")

        # "show temperature" with "same region" intent
        merged = _merge_with_message(
            mgr, "s", "show temperature in the same region",
            variables=["TEMP"],
        )
        # New variable wins
        assert merged.variables == ["TEMP"]
        # Region inherited via "same region"
        assert merged.region == "bay_of_bengal"


class TestMetadataFollowupInheritanceTable:
    """Priority 2: Complete inheritance table for metadata follow-ups.

    After discussing float X with variable Y in region Z:
      "battery status?"      → metadata_lookup, float_id=X only
      "what sensors does it have?" → metadata_lookup, float_id=X only
      "manufacturer?"        → metadata_lookup, float_id=X only
      "what about oxygen?"   → NOT metadata_lookup, variable=DOXY inherited
    """

    def test_battery_status_after_float_discussion(self) -> None:
        mgr = InMemoryConversationManager()
        _seed(mgr, "s", variables=["DOXY"], float_id="2902403",
              region="arabian_sea", year=2024)

        merged = _merge_with_message(
            mgr, "s", "battery status?",
            intent="metadata_lookup",
        )
        assert merged.intent == "metadata_lookup"
        assert merged.float_id == "2902403"
        assert merged.variables == []
        assert merged.region is None
        assert merged.year is None

    def test_sensors_after_float_discussion(self) -> None:
        mgr = InMemoryConversationManager()
        _seed(mgr, "s", variables=["DOXY"], float_id="2902403",
              region="arabian_sea", year=2024)

        merged = _merge_with_message(
            mgr, "s", "what sensors does it have?",
            intent="metadata_lookup",
        )
        assert merged.intent == "metadata_lookup"
        assert merged.float_id == "2902403"
        assert merged.variables == []
        assert merged.region is None
        assert merged.year is None

    def test_manufacturer_after_float_discussion(self) -> None:
        mgr = InMemoryConversationManager()
        _seed(mgr, "s", variables=["DOXY"], float_id="2902403",
              region="arabian_sea", year=2024)

        merged = _merge_with_message(
            mgr, "s", "who is the manufacturer?",
            intent="metadata_lookup",
        )
        assert merged.intent == "metadata_lookup"
        assert merged.float_id == "2902403"
        assert merged.variables == []
        assert merged.region is None

    def test_what_about_oxygen_is_not_metadata(self) -> None:
        """'what about oxygen?' is a data query, NOT metadata_lookup."""
        mgr = InMemoryConversationManager()
        _seed(mgr, "s", variables=["TEMP"], region="arabian_sea", year=2024)

        merged = _merge_with_message(
            mgr, "s", "what about oxygen?",
            variables=["DOXY"],
        )
        # NOT metadata_lookup
        assert merged.intent != "metadata_lookup"
        # Variable from new query
        assert merged.variables == ["DOXY"]
        # Region/year inherited via "what about" (general ref)
        assert merged.region == "arabian_sea"
        assert merged.year == 2024


class TestFullConversationSequences:
    """End-to-end conversation sequence tests matching the PDF bugs."""

    def test_sequence_temp_arabian_same_for_bob(self) -> None:
        """Turn 1: 'temperature in Arabian Sea 2024'
        Turn 2: 'same for Bay of Bengal'
        Expected: TEMP, Bay of Bengal, 2024"""
        mgr = InMemoryConversationManager()

        # Turn 1
        t1 = ParsedIntent(intent="region_search", variables=["TEMP"],
                          region="arabian_sea", year=2024)
        t1.__dict__["_original_message"] = "temperature in Arabian Sea 2024"
        m1 = mgr.merge_context("s", t1)
        mgr.update_context("s", m1, ChatResponse(intent="region_search", message="ok"))

        # Turn 2
        t2 = ParsedIntent(intent="region_search", variables=[],
                          region="bay_of_bengal")
        t2.__dict__["_original_message"] = "same for Bay of Bengal"
        m2 = mgr.merge_context("s", t2)

        assert m2.variables == ["TEMP"]
        assert m2.region == "bay_of_bengal"
        assert m2.year == 2024

    def test_sequence_salinity_bob_show_temperature(self) -> None:
        """Turn 1: 'salinity in Bay of Bengal'
        Turn 2: 'show temperature'
        Expected: TEMP, NO region (no reference phrase)"""
        mgr = InMemoryConversationManager()

        # Turn 1
        t1 = ParsedIntent(intent="region_search", variables=["PSAL"],
                          region="bay_of_bengal")
        t1.__dict__["_original_message"] = "salinity in Bay of Bengal"
        m1 = mgr.merge_context("s", t1)
        mgr.update_context("s", m1, ChatResponse(intent="region_search", message="ok"))

        # Turn 2: no reference phrase → no inheritance
        t2 = ParsedIntent(intent="profile_plot", variables=["TEMP"])
        t2.__dict__["_original_message"] = "show temperature"
        m2 = mgr.merge_context("s", t2)

        assert m2.variables == ["TEMP"]
        assert m2.region is None  # No reference → no inheritance!

    def test_sequence_trajectory_sensors_battery(self) -> None:
        """Turn 1: 'trajectory of float 2902403'
        Turn 2: 'what sensors does it have?'
        Turn 3: 'battery status?'
        Expected: all route to metadata_lookup with float_id=2902403"""
        mgr = InMemoryConversationManager()

        # Turn 1
        t1 = ParsedIntent(intent="trajectory", float_id="2902403")
        t1.__dict__["_original_message"] = "trajectory of float 2902403"
        m1 = mgr.merge_context("s", t1)
        mgr.update_context("s", m1, ChatResponse(intent="trajectory", message="ok"))

        # Turn 2
        t2 = ParsedIntent(intent="metadata_lookup")
        t2.__dict__["_original_message"] = "what sensors does it have?"
        m2 = mgr.merge_context("s", t2)

        assert m2.intent == "metadata_lookup"
        assert m2.float_id == "2902403"
        assert m2.variables == []
        assert m2.region is None

        mgr.update_context("s", m2, ChatResponse(intent="metadata_lookup", message="ok"))

        # Turn 3
        t3 = ParsedIntent(intent="metadata_lookup")
        t3.__dict__["_original_message"] = "battery status?"
        m3 = mgr.merge_context("s", t3)

        assert m3.intent == "metadata_lookup"
        assert m3.float_id == "2902403"
        assert m3.variables == []

    def test_sequence_oxygen_bob_chlorophyll_there(self) -> None:
        """Turn 1: 'salinity in Bay of Bengal 2023'
        Turn 2: 'chlorophyll there'
        Expected: CHLA, bay_of_bengal (via 'there'), year NOT inherited"""
        mgr = InMemoryConversationManager()

        # Turn 1
        t1 = ParsedIntent(intent="region_search", variables=["PSAL"],
                          region="bay_of_bengal", year=2023)
        t1.__dict__["_original_message"] = "salinity in Bay of Bengal 2023"
        m1 = mgr.merge_context("s", t1)
        mgr.update_context("s", m1, ChatResponse(intent="region_search", message="ok"))

        # Turn 2
        t2 = ParsedIntent(intent="profile_plot", variables=["CHLA"])
        t2.__dict__["_original_message"] = "chlorophyll there"
        m2 = mgr.merge_context("s", t2)

        assert m2.variables == ["CHLA"]
        assert m2.region == "bay_of_bengal"  # "there" = inherit region
        assert m2.year is None  # "there" only inherits region, not year

    def test_sequence_temp_arabian_compare_bob(self) -> None:
        """Turn 1: 'temperature in Arabian Sea'
        Turn 2: 'compare that with Bay of Bengal'
        Expected: comparison_plot, TEMP (inherited), bay_of_bengal"""
        mgr = InMemoryConversationManager()

        # Turn 1
        t1 = ParsedIntent(intent="region_search", variables=["TEMP"],
                          region="arabian_sea")
        t1.__dict__["_original_message"] = "temperature in Arabian Sea"
        m1 = mgr.merge_context("s", t1)
        mgr.update_context("s", m1, ChatResponse(intent="region_search", message="ok"))

        # Turn 2: "compare that" = general reference, variables left empty
        # (parser skips default 8-var fill for conversational follow-ups)
        t2 = ParsedIntent(intent="comparison_plot", variables=[],
                          region="bay_of_bengal")
        t2.__dict__["_original_message"] = "compare that with Bay of Bengal"
        m2 = mgr.merge_context("s", t2)

        # "compare that" inherits TEMP (not all 8 vars)
        assert m2.variables == ["TEMP"]
        assert m2.region == "bay_of_bengal"

    def test_sequence_temp_arabian_what_about_2022(self) -> None:
        """Turn 1: 'temperature in Arabian Sea 2024'
        Turn 2: 'what about 2022?'
        Expected: TEMP, arabian_sea, 2022"""
        mgr = InMemoryConversationManager()

        # Turn 1
        t1 = ParsedIntent(intent="region_search", variables=["TEMP"],
                          region="arabian_sea", year=2024)
        t1.__dict__["_original_message"] = "temperature in Arabian Sea 2024"
        m1 = mgr.merge_context("s", t1)
        mgr.update_context("s", m1, ChatResponse(intent="region_search", message="ok"))

        # Turn 2
        t2 = ParsedIntent(intent="profile_plot", variables=[], year=2022)
        t2.__dict__["_original_message"] = "what about 2022?"
        m2 = mgr.merge_context("s", t2)

        assert m2.variables == ["TEMP"]  # inherited via "what about"
        assert m2.region == "arabian_sea"  # inherited via "what about"
        assert m2.year == 2022  # new explicit value wins

    def test_sequence_oxygen_arabian_no_year_leak(self) -> None:
        """Turn 1: 'temperature in Arabian Sea 2024'
        Turn 2: 'oxygen in Arabian Sea'
        Expected: DOXY, arabian_sea, year=None (no leak)"""
        mgr = InMemoryConversationManager()

        # Turn 1
        t1 = ParsedIntent(intent="region_search", variables=["TEMP"],
                          region="arabian_sea", year=2024)
        t1.__dict__["_original_message"] = "temperature in Arabian Sea 2024"
        m1 = mgr.merge_context("s", t1)
        mgr.update_context("s", m1, ChatResponse(intent="region_search", message="ok"))

        # Turn 2: no reference phrase → no year inheritance
        t2 = ParsedIntent(intent="region_search", variables=["DOXY"],
                          region="arabian_sea")
        t2.__dict__["_original_message"] = "oxygen in Arabian Sea"
        m2 = mgr.merge_context("s", t2)

        assert m2.variables == ["DOXY"]
        assert m2.region == "arabian_sea"
        assert m2.year is None  # No reference phrase → no leak!

    def test_compare_that_with_default_vars_not_filled(self) -> None:
        """Priority 2: 'compare that' should NOT fill 8 default variables.
        The parser must leave variables empty for merge_context to fill."""
        from floatchat.intent_parser.regex import RegexIntentParser
        parser = RegexIntentParser()

        # "compare that with Bay of Bengal" — conversational follow-up
        # Parser should NOT fill the default 8 variables
        parsed = parser.parse("compare that with Bay of Bengal")
        assert parsed.intent == "comparison_plot"
        # Variables should be empty (not all 8) — context will fill via reference
        assert len(parsed.variables) <= 2  # At most 1-2 vars, NOT 8


class TestBackwardCompatibility:
    """Ensure existing behavior is preserved for non-conversational queries."""

    def test_fresh_session_no_inheritance(self) -> None:
        mgr = InMemoryConversationManager()
        p = ParsedIntent(intent="profile_plot", variables=["DOXY"],
                        region="arabian_sea")
        merged = mgr.merge_context("s", p)
        assert merged.model_dump() == p.model_dump()

    def test_explicit_values_preserved(self) -> None:
        mgr = InMemoryConversationManager()
        _seed(mgr, "s", variables=["DOXY"], region="arabian_sea", year=2024)

        # Explicit values always win
        merged = _merge_with_message(
            mgr, "s", "salinity in Bay of Bengal 2023",
            variables=["PSAL"], region="bay_of_bengal", year=2023,
        )
        assert merged.variables == ["PSAL"]
        assert merged.region == "bay_of_bengal"
        assert merged.year == 2023

    def test_clear_context_works(self) -> None:
        mgr = InMemoryConversationManager()
        _seed(mgr, "s", variables=["DOXY"], region="arabian_sea")
        mgr.clear_context("s")
        assert mgr.get_context("s") is None

    def test_multiple_sessions_isolated(self) -> None:
        mgr = InMemoryConversationManager()
        _seed(mgr, "sess-a", variables=["DOXY"], region="arabian_sea")
        _seed(mgr, "sess-b", variables=["CHLA"], region="north_atlantic")

        merged_a = _merge_with_message(
            mgr, "sess-a", "same for Bay of Bengal",
            variables=[], region="bay_of_bengal",
        )
        assert merged_a.variables == ["DOXY"]  # From sess-a context

        merged_b = _merge_with_message(
            mgr, "sess-b", "same for Bay of Bengal",
            variables=[], region="bay_of_bengal",
        )
        assert merged_b.variables == ["CHLA"]  # From sess-b context
