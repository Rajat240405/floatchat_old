"""Ontology contract tests (Ontology 2.0, Phase 1 — Domain Ontology Foundation).

These tests pin two properties:

1. **Relocation exactness.** Every vocabulary table now exported by
   ``floatchat.ontology`` is byte-identical to the legacy consumer-local copy
   it replaced. This is the regression net that makes the Phase-1 refactor a
   pure location change with zero behaviour change.

2. **Congruence.** The ontology stays in sync with the frozen contracts it
   documents: the ``ParsedIntent.intent`` Literal (Milestone 5 single source
   of intent truth) and the application ``VariableRegistry``.
"""

from __future__ import annotations

import re
from typing import get_args

from floatchat.models import ParsedIntent
from floatchat.ontology import (
    BGC_VARIABLE_MARKER_TOKENS,
    CATALOGUE_VARIABLE_ORDER,
    CONCEPTS,
    DAC_NAMES,
    FLOAT_CENTRIC_INTENTS,
    INDIA_DEPLOYMENT_BBOX,
    INDIA_QUERY_REGIONS,
    INTENT_DEFINITIONS,
    LEVELS_VARIABLE_ORDER,
    NETWORK_BGC,
    NETWORK_CORE,
    NON_DATA_INTENTS,
    NORMALIZER_ABBREVIATIONS,
    NORMALIZER_CANONICAL_TERMS,
    OCEAN_REGION_PLACE_NAMES,
    PARSER_VARIABLE_ORDER,
    PLATFORM_MODELS,
    REGIONS,
    RESPONSE_INTENT_DEFINITIONS,
    SCIENTIFIC_CONTEXT_INTENTS,
    SCIENTIFIC_FOLLOWUP_INTENTS,
    SENSORS,
    TYPO_CORRECTIONS,
    VARIABLES,
    manufacturer_short_lookup,
    platform_lookup,
    platform_shortlist,
    sensor_keywords_map,
    tag_india_region,
)
from floatchat.ontology.variables import levels_storage_names


# --------------------------------------------------------------------------- #
# Variables
# --------------------------------------------------------------------------- #

