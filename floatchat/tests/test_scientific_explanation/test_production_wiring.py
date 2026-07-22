"""Integration tests for guarded narration and deterministic fallback wiring."""

import json
import logging
from datetime import UTC, datetime
from unittest.mock import MagicMock

import httpx
import pandas as pd
import pytest

from floatchat.api import dependencies
from floatchat.config import Settings, settings
from floatchat.exceptions import ScientificNarratorError
from floatchat.llm_service.base import AbstractLLMService
from floatchat.models import MetadataRecord, ParsedIntent
from floatchat.scientific_explanation.engine import ScientificExplanationEngine
from floatchat.scientific_explanation.features import ScientificFeatureExtractor
from floatchat.scientific_explanation.narrator import ScientificNarrator
from floatchat.scientific_explanation.output_parser import NarratorOutputParser
from floatchat.scientific_explanation.prompt_builder import PromptBuilder
from floatchat.scientific_explanation.schemas import ProfileMeta, build_minimal_facts
from floatchat.scientific_explanation.verification_guard import VerificationGuard

_LLM_EXPLANATION = (
    "The supplied scientific facts show a grounded oxygen pattern with documented quality context."
)


@pytest.fixture
def scientific_inputs():
    intent = ParsedIntent(
        intent="profile_plot",
        variables=["DOXY"],
        region="arabian_sea",
    )
    records = [
        MetadataRecord(
            file="coriolis/7900000/profiles/BR7900000_001.nc",
            date=datetime(2024, 1, 1, tzinfo=UTC),
            latitude=15.0,
            longitude=65.0,
            ocean="I",
            profiler_type="test",
            institution="coriolis",
            parameters="PRES DOXY",
            parameter_data_mode="D D",
            date_update=datetime(2024, 1, 2, tzinfo=UTC),
        )
    ]
    dataframe = pd.DataFrame(
        {
            "PRES": [10.0, 50.0, 100.0],
            "DOXY": [200.0, 100.0, 40.0],
            "source_file": [records[0].file] * 3,
            "profile_date": [records[0].date] * 3,
            "latitude": [records[0].latitude] * 3,
            "longitude": [records[0].longitude] * 3,
            "float_id": ["7900000"] * 3,
            "dac": [records[0].institution] * 3,
        }
    )
    return intent, records, dataframe


def _five_variable_inputs():
    variables = ["TEMP", "DOXY", "PSAL", "CHLA", "BBP700"]
    intent = ParsedIntent(
        intent="profile_plot",
        variables=variables,
        region="arabian_sea",
    )
    records = []
    frames = []
    for index in range(10):
        float_id = f"79{index:05d}"
        file_path = f"coriolis/{float_id}/profiles/BR{float_id}_{index + 1:03d}.nc"
        record = MetadataRecord(
            file=file_path,
            date=datetime(2024, 1, index + 1, tzinfo=UTC),
            latitude=10.0 + index,
            longitude=60.0 + index,
            ocean="I",
            profiler_type="test",
            institution="coriolis",
            parameters=f"PRES {' '.join(variables)}",
            parameter_data_mode="D D D D D",
            date_update=datetime(2024, 2, 1, tzinfo=UTC),
        )
        records.append(record)
        rows = []
        for level, pressure in enumerate([5.0, 25.0, 50.0, 100.0, 200.0]):
            rows.append(
                {
                    "PRES": pressure,
                    "TEMP": 25.0 - level * 3.0,
                    "DOXY": 210.0 - level * 30.0,
                    "PSAL": 35.0 + level * 0.1,
                    "CHLA": 0.1 + level * 0.2,
                    "BBP700": 0.001 + level * 0.001,
                    "source_file": file_path,
                    "float_id": float_id,
                }
            )
        frames.append(pd.DataFrame(rows))

    return intent, records, pd.concat(frames, ignore_index=True)


