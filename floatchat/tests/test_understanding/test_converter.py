"""Deterministic conversion tests — ontology grounding, ambiguity handling,
and SemanticUnderstanding → ParsedIntent conversion (Phase 2).

No LLM anywhere: understandings are constructed directly (that is the point
of the split — conversion is deterministic and unit-testable offline).
"""

from __future__ import annotations

from floatchat.ontology.intents import INTENT_DEFINITIONS
from floatchat.ontology.regions import REGIONS
from floatchat.ontology.variables import VARIABLES
from floatchat.understanding.converter import (
    SemanticConverter,
    ground_intent_name,
    ground_region_mention,
    ground_variable_mention,
)
from floatchat.understanding.models import SemanticUnderstanding


def make_understanding(**fields) -> SemanticUnderstanding:
    """Build a confident understanding (bypasses confidence/ambiguity gates)."""
    fields.setdefault("confidence", 0.95)
    return SemanticUnderstanding.model_validate(fields)


def convert(**fields):
    return SemanticConverter().convert(make_understanding(**fields))


# --------------------------------------------------------------------------- #
# Ontology grounding primitives
# --------------------------------------------------------------------------- #


class TestVariableGrounding:
    def test_canonical_name_grounds_to_itself(self):
        assert ground_variable_mention("DOXY") == "DOXY"

    def test_synonym_grounds(self):
        assert ground_variable_mention("oxygen") == "DOXY"
        assert ground_variable_mention("salt") == "PSAL"
        assert ground_variable_mention("water temp") == "TEMP"

    def test_filler_suffix_is_stripped(self):
        assert ground_variable_mention("oxygen levels") == "DOXY"
        assert ground_variable_mention("nitrate concentration") == "NITRATE"
        assert ground_variable_mention("chlorophyll content") == "CHLA"

    def test_abbreviation_grounds(self):
        # DOXY abbreviations: o2, dox (exact in index); "chl"/"no3" route via
        # the ontology's typo-correction map — same source the parser uses.
        assert ground_variable_mention("o2") == "DOXY"
        assert ground_variable_mention("chl") == "CHLA"
        assert ground_variable_mention("no3") == "NITRATE"

    def test_typo_corrects_via_ontology_map(self):
        assert ground_variable_mention("tembaratre") == "TEMP"
        assert ground_variable_mention("salinty") == "PSAL"
        assert ground_variable_mention("chlorophyl") == "CHLA"

    def test_adjusted_name_grounds_to_base_variable(self):
        assert ground_variable_mention("DOXY_ADJUSTED") == "DOXY"

    def test_known_but_unregistered_variable_grounds(self):
        # Parser-known variable outside the registry (legacy distinction).
        assert ground_variable_mention("irradiance 380") == "DOWN_IRRADIANCE380"

    def test_unknown_variable_does_not_ground(self):
        assert ground_variable_mention("cadmium") is None
        assert ground_variable_mention("heavy metal content") is None

    def test_every_ontology_variable_is_groundable_by_canonical(self):
        for canonical in VARIABLES:
            assert ground_variable_mention(canonical) == canonical


class TestRegionGrounding:
    def test_display_name_grounds(self):
        assert ground_region_mention("Arabian Sea") == "arabian_sea"

    def test_canonical_snake_and_space_forms_ground(self):
        assert ground_region_mention("bay_of_bengal") == "bay_of_bengal"
        assert ground_region_mention("bay of bengal") == "bay_of_bengal"

    def test_leading_article_is_ignored(self):
        assert ground_region_mention("the arabian sea") == "arabian_sea"

    def test_place_name_spelling_grounds(self):
        # place_names include e.g. "arabian" for arabian_sea
        assert ground_region_mention("arabian") == "arabian_sea"

    def test_unknown_region_does_not_ground(self):
        assert ground_region_mention("baltic sea") is None
        assert ground_region_mention("dead sea") is None

    def test_every_ontology_region_is_groundable(self):
        for canonical, region in REGIONS.items():
            assert ground_region_mention(region.display_name) == canonical
            assert ground_region_mention(canonical) == canonical


class TestIntentGrounding:
    def test_every_ontology_intent_name_grounds(self):
        for name in INTENT_DEFINITIONS:
            assert ground_intent_name(name) == name

    def test_lenient_surface_forms(self):
        assert ground_intent_name("Profile Plot") == "profile_plot"
        assert ground_intent_name("comparison-plot") == "comparison_plot"

    def test_unknown_intent_does_not_ground(self):
        assert ground_intent_name("do_the_science_thing") is None


# --------------------------------------------------------------------------- #
# Synonym understanding → identical ParsedIntent (paraphrase tolerance)
# --------------------------------------------------------------------------- #