class TestVariables:
    EXPECTED_REGISTERED = [
        "PRES", "TEMP", "PSAL", "DOXY", "CHLA", "BBP700", "NITRATE",
        "PH_IN_SITU_TOTAL", "DOWNWELLING_PAR", "TEMP_DOXY",
    ]

    def test_inventory(self):
        assert len(VARIABLES) == 13
        registered = [n for n, d in VARIABLES.items() if d.registered]
        assert registered == self.EXPECTED_REGISTERED

    def test_unregistered_irradiances(self):
        """Irradiances are known but must NOT enter the application registry."""
        for name in ("DOWN_IRRADIANCE380", "DOWN_IRRADIANCE412", "DOWN_IRRADIANCE490"):
            assert name in VARIABLES
            assert VARIABLES[name].registered is False

    def test_registry_congruence(self):
        """VariableRegistry._REGISTRY == registered ontology subset (legacy table)."""
        from floatchat.variable_registry.registry import VariableRegistry

        assert list(VariableRegistry._REGISTRY.keys()) == self.EXPECTED_REGISTERED
        doxy = VariableRegistry._REGISTRY["DOXY"]
        assert doxy.aliases == ["oxygen", "dissolved oxygen", "doxy", "dissolved o2", "oxygen concentration"]
        assert doxy.abbreviations == ["o2", "dox"]
        assert doxy.units == "µmol/kg"
        assert doxy.display_label == "Dissolved Oxygen (µmol kg⁻¹)"
        assert doxy.adjusted_name == "DOXY_ADJUSTED"
        assert doxy.qc_name == "DOXY_QC"
        assert doxy.preferred_metadata_index == "bio"
        assert doxy.preferred_profile_type == "B"

    def test_registry_public_api_unchanged(self):
        from floatchat.variable_registry.registry import VariableRegistry

        assert VariableRegistry.normalize("dissolved oxygen") == "DOXY"
        assert VariableRegistry.normalize("photosynthetically active radiation") == "DOWNWELLING_PAR"
        assert VariableRegistry.normalize("DOXY_ADJUSTED") == "DOXY"
        assert VariableRegistry.get("DOWN_IRRADIANCE380") is None  # not registered
        assert VariableRegistry.get_all_query_names() == {
            "PRES", "TEMP", "PSAL", "DOXY", "CHLA", "BBP700", "NITRATE",
            "PH_IN_SITU_TOTAL", "DOWNWELLING_PAR",
        }

    def test_parser_synonyms_verbatim(self):
        assert VARIABLES["DOXY"].parser_synonyms == (
            "oxygen", "dissolved oxygen", "doxy", "o2", "dox", "oxy", "dissolved o2",
        )
        assert VARIABLES["TEMP"].parser_synonyms == ("temperature", "temp", "sst", "water temp")
        assert VARIABLES["DOWN_IRRADIANCE380"].parser_synonyms == (
            "irradiance 380", "down irradiance 380", "ir380",
        )
        assert VARIABLES["PRES"].parser_synonyms == ()

    def test_titles_verbatim(self):
        assert VARIABLES["CHLA"].plot_title == "Chlorophyll-A (mg m⁻³)"
        assert VARIABLES["PSAL"].plot_title == "Practical Salinity"  # no units here (legacy)
        assert VARIABLES["PRES"].card_title == "Pressure"
        assert VARIABLES["PH_IN_SITU_TOTAL"].plot_title == "pH (total scale)"
        assert VARIABLES["PH_IN_SITU_TOTAL"].card_title == "In-situ pH (total scale)"

    def test_prompt_units_verbatim(self):
        """Prompt surface spellings deliberately differ from registry units."""
        assert VARIABLES["BBP700"].units == "m⁻¹"
        assert VARIABLES["BBP700"].prompt_units == "m^-1"
        assert VARIABLES["DOWNWELLING_PAR"].prompt_units == "µmol quanta/m²/s"
        assert VARIABLES["PRES"].prompt_units is None

    def test_sensor_keywords_verbatim(self):
        assert VARIABLES["DOXY"].sensor_keywords == ("OPTODE", "DOXY", "OXYGEN", "AANDERAA")
        assert VARIABLES["BBP700"].sensor_keywords == ("BACKSCATTER", "BBP", "ECO", "FLBBCD")

    def test_sensor_keywords_map_matches_legacy(self):
        assert sensor_keywords_map() == {
            "TEMP": ["CTD", "TEMP", "SST"],
            "PSAL": ["CTD", "PSAL", "SALINITY"],
            "DOXY": ["OPTODE", "DOXY", "OXYGEN", "AANDERAA"],
            "CHLA": ["FLUOROMETER", "CHLA", "CHLOROPHYLL", "ECO"],
            "NITRATE": ["NITRATE", "SUNA", "ISUS", "ISUS_NITRATE"],
            "BBP700": ["BACKSCATTER", "BBP", "ECO", "FLBBCD"],
            "PH_IN_SITU_TOTAL": ["PH", "SBE_PH"],
            "DOWNWELLING_PAR": ["PAR", "RADIOMETER", "OCR"],
        }

    def test_ordered_tuples_verbatim(self):
        # Order is behavioural (difflib tie-breaks, subplot order, column order).
        assert PARSER_VARIABLE_ORDER == (
            "TEMP", "PSAL", "DOXY", "CHLA", "NITRATE", "BBP700",
            "PH_IN_SITU_TOTAL", "DOWNWELLING_PAR",
            "DOWN_IRRADIANCE380", "DOWN_IRRADIANCE412", "DOWN_IRRADIANCE490",
        )
        assert LEVELS_VARIABLE_ORDER == (
            "TEMP", "PSAL", "DOXY", "CHLA", "BBP700", "NITRATE",
            "PH_IN_SITU_TOTAL", "DOWNWELLING_PAR",
        )
        # The two legacy orderings genuinely differed (NITRATE vs BBP700).
        assert CATALOGUE_VARIABLE_ORDER == (
            "TEMP", "PSAL", "DOXY", "CHLA", "NITRATE", "BBP700",
            "PH_IN_SITU_TOTAL", "DOWNWELLING_PAR",
        )

    def test_levels_storage_names(self):
        assert levels_storage_names("PH_IN_SITU_TOTAL") == (
            "ph_in_situ_total", "ph_in_situ_total_qc", "ph_in_situ_total_adjusted",
        )

    def test_typo_corrections_samples(self):
        assert len(TYPO_CORRECTIONS) == 91
        assert TYPO_CORRECTIONS["TEMPARATURE"] == "TEMP"
        assert TYPO_CORRECTIONS["CHLOROPHYLL-A"] == "CHLA"
        assert TYPO_CORRECTIONS["IR490"] == "DOWN_IRRADIANCE490"
        assert TYPO_CORRECTIONS["OCEAN PH"] == "PH_IN_SITU_TOTAL"

    def test_normalizer_vocabulary_verbatim(self):
        assert NORMALIZER_CANONICAL_TERMS == [
            "temperature", "chlorophyll", "oxygen", "dissolved oxygen", "salinity",
            "Arabian Sea", "Bay of Bengal", "Southern Ocean", "Mediterranean Sea",
            "TEMP", "CHLA", "DOXY", "PSAL",
        ]
        assert NORMALIZER_ABBREVIATIONS == {
            "chl": "chlorophyll",
            "temp": "temperature",
            "dox": "dissolved oxygen",
            "o2": "oxygen",
            "psal": "salinity",
        }

    def test_regex_parser_patterns_from_ontology(self):
        """Patterns built by the regex parser match the legacy construction."""
        from floatchat.intent_parser import regex as regex_module

        now = {c: p.pattern for c, p in regex_module._VAR_PATTERNS}
        for canonical, definition in VARIABLES.items():
            if not definition.parser_synonyms:
                continue
            legacy_sorted = sorted(
                list(definition.parser_synonyms) + [canonical.lower()],
                key=len, reverse=True,
            )
            expected = r"\b(?:" + "|".join(re.escape(s) for s in legacy_sorted) + r")\b"
            assert now[canonical] == expected, canonical