def _legacy_explanation(intent, records, dataframe, *, use_extractor: bool = False) -> str:
    """Return the deterministic fallback output the engine should produce.

    With ``use_extractor=False`` (default) the engine is wired **without**
    a ``ScientificFeatureExtractor`` and ``narrator_enabled=False`` so the
    legacy bullet-style template is exercised — matching the call paths
    in tests 4 (``test_disabled_setting_always_returns_legacy_template``),
    5 (``test_incomplete_pipeline_returns_legacy_template``), and 6a
    (extractor failure).

    With ``use_extractor=True`` an extractor is wired but the pipeline
    remains incomplete (no narrator), so the engine takes the
    "pipeline not ready" branch and returns the **enriched**
    ``ScientificFacts``-aware fallback. This matches the expected output
    for tests 1, 2, 3 (LLM failures) and 6b (prompt_builder failure) —
    i.e. any case where the LLM pipeline raised but ``ScientificFacts``
    was built successfully before the failure.
    """
    if use_extractor:
        # The wired engine uses build_minimal_facts via a mock extractor,
        # so the helper must use the same facts to produce a matching
        # fallback output.
        facts = build_minimal_facts(intent.variables, region=intent.region)
        extractor = MagicMock(spec=ScientificFeatureExtractor)
        extractor.extract.return_value = facts
        engine = ScientificExplanationEngine(
            feature_extractor=extractor,
            narrator_enabled=True,
        )
    else:
        engine = ScientificExplanationEngine(narrator_enabled=False)
    return engine.generate_explanation(
        intent,
        records,
        intent.variables,
        {},
        df=dataframe,
    )


def _wired_engine(
    raw_response: str | Exception,
    *,
    enabled: bool | None = True,
) -> tuple[ScientificExplanationEngine, MagicMock, MagicMock]:
    facts = build_minimal_facts(["DOXY"], region="arabian_sea")
    extractor = MagicMock(spec=ScientificFeatureExtractor)
    extractor.extract.return_value = facts

    llm = MagicMock(spec=AbstractLLMService)
    if isinstance(raw_response, Exception):
        llm.generate.side_effect = raw_response
    else:
        llm.generate.return_value = raw_response

    engine = ScientificExplanationEngine(
        feature_extractor=extractor,
        prompt_builder=PromptBuilder(max_payload_bytes=4096),
        narrator=ScientificNarrator(llm, max_retries=0),
        output_parser=NarratorOutputParser(),
        verification_guard=VerificationGuard(),
        narrator_enabled=enabled,
    )
    return engine, extractor, llm