class TestSynonymParaphraseEquivalence:
    def test_different_spellings_of_the_same_variable_convert_identically(self):
        intents = {
            phrase: convert(
                intent_name="profile_plot",
                variable_mentions=[phrase],
                region_mentions=["arabian sea"],
            ).parsed_intent
            for phrase in ("oxygen", "dissolved oxygen", "oxygen levels", "o2", "DOXY")
        }
        dumps = {p: i.model_dump() for p, i in intents.items()}
        assert len({str(d) for d in dumps.values()}) == 1
        assert next(iter(intents.values())).variables == ["DOXY"]

    def test_different_spellings_of_the_same_region_convert_identically(self):
        for phrase in ("arabian sea", "the Arabian Sea", "arabian_sea", "ARABIAN SEA"):
            intent = convert(
                intent_name="region_search",
                variable_mentions=["oxygen"],
                region_mentions=[phrase],
            ).parsed_intent
            assert intent.region == "arabian_sea", phrase


# --------------------------------------------------------------------------- #
# ParsedIntent conversion (happy paths, per intent family)
# --------------------------------------------------------------------------- #


class TestParsedIntentConversion:
    def test_profile_plot_full_conversion(self):
        outcome = convert(
            intent_name="profile_plot",
            variable_mentions=["oxygen levels", "tembaratre"],
            region_mentions=["the arabian sea"],
            temporal={"year": 2024, "season": "monsoon"},
        )
        intent = outcome.parsed_intent
        assert outcome.kind == "intent"
        assert intent.intent == "profile_plot"
        assert intent.variables == ["DOXY", "TEMP"]
        assert intent.region == "arabian_sea"
        assert intent.year == 2024
        # season → month-window mirrors the regex parser exactly
        assert intent.month_window == [6, 7, 8, 9]
        assert intent.month == 6

    def test_trajectory_with_float(self):
        intent = convert(
            intent_name="trajectory", float_ids=["2902403"]
        ).parsed_intent
        assert intent.intent == "trajectory"
        assert intent.float_id == "2902403"

    def test_metadata_lookup(self):
        intent = convert(
            intent_name="metadata_lookup", float_ids=["1901897"]
        ).parsed_intent
        assert intent.intent == "metadata_lookup"
        assert intent.float_id == "1901897"

    def test_ts_diagram(self):
        intent = convert(
            intent_name="ts_diagram",
            region_mentions=["bay of bengal"],
            temporal={"year": 2023},
        ).parsed_intent
        assert intent.intent == "ts_diagram"
        assert intent.region == "bay_of_bengal"

    def test_count_aggregate_existence_check(self):
        intent = convert(
            intent_name="count_aggregate",
            variable_mentions=["oxygen"],
            place_mentions=["goa"],
            existence_check=True,
        ).parsed_intent
        assert intent.intent == "count_aggregate"
        assert intent.existence_check is True
        # gazetteer grounding (offline local table)
        assert intent.lat is not None and intent.lon is not None
        assert intent.radius_km is not None

    def test_nearest_float_with_injected_place_resolver(self):
        spy_calls = []

        def fake_resolver(place):
            spy_calls.append(place)
            return {"lat": 15.3, "lon": 73.9, "radius_km": 100}

        converter = SemanticConverter(place_resolver=fake_resolver)
        outcome = converter.convert(
            make_understanding(
                intent_name="nearest_float", place_mentions=["goa"]
            )
        )
        intent = outcome.parsed_intent
        assert spy_calls == ["goa"]
        assert intent.lat == 15.3 and intent.lon == 73.9
        assert intent.radius_km == 100

    def test_place_resolver_not_called_when_region_present(self):
        """Parity with the regex parser: a resolved region suppresses the
        gazetteer entirely (prevents ocean names being geocoded as cities)."""
        spy_calls = []

        def spy(place):
            spy_calls.append(place)
            return None

        converter = SemanticConverter(place_resolver=spy)
        outcome = converter.convert(
            make_understanding(
                intent_name="profile_plot",
                variable_mentions=["oxygen"],
                region_mentions=["arabian sea"],
                place_mentions=["goa"],
            )
        )
        assert spy_calls == []
        assert outcome.parsed_intent.region == "arabian_sea"
        assert outcome.parsed_intent.lat is None

    def test_depth_bounds(self):
        intent = convert(
            intent_name="profile_plot",
            variable_mentions=["temperature"],
            float_ids=["2902403"],
            depth={"min": 200.0, "max": 1000.0},
        ).parsed_intent
        assert intent.depth_min == 200.0
        assert intent.depth_max == 1000.0

    def test_explicit_coordinates_and_radius(self):
        intent = convert(
            intent_name="radius_search",
            spatial={"lat": 15.0, "lon": 72.0, "radius_km": 50.0},
        ).parsed_intent
        assert intent.lat == 15.0 and intent.lon == 72.0
        assert intent.radius_km == 50.0

    def test_operational_filter_alive(self):
        intent = convert(
            intent_name="region_search",
            variable_mentions=["temperature"],
            region_mentions=["arabian sea"],
            operational_filter="ALIVE",
        ).parsed_intent
        assert intent.operational_filter == "alive"

    def test_operational_filter_other_values_dropped(self):
        intent = convert(
            intent_name="region_search",
            variable_mentions=["temperature"],
            region_mentions=["arabian sea"],
            operational_filter="dead",
        ).parsed_intent
        assert intent.operational_filter is None

    def test_explicit_iso_dates(self):
        intent = convert(
            intent_name="time_series",
            variable_mentions=["temperature"],
            region_mentions=["arabian sea"],
            temporal={"date_start": "2023-01-01", "date_end": "2024-01-01"},
        ).parsed_intent
        assert intent.temporal_date_start == "2023-01-01"
        assert intent.temporal_date_end == "2024-01-01"