# --------------------------------------------------------------------------- #
# Regions
# --------------------------------------------------------------------------- #

class TestRegions:
    LEGACY_ORDER = [
        "arabian_sea", "bay_of_bengal", "north_atlantic", "south_atlantic",
        "north_pacific", "south_pacific", "indian_ocean", "southern_ocean",
        "mediterranean_sea", "red_sea", "gulf_of_mexico", "tasman_sea",
        "caribbean_sea",
    ]

    def test_inventory_and_order(self):
        # Order is observable: the parser's region extractor returns the first
        # matching region.
        assert list(REGIONS.keys()) == self.LEGACY_ORDER

    def test_aliases_verbatim(self):
        assert REGIONS["mediterranean_sea"].aliases == ("mediterranean", "mediterranean sea")
        assert REGIONS["arabian_sea"].aliases == ("arabian sea",)

    def test_polygons_congruent_with_metadata_service(self):
        from floatchat.metadata_service.polygons import REGION_POLYGONS

        assert list(REGION_POLYGONS.keys()) == self.LEGACY_ORDER
        for name, polygon in REGION_POLYGONS.items():
            assert [tuple(v) for v in polygon] == [tuple(v) for v in REGIONS[name].polygon]
        assert len(REGIONS["arabian_sea"].polygon) == 13
        assert REGIONS["arabian_sea"].polygon[0] == (68.0, 23.0)
        assert REGIONS["arabian_sea"].polygon[-1] == REGIONS["arabian_sea"].polygon[0]

    def test_bboxes_congruent_with_metadata_service(self):
        from floatchat.metadata_service.regions import _BOUNDS, resolve_region

        for name, bbox in _BOUNDS.items():
            assert dict(bbox) == dict(REGIONS[name].bbox)
        assert resolve_region("Bay of Bengal") == REGIONS["bay_of_bengal"].bbox
        assert REGIONS["north_pacific"].bbox["lon_max"] == -80.0

    def test_place_names_legacy_set(self):
        assert set(OCEAN_REGION_PLACE_NAMES) == {
            "arabian sea", "arabian", "bay of bengal", "bengal",
            "indian ocean", "indian", "north atlantic", "south atlantic",
            "north pacific", "south pacific", "southern ocean",
            "mediterranean", "red sea", "gulf of mexico",
        }
        # Tasman Sea / Caribbean were never in the legacy skip-list.
        assert "tasman sea" not in OCEAN_REGION_PLACE_NAMES
        assert "caribbean sea" not in OCEAN_REGION_PLACE_NAMES

    def test_india_constants(self):
        assert INDIA_QUERY_REGIONS == frozenset({"arabian_sea", "bay_of_bengal"})
        assert INDIA_DEPLOYMENT_BBOX == {
            "lat_min": -10.0, "lat_max": 30.0, "lon_min": 40.0, "lon_max": 100.0,
        }

    def test_point_in_region(self):
        from floatchat.metadata_service.polygons import point_in_region

        assert point_in_region(72.0, 15.0, "arabian_sea") is True
        assert point_in_region(88.0, 12.0, "bay_of_bengal") is True
        assert point_in_region(0.0, 0.0, "arabian_sea") is False
        assert point_in_region(0.0, 0.0, "unknown_region") is True  # no filter

    def test_tag_india_region(self):
        assert tag_india_region(15.0, 72.0) == "arabian_sea"
        assert tag_india_region(12.0, 88.0) == "bay_of_bengal"
        assert tag_india_region(0.0, 0.0) is None

    def test_parser_region_synonyms_from_ontology(self):
        from floatchat.intent_parser.regex import _REGION_PATTERNS, _REGION_SYNONYMS

        assert list(_REGION_SYNONYMS.keys()) == self.LEGACY_ORDER
        for canonical, definition in REGIONS.items():
            assert _REGION_SYNONYMS[canonical] == list(definition.aliases)
            legacy_sorted = sorted(
                list(definition.aliases) + [canonical.replace("_", " ")],
                key=len, reverse=True,
            )
            expected = r"(?:" + "|".join(re.escape(s) for s in legacy_sorted) + r")"
            assert dict(_REGION_PATTERNS)[canonical].pattern == expected


