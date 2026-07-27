"""Ontology grounding of the understanding prompt (Phase 2 requirement).

The semantic layer's domain vocabulary must be generated FROM the Phase 1
ontology — never hand-copied. These tests prove every intent, variable,
region and concept in the ontology reaches the prompt, and that the prompt
changes automatically when the ontology does (no duplicated alias lists).
"""

from __future__ import annotations

from dataclasses import replace

from floatchat.ontology.concepts import CONCEPTS
from floatchat.ontology.intents import INTENT_DEFINITIONS
from floatchat.ontology.regions import REGIONS
from floatchat.ontology.variables import VARIABLES
from floatchat.understanding import prompt as prompt_module
from floatchat.understanding.prompt import build_system_prompt, build_user_prompt


class TestSystemPromptOntologyGrounding:
    def test_every_intent_name_and_description_is_present(self):
        prompt = build_system_prompt()
        for definition in INTENT_DEFINITIONS.values():
            assert definition.name in prompt
            assert definition.description in prompt

    def test_every_variable_is_present_with_synonym_hints(self):
        prompt = build_system_prompt()
        for canonical, definition in VARIABLES.items():
            assert canonical in prompt
            assert definition.description in prompt
        # Spot-check: synonym vocabulary reaches the prompt (grounding source)
        assert "temperature" in prompt  # TEMP.parser_synonyms
        assert "oxygen" in prompt  # DOXY aliases

    def test_every_region_is_present(self):
        prompt = build_system_prompt()
        for region in REGIONS.values():
            assert region.display_name in prompt

    def test_every_concept_is_present(self):
        prompt = build_system_prompt()
        for concept in CONCEPTS.values():
            assert concept.term in prompt

    def test_prompt_tracks_ontology_edits(self, monkeypatch):
        """Adding an ontology member must change the prompt automatically —
        the definitive 'no duplicated vocabulary' proof."""
        fake = replace(
            REGIONS["arabian_sea"],
            canonical="zwischenahner_meer",
            display_name="Zwischenahner Meer",
            aliases=("meer",),
        )
        patched = dict(REGIONS)
        patched["zwischenahner_meer"] = fake
        monkeypatch.setattr(prompt_module, "REGIONS", patched)
        build_system_prompt.cache_clear()
        try:
            prompt = build_system_prompt()
        finally:
            build_system_prompt.cache_clear()
        assert "Zwischenahner Meer" in prompt

    def test_output_contract_and_rules_are_present(self):
        prompt = build_system_prompt()
        assert "OUTPUT CONTRACT" in prompt
        assert "intent_name" in prompt
        assert "requires_clarification" in prompt
        assert "ONLY the JSON object" in prompt

    def test_prompt_is_deterministic(self):
        assert build_system_prompt() == build_system_prompt()


class TestUserPrompt:
    def test_message_is_included(self):
        prompt = build_user_prompt("show oxygen in arabian sea")
        assert "show oxygen in arabian sea" in prompt
        assert "PRIOR CONVERSATION CONTEXT" not in prompt

    def test_context_block_is_rendered_when_available(self):
        class Ctx:
            last_float_id = "2902403"
            last_variables = ["DOXY"]
            last_region = "arabian_sea"
            last_year = 2024
            last_profile_number = 4
            last_intent = "profile_plot"

        prompt = build_user_prompt("same but for salinity", Ctx())
        assert "PRIOR CONVERSATION CONTEXT" in prompt
        assert "2902403" in prompt
        assert "arabian sea" in prompt  # underscores rendered as spaces
        assert "2024" in prompt

    def test_empty_context_object_produces_no_block(self):
        class Empty:
            pass

        prompt = build_user_prompt("hello", Empty())
        assert "PRIOR CONVERSATION CONTEXT" not in prompt