class TestScientificExplanationProductionWiring:
    def test_narrator_success_returns_llm_explanation(self, scientific_inputs) -> None:
        intent, records, dataframe = scientific_inputs
        raw = json.dumps(
            {
                "explanation": _LLM_EXPLANATION,
                "key_findings": [],
                "confidence": "high",
            }
        )
        engine, extractor, llm = _wired_engine(raw)

        result = engine.generate_explanation(
            intent,
            records,
            intent.variables,
            {},
            df=dataframe,
        )

        assert result == _LLM_EXPLANATION
        extractor.extract.assert_called_once_with(
            dataframe,
            intent.variables,
            intent,
            records,
        )
        llm.generate.assert_called_once()

    def test_success_path_logs_facts_and_prompt_sizes(
        self,
        scientific_inputs,
        caplog,
    ) -> None:
        intent, records, dataframe = scientific_inputs
        caplog.set_level(logging.INFO)
        raw = json.dumps(
            {
                "explanation": _LLM_EXPLANATION,
                "key_findings": [],
                "confidence": "high",
            }
        )
        llm = MagicMock(spec=AbstractLLMService)
        llm.generate.return_value = raw
        engine = ScientificExplanationEngine(
            feature_extractor=ScientificFeatureExtractor(use_legacy=True),
            prompt_builder=PromptBuilder(max_payload_bytes=4096),
            narrator=ScientificNarrator(llm, max_retries=0),
            output_parser=NarratorOutputParser(),
            verification_guard=VerificationGuard(),
            narrator_enabled=True,
        )

        result = engine.generate_explanation(
            intent,
            records,
            intent.variables,
            {},
            df=dataframe,
        )

        assert result == _LLM_EXPLANATION
        prompt = llm.generate.call_args.args[0]
        assert "<scientific_facts_json>" in prompt
        assert '"variables":["DOXY"]' in prompt
        assert any(
            "ScientificFacts JSON size_bytes=" in record.message
            for record in caplog.records
        )
        assert any(
            "Scientific narration compact facts size_bytes=" in record.message
            for record in caplog.records
        )
        assert any(
            f"Scientific narration final prompt size_bytes={len(prompt.encode('utf-8'))}"
            in record.message
            for record in caplog.records
        )

    def test_parser_failure_returns_existing_template(self, scientific_inputs) -> None:
        intent, records, dataframe = scientific_inputs
        # ScientificFacts were built successfully before the LLM step
        # failed, so the fallback consumes the enriched facts.
        expected = _legacy_explanation(intent, records, dataframe, use_extractor=True)
        engine, _, _ = _wired_engine("not valid JSON")

        result = engine.generate_explanation(
            intent,
            records,
            intent.variables,
            {},
            df=dataframe,
        )

        assert result == expected

    def test_verification_failure_returns_existing_template(self, scientific_inputs) -> None:
        intent, records, dataframe = scientific_inputs
        # ScientificFacts were built successfully before the LLM step
        # failed, so the fallback consumes the enriched facts.
        expected = _legacy_explanation(intent, records, dataframe, use_extractor=True)
        raw = json.dumps(
            {
                "explanation": (
                    "The narration invents an unsupported oxygen measurement of 999 units."
                ),
                "key_findings": [],
                "confidence": "high",
            }
        )
        engine, _, _ = _wired_engine(raw)

        result = engine.generate_explanation(
            intent,
            records,
            intent.variables,
            {},
            df=dataframe,
        )

        assert result == expected

    @pytest.mark.parametrize(
        "provider_error",
        [
            httpx.ReadTimeout(
                "narrator timed out",
                request=httpx.Request("POST", "http://narrator.test/api/generate"),
            ),
            ScientificNarratorError("provider failed"),
        ],
    )
    def test_narrator_timeout_or_error_returns_existing_template(
        self,
        scientific_inputs,
        provider_error: Exception,
    ) -> None:
        intent, records, dataframe = scientific_inputs
        # ScientificFacts were built successfully before the narrator
        # raised, so the fallback consumes the enriched facts.
        expected = _legacy_explanation(intent, records, dataframe, use_extractor=True)
        engine, _, llm = _wired_engine(provider_error)

        result = engine.generate_explanation(
            intent,
            records,
            intent.variables,
            {},
            df=dataframe,
        )

        assert result == expected
        llm.generate.assert_called_once()

    def test_production_timeout_budget_does_not_restart_timed_out_generation(self) -> None:
        assert Settings.model_fields["sci_narrator_timeout"].default == 60.0
        assert Settings.model_fields["sci_narrator_max_retries"].default == 0
        assert Settings.model_fields["sci_narrator_max_tokens"].default == 500

    def test_compacted_five_variable_facts_preserve_scientific_content(self) -> None:
        intent, records, dataframe = _five_variable_inputs()
        facts = ScientificFeatureExtractor(use_legacy=True).extract(
            dataframe,
            intent.variables,
            intent,
            records,
        )

        assert facts.provenance.profile_count == 10
        assert len(facts.profiles) == 3
        assert all(profile.source_file is None for profile in facts.profiles)
        assert facts.provenance.gdac_files == [record.file for record in records[:3]]
        assert {stat.variable for stat in facts.stats} == set(intent.variables)
        assert {feature.feature for feature in facts.features} == {
            "thermocline",
            "oxygen_minimum",
            "halocline",
            "dcm",
        }
        assert facts.qc.delayed_mode_pct == 100.0

        allowed_numbers = set(facts.numeric_allowlist()["all"])
        for stat in facts.stats:
            for value in (
                stat.min_val,
                stat.max_val,
                stat.mean_val,
                stat.median_val,
                stat.surface_mean_0_10m,
                stat.deep_mean_below_200m,
                stat.deepest_pres_dbar,
                stat.deepest_val,
            ):
                if value is not None:
                    assert value in allowed_numbers

        full_payload = facts.to_llm_payload(max_bytes=4096)
        prompt = PromptBuilder(max_payload_bytes=4096).build(facts)
        compact_payload = json.loads(
            prompt.split("<scientific_facts_json>\n", 1)[1].split(
                "\n</scientific_facts_json>", 1
            )[0]
        )
        full_payload_bytes = len(full_payload.encode("utf-8"))
        compact_payload_bytes = len(
            json.dumps(compact_payload, separators=(",", ":")).encode("utf-8")
        )
        assert full_payload_bytes <= 4096
        assert compact_payload_bytes < full_payload_bytes * 0.6
        assert len(prompt.encode("utf-8")) < 5000
        assert compact_payload["variables"] == intent.variables
        assert compact_payload["relationships"] == facts.cross_variable_notes
        assert compact_payload["quality"]["delayed_mode_pct"] == facts.qc.delayed_mode_pct
        compact_stats = {item["variable"]: item for item in compact_payload["statistics"]}
        assert set(compact_stats) == set(intent.variables)
        for stat in facts.stats:
            projected = compact_stats[stat.variable]
            assert projected["minimum"] == stat.min_val
            assert projected["maximum"] == stat.max_val
            assert projected["surface_mean"] == stat.surface_mean_0_10m
            assert projected["deep_mean"] == stat.deep_mean_below_200m
            assert projected["deepest_pressure_dbar"] == stat.deepest_pres_dbar
            assert projected["deepest_value"] == stat.deepest_val
        compact_features = {item["feature"]: item for item in compact_payload["features"]}
        assert set(compact_features) == {
            "thermocline",
            "oxygen_minimum",
            "halocline",
            "dcm",
        }
        for feature in facts.features:
            projected = compact_features[feature.feature]
            assert projected.get("depth_dbar") == feature.depth_dbar
            assert projected.get("strength") == feature.strength
            assert projected.get("value") == feature.value_at_feature
            assert projected.get("prominence") == feature.prominence
        assert "profiles" not in compact_payload
        assert "provenance" not in compact_payload
        assert "mean_val" not in compact_payload["statistics"][0]
        assert "median_val" not in compact_payload["statistics"][0]
        assert "n_obs" not in compact_payload["statistics"][0]

    def test_standard_five_variable_query_reaches_narrator_after_compaction(self) -> None:
        intent, records, dataframe = _five_variable_inputs()
        raw = json.dumps(
            {
                "explanation": (
                    "The supplied facts preserve all requested scientific variables and features."
                ),
                "key_findings": [],
                "confidence": "high",
            }
        )
        llm = MagicMock(spec=AbstractLLMService)
        llm.generate.return_value = raw
        engine = ScientificExplanationEngine(
            feature_extractor=ScientificFeatureExtractor(use_legacy=True),
            prompt_builder=PromptBuilder(max_payload_bytes=4096),
            narrator=ScientificNarrator(llm, max_retries=0),
            output_parser=NarratorOutputParser(),
            verification_guard=VerificationGuard(),
            narrator_enabled=True,
        )

        result = engine.generate_explanation(
            intent,
            records,
            intent.variables,
            {},
            df=dataframe,
        )

        assert result == (
            "The supplied facts preserve all requested scientific variables and features."
        )
        llm.generate.assert_called_once()

    def test_uncompacted_standard_fixture_would_exceed_existing_limit(self) -> None:
        intent, records, dataframe = _five_variable_inputs()
        facts = ScientificFeatureExtractor(use_legacy=True).extract(
            dataframe,
            intent.variables,
            intent,
            records,
        )
        full_profiles = [
            ProfileMeta(
                float_id=record.file.split("/")[1],
                profile_date=record.date.isoformat(),
                latitude=record.latitude,
                longitude=record.longitude,
                dac=record.institution,
                data_mode="D",
                source_file=record.file,
            )
            for record in records
        ]
        full_provenance = facts.provenance.model_copy(
            update={"gdac_files": [record.file for record in records]}
        )
        uncompacted = facts.model_copy(
            update={"profiles": full_profiles, "provenance": full_provenance}
        )

        assert len(uncompacted.to_llm_payload().encode("utf-8")) > 4096
        assert len(facts.to_llm_payload(max_bytes=4096).encode("utf-8")) <= 4096

    def test_disabled_setting_always_returns_legacy_template(
        self,
        scientific_inputs,
        monkeypatch,
    ) -> None:
        intent, records, dataframe = scientific_inputs
        expected = _legacy_explanation(intent, records, dataframe)
        valid_raw = json.dumps(
            {
                "explanation": _LLM_EXPLANATION,
                "key_findings": [],
                "confidence": "high",
            }
        )
        monkeypatch.setattr(settings, "sci_narrator_enabled", False)
        engine, extractor, llm = _wired_engine(valid_raw, enabled=None)

        result = engine.generate_explanation(
            intent,
            records,
            intent.variables,
            {},
            df=dataframe,
        )

        assert result == expected
        extractor.extract.assert_not_called()
        llm.generate.assert_not_called()

    def test_incomplete_pipeline_returns_legacy_template(self, scientific_inputs) -> None:
        intent, records, dataframe = scientific_inputs
        expected = _legacy_explanation(intent, records, dataframe)
        engine = ScientificExplanationEngine(narrator_enabled=True)

        result = engine.generate_explanation(
            intent,
            records,
            intent.variables,
            {},
            df=dataframe,
        )

        assert result == expected

    @pytest.mark.parametrize("failing_component", ["extractor", "prompt_builder"])
    def test_pre_narrator_failure_returns_existing_template(
        self,
        scientific_inputs,
        failing_component: str,
    ) -> None:
        intent, records, dataframe = scientific_inputs
        # The fallback must consume ``ScientificFacts`` whenever it
        # could be built. For ``extractor`` failure the facts are never
        # produced, so the legacy path is used. For ``prompt_builder``
        # failure the facts ARE produced, so the enriched prose is the
        # correct fallback.
        use_extractor = failing_component != "extractor"
        expected = _legacy_explanation(
            intent, records, dataframe, use_extractor=use_extractor
        )
        valid_raw = json.dumps(
            {
                "explanation": _LLM_EXPLANATION,
                "key_findings": [],
                "confidence": "high",
            }
        )
        engine, extractor, _ = _wired_engine(valid_raw)
        if failing_component == "extractor":
            extractor.extract.side_effect = ValueError("facts failed")
        else:
            engine.prompt_builder = MagicMock(spec=PromptBuilder)
            engine.prompt_builder.build.side_effect = ValueError("prompt failed")

        result = engine.generate_explanation(
            intent,
            records,
            intent.variables,
            {},
            df=dataframe,
        )

        assert result == expected

    def test_injected_dependencies_are_used_without_replacement(self) -> None:
        extractor = MagicMock(spec=ScientificFeatureExtractor)
        prompt_builder = MagicMock(spec=PromptBuilder)
        narrator = MagicMock(spec=ScientificNarrator)
        output_parser = MagicMock(spec=NarratorOutputParser)
        guard = MagicMock(spec=VerificationGuard)

        engine = ScientificExplanationEngine(
            feature_extractor=extractor,
            prompt_builder=prompt_builder,
            narrator=narrator,
            output_parser=output_parser,
            verification_guard=guard,
        )

        assert engine.feature_extractor is extractor
        assert engine.prompt_builder is prompt_builder
        assert engine.narrator is narrator
        assert engine.output_parser is output_parser
        assert engine.verification_guard is guard

    def test_guard_receives_parser_output_and_same_facts(self, scientific_inputs) -> None:
        intent, records, dataframe = scientific_inputs
        facts = build_minimal_facts(["DOXY"])
        parsed = MagicMock()
        parsed.explanation = _LLM_EXPLANATION

        extractor = MagicMock(spec=ScientificFeatureExtractor)
        extractor.extract.return_value = facts
        prompt_builder = MagicMock(spec=PromptBuilder)
        prompt_builder.build.return_value = "prompt"
        narrator = MagicMock(spec=ScientificNarrator)
        narrator.generate.return_value = "raw"
        output_parser = MagicMock(spec=NarratorOutputParser)
        output_parser.parse.return_value = parsed
        guard = MagicMock(spec=VerificationGuard)
        guard.verify.return_value = parsed
        engine = ScientificExplanationEngine(
            feature_extractor=extractor,
            prompt_builder=prompt_builder,
            narrator=narrator,
            output_parser=output_parser,
            verification_guard=guard,
            narrator_enabled=True,
        )

        result = engine.generate_explanation(
            intent,
            records,
            intent.variables,
            {},
            df=dataframe,
        )

        assert result == _LLM_EXPLANATION
        output_parser.parse.assert_called_once_with("raw")
        guard.verify.assert_called_once_with(parsed, facts)

    def test_composition_root_injects_pipeline_components(self, monkeypatch) -> None:
        monkeypatch.setattr(dependencies, "_scientific_explanation_engine", None)
        extractor = MagicMock(spec=ScientificFeatureExtractor)
        prompt_builder = MagicMock(spec=PromptBuilder)
        narrator = MagicMock(spec=ScientificNarrator)
        output_parser = MagicMock(spec=NarratorOutputParser)
        guard = MagicMock(spec=VerificationGuard)

        engine = dependencies.get_scientific_explanation_engine(
            extractor,
            prompt_builder,
            narrator,
            output_parser,
            guard,
        )

        assert engine.feature_extractor is extractor
        assert engine.prompt_builder is prompt_builder
        assert engine.narrator is narrator
        assert engine.output_parser is output_parser
        assert engine.verification_guard is guard

    def test_query_engine_receives_explanation_engine_from_composition_root(
        self,
        monkeypatch,
    ) -> None:
        monkeypatch.setattr(dependencies, "_query_engine", None)
        metadata = MagicMock()
        repository = MagicMock()
        reader = MagicMock()
        visualization = MagicMock()
        explanation_engine = ScientificExplanationEngine(narrator_enabled=False)

        query_engine = dependencies.get_query_engine(
            metadata,
            repository,
            reader,
            visualization,
            explanation_engine,
        )

        assert query_engine.explanation_engine is explanation_engine

    def test_composition_root_configures_dedicated_qwen3_provider(
        self,
        monkeypatch,
    ) -> None:
        monkeypatch.setattr(dependencies, "_scientific_llm_service", None)
        monkeypatch.setattr(settings, "ollama_base_url", "http://narrator.test")
        monkeypatch.setattr(settings, "sci_narrator_model", "qwen3:test")
        monkeypatch.setattr(settings, "sci_narrator_timeout", 4.5)
        monkeypatch.setattr(settings, "sci_narrator_temperature", 0.15)
        monkeypatch.setattr(settings, "sci_narrator_top_p", 0.75)
        monkeypatch.setattr(settings, "sci_narrator_max_tokens", 300)
        monkeypatch.setattr(settings, "sci_narrator_thinking", False)

        service = dependencies.get_scientific_llm_service()

        assert service.model == "qwen3:test"
        assert service.timeout == 4.5
        assert service.temperature == 0.15
        assert service.top_p == 0.75
        assert service.max_tokens == 300
        assert service.json_mode is True