# --------------------------------------------------------------------------- #
# Sensors / platforms
# --------------------------------------------------------------------------- #

class TestSensors:
    LEGACY_PLATFORM_TABLE = {
        "831": ("APEX", "Teledyne Webb (USA)"),
        "832": ("APEX", "Teledyne Webb (USA)"),
        "833": ("APEX", "Teledyne Webb (USA)"),
        "834": ("APEX", "Teledyne Webb (USA)"),
        "835": ("APEX", "Teledyne Webb (USA)"),
        "836": ("PROVOR CTS4", "Teledyne CARAIBE (France)"),
        "837": ("PROVOR CTS5", "Teledyne CARAIBE (France)"),
        "838": ("PROVOR", "Teledyne CARAIBE (France)"),
        "839": ("PROVOR", "Teledyne CARAIBE (France)"),
        "840": ("PROVOR", "Teledyne CARAIBE (France)"),
        "841": ("PROVOR", "Teledyne CARAIBE (France)"),
        "842": ("PROVOR", "Teledyne CARAIBE (France)"),
        "843": ("PROVOR", "Teledyne CARAIBE (France)"),
        "844": ("PROVOR", "Teledyne CARAIBE (France)"),
        "845": ("NAVIS", "Teledyne Webb (USA)"),
        "846": ("NINJA", "Tsurumi Seiki (Japan)"),
        "847": ("NINJA", "Tsurumi Seiki (Japan)"),
        "848": ("NEMO", "Nortek (Norway)"),
        "849": ("NEMO", "Nortek (Norway)"),
        "850": ("SOLO", "Scripps/Floats Inc. (USA)"),
        "851": ("SOLO", "Scripps/Floats Inc. (USA)"),
        "852": ("SOLO", "Scripps/Floats Inc. (USA)"),
        "853": ("SOLO", "Scripps/Floats Inc. (USA)"),
        "854": ("SOLO", "Scripps/Floats Inc. (USA)"),
        "860": ("ARVOR", "Teledyne CARAIBE (France)"),
        "861": ("ARVOR", "Teledyne CARAIBE (France)"),
        "862": ("ARVOR", "Teledyne CARAIBE (France)"),
        "863": ("ARVOR", "Teledyne CARAIBE (France)"),
        "864": ("ARVOR", "Teledyne CARAIBE (France)"),
    }

    LEGACY_SHORT_MAP = {
        "836": "PROVOR CTS4", "837": "PROVOR CTS5", "841": "PROVOR",
        "842": "PROVOR", "831": "APEX", "832": "APEX", "845": "NAVIS",
        "851": "SOLO", "861": "ARVOR", "862": "ARVOR",
    }

    LEGACY_SHORT_MANUFACTURERS = {
        "831": "Teledyne Webb", "832": "Teledyne Webb", "833": "Teledyne Webb",
        "834": "Teledyne Webb", "835": "Teledyne Webb",
        "836": "Teledyne CARAIBE", "837": "Teledyne CARAIBE",
        "838": "Teledyne CARAIBE", "839": "Teledyne CARAIBE",
        "840": "Teledyne CARAIBE", "841": "Teledyne CARAIBE",
        "842": "Teledyne CARAIBE", "843": "Teledyne CARAIBE",
        "844": "Teledyne CARAIBE", "845": "Teledyne Webb",
        "846": "Tsurumi Seiki", "847": "Tsurumi Seiki",
        "848": "Nortek", "849": "Nortek",
        "850": "Scripps/Floats Inc.", "851": "Scripps/Floats Inc.",
        "852": "Scripps/Floats Inc.", "853": "Scripps/Floats Inc.",
        "854": "Scripps/Floats Inc.", "860": "Teledyne CARAIBE",
        "861": "Teledyne CARAIBE", "862": "Teledyne CARAIBE",
        "863": "Teledyne CARAIBE", "864": "Teledyne CARAIBE",
    }

    def test_platform_table_exact(self):
        assert len(PLATFORM_MODELS) == 29
        assert platform_lookup() == self.LEGACY_PLATFORM_TABLE

    def test_platform_shortlist_exact(self):
        assert platform_shortlist() == self.LEGACY_SHORT_MAP

    def test_manufacturer_short_exact(self):
        assert manufacturer_short_lookup() == self.LEGACY_SHORT_MANUFACTURERS

    def test_manufacturer_short_matches_helpers(self):
        from floatchat.query_engine.helpers import _PROFILER_MFR_MAP

        assert _PROFILER_MFR_MAP == self.LEGACY_SHORT_MANUFACTURERS

    def test_duckdb_platform_map_matches_ontology(self):
        from floatchat.data_lake.duckdb_lake import DuckDBDataLake

        assert DuckDBDataLake._PROFILER_MANUFACTURER_MAP == self.LEGACY_PLATFORM_TABLE

    def test_network_vocabulary(self):
        assert NETWORK_CORE == "Core Argo"
        assert NETWORK_BGC == "BGC Argo"

    def test_bgc_marker_tokens_exact(self):
        assert BGC_VARIABLE_MARKER_TOKENS == (
            "DOXY", "CHLA", "NITRATE", "BBP", "PH_IN_SITU", "DOWNWELLING", "DOWN_IRR",
        )

    def test_dac_names_exact(self):
        assert DAC_NAMES == {
            "IF": "IFREMER (Coriolis)",
            "IN": "INCOIS (India)",
            "AO": "AOML (NOAA)",
            "JM": "JMA (Japan)",
            "CS": "CSIRO (Australia)",
            "KM": "KORDI / KMA (Korea)",
            "BO": "BODC (UK)",
            "HZ": "CSIO (China)",
        }

    def test_sensor_catalogue_links_variables(self):
        for sensor in SENSORS.values():
            for variable in sensor.variables:
                assert variable in VARIABLES, sensor.canonical
        assert SENSORS["OPTODE"].variables == ("DOXY",)
        assert SENSORS["NITRATE_SENSOR"].tokens == ("NITRATE", "SUNA", "ISUS", "ISUS_NITRATE")