# --------------------------------------------------------------------------- #
# Comparison handling (mirrors the regex parser contract)
# --------------------------------------------------------------------------- #


class TestComparisonConversion:
    def test_two_floats_upgrade_profile_plot_to_comparison(self):
        intent = convert(
            intent_name="profile_plot",
            variable_mentions=["temperature"],
            comparison={"is_comparison": True, "float_ids": ["2903467", "2902403"]},
        ).parsed_intent
        assert intent.intent == "comparison_plot"
        # parser contract: full sorted list + first id also primary
        assert intent.comparison_float_ids == ["2902403", "2903467"]
        assert intent.float_id == "2902403"

    def test_two_regions_upgrade_to_comparison(self):
        intent = convert(
            intent_name="profile_plot",
            variable_mentions=["salinity"],
            comparison={
                "is_comparison": True,
                "region_mentions": ["arabian sea", "bay of bengal"],
            },
        ).parsed_intent
        assert intent.intent == "comparison_plot"
        assert intent.comparison_regions == ["arabian_sea", "bay_of_bengal"]
        # parser contract: primary region = first comparison region
        assert intent.region == "arabian_sea"

    def test_two_float_ids_alone_imply_comparison(self):
        intent = convert(
            intent_name="profile_plot",
            variable_mentions=["oxygen"],
            float_ids=["1901897", "2902403"],
        ).parsed_intent
        assert intent.intent == "comparison_plot"
        assert intent.comparison_float_ids == ["1901897", "2902403"]


# --------------------------------------------------------------------------- #
# Value validation: nothing invented, invalid values dropped with ambiguity
# --------------------------------------------------------------------------- #


class TestNoInvention:
    def test_unknown_variable_is_dropped_with_ambiguity(self):
        outcome = convert(
            intent_name="profile_plot",
            variable_mentions=["cadmium", "oxygen"],
            float_ids=["2902403"],
        )
        assert outcome.parsed_intent.variables == ["DOXY"]
        fields = [a.field for a in outcome.ambiguities]
        assert "variables" in fields

    def test_fabricated_float_id_is_dropped(self):
        outcome = convert(
            intent_name="trajectory", float_ids=["ABC123", "2902403"]
        )
        assert outcome.parsed_intent.float_id == "2902403"

    def test_year_out_of_range_dropped(self):
        outcome = convert(
            intent_name="profile_plot",
            variable_mentions=["temperature"],
            region_mentions=["arabian sea"],
            temporal={"year": 1810},
        )
        assert outcome.parsed_intent.year is None
        assert any(a.field == "temporal" for a in outcome.ambiguities)

    def test_month_out_of_range_dropped(self):
        outcome = convert(
            intent_name="profile_plot",
            variable_mentions=["temperature"],
            region_mentions=["arabian sea"],
            temporal={"month": 13},
        )
        assert outcome.parsed_intent.month is None

    def test_profile_number_must_be_positive(self):
        outcome = convert(
            intent_name="profile_plot",
            variable_mentions=["temperature"],
            float_ids=["2902403"],
            profile_number=0,
        )
        assert outcome.parsed_intent.profile_number is None

    def test_latitude_longitude_must_come_as_pair(self):
        outcome = convert(
            intent_name="nearest_float",
            spatial={"lat": 15.0, "lon": None},
        )
        assert outcome.parsed_intent.lat is None
        assert outcome.parsed_intent.lon is None
        assert any(a.field == "spatial" for a in outcome.ambiguities)

    def test_out_of_range_coordinates_dropped(self):
        outcome = convert(
            intent_name="nearest_float",
            spatial={"lat": 95.0, "lon": 72.0},
        )
        assert outcome.parsed_intent.lat is None
        assert outcome.parsed_intent.lon is None

    def test_negative_depth_dropped(self):
        outcome = convert(
            intent_name="profile_plot",
            variable_mentions=["temperature"],
            float_ids=["2902403"],
            depth={"min": -5.0, "max": 100.0},
        )
        assert outcome.parsed_intent.depth_min is None
        assert outcome.parsed_intent.depth_max == 100.0

    def test_unknown_season_dropped_with_ambiguity(self):
        outcome = convert(
            intent_name="profile_plot",
            variable_mentions=["temperature"],
            region_mentions=["arabian sea"],
            temporal={"season": "hombre"},
        )
        assert outcome.parsed_intent.month_window is None
        assert any(a.field == "temporal" for a in outcome.ambiguities)

    def test_invalid_iso_date_dropped(self):
        outcome = convert(
            intent_name="time_series",
            variable_mentions=["temperature"],
            region_mentions=["arabian sea"],
            temporal={"date_start": "15/01/2024"},
        )
        assert outcome.parsed_intent.temporal_date_start is None

    def test_unknown_intent_name_stays_unknown_with_ambiguity(self):
        """An ungrounded intent name must NOT trigger clarification — parity
        with the legacy 'unknown → suggestion message' path is preserved."""
        outcome = convert(intent_name="do_science_thing", confidence=0.9)
        assert outcome.kind == "intent"
        assert outcome.parsed_intent.intent == "unknown"
        assert any(a.field == "intent" for a in outcome.ambiguities)