class TestScientificNarrationSupportedVariableCoverage:
    """Exercise the complete facts → prompt → narrator → parser → guard path.

    The deterministic fixture is intentionally shared across query shapes. This
    checks that selecting a subset never drops core variables from
    ``ScientificFacts`` while the same real feature extractor is used by the
    production engine.
    """

    @pytest.mark.parametrize(
        ("query", "variables", "expected_features"),
        [
            ("temperature", ["TEMP"], {"thermocline"}),
            ("salinity", ["PSAL"], {"halocline"}),
            ("oxygen", ["DOXY"], {"oxygen_minimum"}),
            ("chlorophyll", ["CHLA"], {"dcm"}),
            ("temperature salinity", ["TEMP", "PSAL"], {"thermocline", "halocline"}),
            (
                "temperature oxygen salinity chlorophyll backscatter",
                ["TEMP", "DOXY", "PSAL", "CHLA", "BBP700"],
                {"thermocline", "halocline", "oxygen_minimum", "dcm"},
            ),
        ],
    )
    def test_supported_query_reaches_verified_narration_without_fallback(
        self,
        query: str,
        variables: list[str],
        expected_features: set[str],
    ) -> None:
        _, records, dataframe = _five_variable_inputs()
        intent = ParsedIntent(
            intent="profile_plot",
            variables=variables,
            region="arabian_sea",
        )
        extractor = ScientificFeatureExtractor(use_legacy=True)
        captured_facts = []
        extract = extractor.extract

        def capture(*args, **kwargs):
            facts = extract(*args, **kwargs)
            captured_facts.append(facts)
            return facts

        extractor.extract = capture  # type: ignore[method-assign]
        explanation = (
            "The observed vertical structure provides a coherent, grounded scientific "
            "description of the sampled water column and its detected features."
        )
        llm = MagicMock(spec=AbstractLLMService)
        llm.generate.return_value = json.dumps(
            {"explanation": explanation, "key_findings": [], "confidence": "high"}
        )
        guard = MagicMock(spec=VerificationGuard, wraps=VerificationGuard())
        engine = ScientificExplanationEngine(
            feature_extractor=extractor,
            prompt_builder=PromptBuilder(max_payload_bytes=4096),
            narrator=ScientificNarrator(llm, max_retries=0),
            output_parser=NarratorOutputParser(),
            verification_guard=guard,
            narrator_enabled=True,
        )

        result = engine.generate_explanation(intent, records, variables, {}, df=dataframe)

        assert query  # Retains the user-facing query label in parametrized output.
        assert result == explanation  # A fallback would produce a different template.
        assert llm.generate.called
        assert guard.verify.called
        assert len(captured_facts) == 1
        facts = captured_facts[0]
        assert {stat.variable.replace("_ADJUSTED", "") for stat in facts.stats} == set(variables)
        assert {feature.feature for feature in facts.features} == expected_features
        assert all(stat.n_obs > 0 for stat in facts.stats)


class TestDeterministicFallbackNarrative:
    """Timeout fallback remains scientific prose without an LLM."""

    def test_facts_aware_fallback_uses_natural_evidence_bounded_paragraphs(self) -> None:
        intent, records, dataframe = _five_variable_inputs()
        facts = ScientificFeatureExtractor(use_legacy=True).extract(
            dataframe, intent.variables, intent, records
        )
        prose = ScientificExplanationEngine()._format_prose_from_facts(facts, records)

        assert "\n\n" in prose
        assert "•" not in prose
        assert "classified as" not in prose
        assert "Quality control:" not in prose
        assert facts.cross_variable_notes[0] in prose
        assert "dominant mechanisms" in prose
        assert "moderate thermocline near" in prose.lower()