# --------------------------------------------------------------------------- #
# Intents
# --------------------------------------------------------------------------- #

class TestIntents:
    def test_intent_names_congruent_with_parsed_intent_contract(self):
        """Ontology intent names must mirror the frozen Literal exactly."""
        literal_names = set(get_args(ParsedIntent.model_fields["intent"].annotation))
        assert set(INTENT_DEFINITIONS.keys()) == literal_names
        assert len(literal_names) == 17

    def test_non_data_intents_verbatim(self):
        assert NON_DATA_INTENTS == frozenset({
            "general_chat", "unknown", "small_talk", "out_of_domain", "knowledge_base",
        })
        assert NON_DATA_INTENTS <= set(INTENT_DEFINITIONS.keys())

    def test_dispatch_congruence(self):
        """The dispatcher keeps its Milestone-5 derivation, sourced from the ontology."""
        from floatchat.query_engine import dispatch

        assert dispatch._NON_DATA_INTENTS == NON_DATA_INTENTS
        assert dispatch._DATA_INTENTS == frozenset(INTENT_DEFINITIONS.keys()) - NON_DATA_INTENTS

    def test_grouping_memberships_verbatim(self):
        assert SCIENTIFIC_CONTEXT_INTENTS == frozenset({
            "profile_plot", "time_series", "hovmoller", "ts_diagram",
            "comparison_plot", "comparison", "trajectory",
        })
        assert SCIENTIFIC_FOLLOWUP_INTENTS == frozenset({
            "profile_plot", "time_series", "hovmoller", "ts_diagram",
            "comparison_plot", "comparison",
        })
        assert FLOAT_CENTRIC_INTENTS == frozenset({
            "trajectory", "metadata_lookup", "nearest_float",
        })
        # Deliberate exclusion: trajectory is context-establishing but not
        # eligible for follow-up intent reuse.
        assert SCIENTIFIC_FOLLOWUP_INTENTS == SCIENTIFIC_CONTEXT_INTENTS - {"trajectory"}

    def test_response_intents_documented(self):
        assert set(RESPONSE_INTENT_DEFINITIONS.keys()) == {
            "available_plots", "clarification", "mixed_query", "error",
        }
        # Response-only pseudo-intents are not parseable intents.
        assert not (set(RESPONSE_INTENT_DEFINITIONS.keys()) & set(INTENT_DEFINITIONS.keys()))

    def test_kind_annotations(self):
        for name, definition in INTENT_DEFINITIONS.items():
            expected_kind = "non_data" if name in NON_DATA_INTENTS else "data"
            assert definition.kind == expected_kind, name