# --------------------------------------------------------------------------- #
# Ambiguity handling → structured clarification (ask, never guess)
# --------------------------------------------------------------------------- #


class TestAmbiguityHandling:
    def test_explicit_clarification_request_passes_through(self):
        outcome = convert(
            intent_name="profile_plot",
            variable_mentions=["it"],
            requires_clarification=True,
            clarification_question="Which variable would you like to plot?",
        )
        assert outcome.kind == "clarification"
        assert outcome.parsed_intent is None
        assert outcome.clarification.question == "Which variable would you like to plot?"

    def test_clarification_question_is_generated_when_missing(self):
        outcome = convert(
            intent_name="unknown",
            variable_mentions=["oxygen"],
            requires_clarification=True,
        )
        assert outcome.kind == "clarification"
        assert "oxygen" in outcome.clarification.question  # echoes what was understood

    def test_confidence_below_threshold_clarifies(self):
        converter = SemanticConverter(min_confidence=0.8)
        outcome = converter.convert(
            make_understanding(
                intent_name="profile_plot",
                confidence=0.5,
                variable_mentions=["oxygen"],
                region_mentions=["arabian sea"],
            )
        )
        assert outcome.kind == "clarification"

    def test_confidence_at_threshold_converts(self):
        converter = SemanticConverter(min_confidence=0.8)
        outcome = converter.convert(
            make_understanding(
                intent_name="profile_plot",
                confidence=0.8,
                variable_mentions=["oxygen"],
                region_mentions=["arabian sea"],
            )
        )
        assert outcome.kind == "intent"

    def test_ungroundable_region_with_no_scope_clarifies_with_candidates(self):
        outcome = convert(
            intent_name="region_search",
            variable_mentions=["oxygen"],
            region_mentions=["baltic sea"],
        )
        assert outcome.kind == "clarification"
        assert "baltic sea" in outcome.clarification.question
        assert outcome.clarification.field == "region"
        assert "Arabian Sea" in outcome.clarification.candidates

    def test_ungroundable_region_does_not_clarify_when_float_scope_exists(self):
        outcome = convert(
            intent_name="profile_plot",
            variable_mentions=["oxygen"],
            region_mentions=["baltic sea"],
            float_ids=["2902403"],
        )
        assert outcome.kind == "intent"
        assert outcome.parsed_intent.region is None
        assert outcome.parsed_intent.float_id == "2902403"

    def test_nearest_float_with_unresolvable_place_clarifies(self):
        converter = SemanticConverter(place_resolver=lambda place: None)
        outcome = converter.convert(
            make_understanding(intent_name="nearest_float", place_mentions=["middle of nowhere"])
        )
        assert outcome.kind == "clarification"
        assert outcome.clarification.field == "location"

    def test_llm_supplied_ambiguities_ride_along(self):
        outcome = convert(
            intent_name="profile_plot",
            variable_mentions=["oxygen"],
            region_mentions=["arabian sea"],
            requires_clarification=True,
            clarification_question="Which float?",
            ambiguities=[{"field": "float", "description": "two floats in context"}],
        )
        assert outcome.clarification.ambiguities[0].field == "float"

    def test_place_resolution_failure_never_crashes(self):
        def boom(place):
            raise RuntimeError("gazetteer boom")

        converter = SemanticConverter(place_resolver=boom)
        outcome = converter.convert(
            make_understanding(intent_name="nearest_float", place_mentions=["goa"])
        )
        assert outcome.kind == "clarification"  # unresolved place → ask