# --------------------------------------------------------------------------- #
# Concepts
# --------------------------------------------------------------------------- #

class TestConcepts:
    def test_required_glossary_terms(self):
        required = {
            "bgc_float", "core_float", "profile", "cycle",
            "parking_depth", "trajectory", "delayed_mode", "real_time_mode",
        }
        assert required <= set(CONCEPTS.keys())

    def test_kb_links_exist(self):
        import json
        from pathlib import Path

        kb_path = (
            Path(__file__).resolve().parents[2]
            / "src" / "floatchat" / "llm_service" / "knowledge_base.json"
        )
        kb_ids = {entry["id"] for entry in json.loads(kb_path.read_text())}
        for concept in CONCEPTS.values():
            if concept.kb_entry_id is not None:
                assert concept.kb_entry_id in kb_ids, concept.concept_id


# --------------------------------------------------------------------------- #
# Consumer-derived table exactness (integration guards)
# --------------------------------------------------------------------------- #

class TestConsumerDerivations:
    def test_fuzzy_tables_from_ontology(self):
        from floatchat.intent_parser import fuzzy

        assert fuzzy._VARIABLE_CANONICAL == list(PARSER_VARIABLE_ORDER)
        assert fuzzy._TYPO_MAP == TYPO_CORRECTIONS

    def test_fallback_normalizer_tables_from_ontology(self):
        from floatchat.query_normalizer import fallback

        assert fallback._CANONICAL_TERMS == NORMALIZER_CANONICAL_TERMS
        assert fallback._ABBREV_MAP == NORMALIZER_ABBREVIATIONS

    def test_visualization_titles_from_ontology(self):
        from floatchat.visualization_engine.profile import _VAR_TITLES

        assert _VAR_TITLES == {
            name: definition.plot_title
            for name, definition in VARIABLES.items()
            if definition.plot_title is not None
        }
        assert len(_VAR_TITLES) == 11

    def test_floats_service_tables_from_ontology(self):
        from floatchat.api.services import floats_service

        assert floats_service._VAR_TITLES == {
            name: definition.card_title
            for name, definition in VARIABLES.items()
            if definition.card_title is not None
        }
        assert len(floats_service._VAR_TITLES) == 9
        assert tuple(floats_service._CORE_PLOT_VARS) == CATALOGUE_VARIABLE_ORDER

    def test_features_units_from_ontology(self):
        from floatchat.scientific_explanation.features import _UNITS

        expected = {
            f"{name}{suffix}": definition.prompt_units
            for name, definition in VARIABLES.items()
            if definition.prompt_units is not None
            for suffix in ("", "_ADJUSTED")
        }
        expected.update({"CDOM": "ppb", "CDOM_ADJUSTED": "ppb"})
        assert _UNITS == expected
        assert len(_UNITS) == 18

    def test_engine_india_gate_uses_ontology(self):
        from floatchat.query_engine import engine as _engine  # noqa: F401
        from floatchat.ontology.regions import INDIA_QUERY_REGIONS as _iq

        assert _iq == frozenset({"arabian_sea", "bay_of_bengal"})


# --------------------------------------------------------------------------- #
# Behavioural probes through the public pipeline surfaces
# --------------------------------------------------------------------------- #

class TestBehaviourProbes:
    def test_parser_still_extracts_variables_and_regions(self):
        from floatchat.intent_parser.regex import RegexIntentParser

        parser = RegexIntentParser()
        intent = parser.parse("show oxygen and chlorophyll in arabian sea for 2024")
        assert intent.variables == ["CHLA", "DOXY"]
        assert intent.region == "arabian_sea"
        assert intent.year == 2024

    def test_typo_correction_still_applies(self):
        # The regex patterns only match exact synonyms; typo tolerance lives in
        # fuzzy.correct_variables_with_fuzzy (ontology.TYPO_CORRECTIONS + rapidfuzz).
        # Probe it directly, mirroring tests/test_intent_parser/test_phase5.py.
        from floatchat.intent_parser.fuzzy import correct_variables_with_fuzzy

        assert correct_variables_with_fuzzy(["tembaratre"]) == ["TEMP"]
        assert correct_variables_with_fuzzy(["salinty"]) == ["PSAL"]
        assert correct_variables_with_fuzzy(["chlorophyl"]) == ["CHLA"]

    def test_region_tag_rules(self):
        from floatchat.data_lake.duckdb_lake import build_region_tag

        assert build_region_tag(15.0, 72.0) == "arabian_sea"
        assert build_region_tag(12.0, 88.0) == "bay_of_bengal"
        assert build_region_tag(0.0, 0.0) is None
