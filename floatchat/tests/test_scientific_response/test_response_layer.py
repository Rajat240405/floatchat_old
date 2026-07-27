"""Phase 5 — Scientific Response Layer.

Facts-vs-prose discipline under test:
* narration/context/assumption sections describe only grounded facts;
* summaries are computed solely from the returned payload (figure traces,
  map markers, data_summary) or carried over from the engine — thin data ⇒
  the statement is omitted;
* execution output (figure, map_data, original data_summary keys) passes
  through byte-identical, and the layer vanishes entirely when disabled.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from floatchat.models import ChatResponse, MapData, ParsedIntent
from floatchat.scientific_response import ScientificResponseLayer
from floatchat.scientific_response.summary import summarize
from floatchat.scientific_response.suggestions import suggest

LAYER = ScientificResponseLayer()


# --------------------------------------------------------------------- #
# Fixtures — synthetic engine responses (deterministic payloads)
# --------------------------------------------------------------------- #
def _temp_profile_figure() -> dict:
    # 40-point monotonic temperature profile: ~28 °C surface → 4 °C at 1000 dbar
    pres = [float(p) for p in range(0, 1025, 25)]
    temp = [28.0 - (p / 1000.0) * 24.0 for p in pres]
    return {"data": [{"x": temp, "y": pres, "name": "Float 5906969", "type": "scatter"}]}


def profile_response() -> ChatResponse:
    return ChatResponse(
        intent="profile_plot",
        message="Showing TEMP profile for Float 5906969, the latest available profile.\n\nTemperature ranges 4.0–28.0 °C across the profile.",
        figure=_temp_profile_figure(),
        data_summary={
            "matched_records": 3,
            "unique_floats": 1,
            "unique_profiles": 3,
            "total_measurements": 450,
            "date_range": {"min": "2024-01-05", "max": "2024-03-01"},
            "stats": {},
        },
        map_data=[],
    )


def comparison_response() -> ChatResponse:
    pres = [float(p) for p in range(0, 1025, 25)]
    as_tr = {"x": [36.0 - p * 0.001 for p in pres], "y": pres, "name": "Arabian Sea"}
    bb_tr = {"x": [33.0 - p * 0.001 for p in pres], "y": pres, "name": "Bay of Bengal"}
    return ChatResponse(
        intent="comparison_plot",
        message="Showing PSAL profile, the latest available profile.",
        figure={"data": [as_tr, bb_tr]},
        data_summary={"matched_records": 40, "unique_floats": 12, "unique_profiles": 40},
        map_data=[],
    )


def trajectory_response() -> ChatResponse:
    markers = [
        MapData(float_id="5906969", latitude=11.0, longitude=72.0,
                profile_date="2024-01-01", profile_number=1, dac="INCOIS"),
        MapData(float_id="5906969", latitude=10.0, longitude=71.0,
                profile_date="2024-02-01", profile_number=2, dac="INCOIS"),
        MapData(float_id="5906969", latitude=9.0, longitude=70.0,
                profile_date="2024-03-01", profile_number=3, dac="INCOIS"),
    ]
    return ChatResponse(
        intent="trajectory",
        message="Retrieved 3 profile coordinates for Float 5906969 spanning a total trajectory distance of 200.0 km between 2024-01-01 and 2024-03-01.",
        figure=None,
        data_summary={
            "matched_records": 3,
            "trajectory_points": 3,
            "distance_km": 200.0,
            "date_range": {"min": "2024-01-01", "max": "2024-03-01"},
        },
        map_data=markers,
    )


def metadata_response() -> ChatResponse:
    return ChatResponse(
        intent="metadata_lookup",
        message="Float 5906969 metadata: active, INCOIS.",
        figure=None,
        data_summary={
            "matched_records": 140,
            "float_info": {"status": "active", "dac": "INCOIS", "profile_count": 140,
                           "latitude": 10.2, "longitude": 71.5},
        },
        map_data=[],
    )


def intent_of(name: str, **kw) -> ParsedIntent:
    return ParsedIntent(intent=name, **kw)


# --------------------------------------------------------------------- #
# Narration
# --------------------------------------------------------------------- #
class TestNarration:
    def test_profile_float_narration_is_scientific(self):
        out = LAYER.compose(profile_response(), intent=intent_of("profile_plot", variables=["TEMP"], float_id="5906969"))
        assert "temperature profile" in out.message.lower()
        assert "Float 5906969" in out.message
        assert "water column" in out.message
        assert "Showing TEMP" not in out.message.split("\n\n")[0]  # log-style line replaced

    def test_comparison_regions_narration(self):
        out = LAYER.compose(
            comparison_response(),
            intent=intent_of("comparison_plot", variables=["PSAL"],
                             comparison_regions=["arabian_sea", "bay_of_bengal"],
                             region="arabian_sea"),
        )
        first = out.message.split("\n\n")[0]
        assert "Comparing salinity" in first
        assert "Arabian Sea" in first and "Bay of Bengal" in first
        assert "all matching observations" in first

    def test_trajectory_narration_uses_facts(self):
        out = LAYER.compose(trajectory_response(), intent=intent_of("trajectory", float_id="5906969"))
        first = out.message.split("\n\n")[0]
        assert "drift trajectory" in first
        assert "3" in first and "2024-01-01" in first

    def test_metadata_narration(self):
        out = LAYER.compose(metadata_response(), intent=intent_of("metadata_lookup", float_id="5906969"))
        assert out.message.startswith("Metadata summary for **Float 5906969**")


# --------------------------------------------------------------------- #
# Summaries — computed facts only
# --------------------------------------------------------------------- #
class TestSummaries:
    def test_temperature_structure_is_computed_correctly(self):
        bullets = summarize(profile_response(), intent_of("profile_plot", variables=["TEMP"], float_id="5906969"), profile_response().message)
        joined = " ".join(bullets)
        assert "Temperature spans 4.0–28.0" in joined
        # surface band (≤50 dbar) mean of the synthetic linear profile: 27.4 °C
        assert "27.4 °C near the surface" in joined
        assert "4.0 °C at depth" in joined
        # engine interpretation carried forward
        assert "Temperature ranges 4.0–28.0 °C across the profile." in bullets

    def test_comparison_surface_stats_computed(self):
        bullets = summarize(
            comparison_response(),
            intent_of("comparison_plot", variables=["PSAL"], comparison_regions=["arabian_sea", "bay_of_bengal"]),
            comparison_response().message,
        )
        assert any("Arabian Sea ≈ 36.0" in b and "Bay of Bengal ≈ 33.0" in b for b in bullets)
        assert any("Arabian Sea sits higher" in b for b in bullets)

    def test_trajectory_direction_computed_from_markers(self):
        bullets = summarize(trajectory_response(), intent_of("trajectory", float_id="5906969"), trajectory_response().message)
        assert any("southwestward" in b for b in bullets)
        assert any("total path ≈ 200 km" in b for b in bullets)

    def test_thin_data_produces_no_invented_observations(self):
        response = ChatResponse(
            intent="profile_plot",
            message="Showing DOXY profile.",
            figure={"data": [{"x": [1.0, 2.0], "y": [0.0, 10.0], "name": "x"}]},
            data_summary={"matched_records": 1},
            map_data=[],
        )
        bullets = summarize(response, intent_of("profile_plot", variables=["DOXY"]), response.message)
        assert bullets == []  # 2 points — nothing computable, nothing said

    def test_metadata_facts_from_float_info(self):
        bullets = summarize(metadata_response(), intent_of("metadata_lookup", float_id="5906969"), metadata_response().message)
        joined = " ".join(bullets)
        assert "Operational status: active." in joined
        assert "Profiles on record: 140." in joined
        assert "(10.20, 71.50)" in joined


# --------------------------------------------------------------------- #
# Context Used / Assumptions — only when actually applicable
# --------------------------------------------------------------------- #
class TestContextAndAssumptions:
    def test_context_section_only_when_inherited(self):
        intent = intent_of("profile_plot", variables=["PSAL"], float_id="5906969", profile_number=142)
        no_ctx = LAYER.compose(profile_response(), intent=intent)
        assert "Context used" not in no_ctx.message

        with_ctx = LAYER.compose(
            profile_response(),
            intent=intent,
            context_resolutions=[
                "inherited float_id=5906969 (active float)",
                "inherited profile=142 (active profile of float 5906969)",
            ],
        )
        assert "**Context used**" in with_ctx.message
        assert "previously selected float (5906969)" in with_ctx.message
        assert "previously selected profile (142)" in with_ctx.message

    def test_ongoing_comparison_context_phrasing(self):
        out = LAYER.compose(
            comparison_response(),
            intent=intent_of("comparison_plot", variables=["CHLA"], comparison_regions=["arabian_sea", "bay_of_bengal"]),
            context_resolutions=["inherited ongoing comparison (regions arabian_sea,bay_of_bengal)"],
        )
        assert "Continuing the existing comparison between the Arabian Sea and the Bay of Bengal." in out.message

    def test_assumptions_reflect_actual_defaults(self):
        out = LAYER.compose(
            profile_response(),
            intent=intent_of("profile_plot", variables=["TEMP"], float_id="5906969"),
        )
        assert "**Assumptions used**" in out.message
        assert "Latest available profile selected" in out.message
        assert "No depth range specified" in out.message
        assert "No time range specified" in out.message

    def test_no_invented_assumptions_for_fully_explicit_request(self):
        out = LAYER.compose(
            profile_response(),
            intent=intent_of(
                "profile_plot", variables=["TEMP"], float_id="5906969",
                profile_number=142, depth_min=0.0, depth_max=500.0, year=2024,
            ),
        )
        assert "Latest available profile" not in out.message
        assert "No depth range" not in out.message
        assert "No time range" not in out.message

    def test_reasoner_defaults_reported_as_assumptions(self):
        out = LAYER.compose(
            profile_response(),
            intent=intent_of("ts_diagram", variables=["TEMP", "PSAL"], float_id="2902403"),
            reasoning_rule="named_scientific_form",
            reasoning_resolutions=["ts_diagram named with no variables: defaulting to TEMP+PSAL (established form default)"],
        )
        assert "defaulting to TEMP+PSAL" in out.message


# --------------------------------------------------------------------- #
# Follow-up suggestions
# --------------------------------------------------------------------- #
class TestSuggestions:
    def test_profile_suggestions_relevant_and_grounded(self):
        items = suggest(intent_of("profile_plot", variables=["TEMP"], float_id="5906969"))
        assert 3 <= len(items) <= 5
        assert any("5906969" in i for i in items)
        assert any("trajectory" in i.lower() for i in items)

    def test_comparison_suggestions(self):
        items = suggest(intent_of("comparison_plot", variables=["DOXY"], comparison_regions=["arabian_sea", "bay_of_bengal"]))
        assert 3 <= len(items) <= 5
        assert any("Compare" in i for i in items)

    def test_no_duplicates(self):
        items = suggest(intent_of("metadata_lookup", float_id="5906969"))
        assert len(items) == len(set(items))


# --------------------------------------------------------------------- #
# Structure
# --------------------------------------------------------------------- #
class TestStructure:
    def test_section_order_and_optional_omission(self):
        out = LAYER.compose(
            profile_response(),
            intent=intent_of("profile_plot", variables=["TEMP"], float_id="5906969"),
            context_resolutions=["inherited float_id=5906969 (active float)"],
        )
        msg = out.message
        narr_end = msg.index("\n\n")
        order = [
            msg.index("**Scientific summary**"),
            msg.index("**Context used**"),
            msg.index("**Assumptions used**"),
            msg.index("**Suggested follow-ups**"),
        ]
        assert narr_end < order[0] and order == sorted(order)
        assert "**Request interpretation**" not in msg  # flag off by default

    def test_reasoning_section_is_opt_in(self, monkeypatch):
        from floatchat.config import settings

        intent = intent_of("profile_plot", variables=["DOXY"], float_id="5906969")
        monkeypatch.setattr(settings, "scientific_reasoning_explanation_enabled", True)
        out = LAYER.compose(
            profile_response(),
            intent=intent,
            reasoning_rule="discovery_vs_measurement",
            reasoning_resolutions=["variables ['DOXY'] present: reinterpreting 'radius_search' as a measurement objective (profile_plot)"],
        )
        assert "**Request interpretation**" in out.message
        assert "Reasoning rule: discovery vs measurement." in out.message
        assert "DOXY" in out.message


# --------------------------------------------------------------------- #
# Pass-through guarantees
# --------------------------------------------------------------------- #
class TestPassThrough:
    def test_execution_payload_passes_byte_identical(self):
        response = profile_response()
        out = LAYER.compose(response, intent=intent_of("profile_plot", variables=["TEMP"], float_id="5906969"))
        assert out.figure == response.figure          # plot untouched
        assert out.map_data == response.map_data
        for key, value in response.data_summary.items():
            assert out.data_summary[key] == value     # original keys intact
        assert out.data_summary["engine_message"] == response.message
        assert out.intent == response.intent

    def test_zero_result_responses_untouched(self):
        response = ChatResponse(intent="profile_plot", message="No data found.",
                                figure=None, data_summary={"matched_records": 0}, map_data=[])
        out = LAYER.compose(response, intent=intent_of("profile_plot", variables=["TEMP"]))
        assert out.message == "No data found."
        assert "engine_message" not in out.data_summary

    def test_layer_disabled_is_identity(self, monkeypatch):
        from floatchat.config import settings

        monkeypatch.setattr(settings, "scientific_response_enabled", False)
        response = profile_response()
        out = LAYER.compose(response, intent=intent_of("profile_plot", variables=["TEMP"], float_id="5906969"))
        assert out is response


# --------------------------------------------------------------------- #
# Purity
# --------------------------------------------------------------------- #
class TestPurity:
    def test_no_forbidden_imports(self):
        import ast
        import importlib
        import inspect

        for name in ("layer", "narration", "summary", "suggestions"):
            mod = importlib.import_module(f"floatchat.scientific_response.{name}")
            tree = ast.parse(inspect.getsource(mod))
            imported: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(a.name for a in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module)
            for forbidden in (
                "floatchat.llm_service", "floatchat.data_lake",
                "floatchat.query_engine", "floatchat.retrieval_planner", "duckdb",
            ):
                assert not any(
                    m == forbidden or m.startswith(forbidden + ".") for m in imported
                ), (name, forbidden)


# --------------------------------------------------------------------- #
# End-to-end wiring through handle_chat (engine stubbed, real seam)
# --------------------------------------------------------------------- #
class TestChatIntegration:
    def test_composed_response_flows_through_chat(self, monkeypatch):
        from unittest.mock import MagicMock, patch

        from floatchat.api.schemas import ChatRequest
        from floatchat.api.services.chat_service import handle_chat
        from floatchat.llm_service.classifier import QueryClassifier

        engine = MagicMock()
        engine.execute = MagicMock(return_value=profile_response())
        resolver = MagicMock()
        resolver.resolve = MagicMock(
            return_value=intent_of("profile_plot", variables=["TEMP"], float_id="5906969")
        )
        resolver.last_semantic_outcome = None

        with patch.object(QueryClassifier, "classify", return_value="DATA_QUERY"):
            response = handle_chat(
                ChatRequest(message="show temperature of float 5906969", session_id=None),
                MagicMock(),          # classifier instance (patched)
                MagicMock(),          # llm_service
                MagicMock(),          # intent_parser
                resolver,
                engine,
                MagicMock(),          # conversation_manager
                MagicMock(),          # knowledge_base
                response_layer=LAYER,
            )
        assert response.data_summary["engine_message"].startswith("Showing TEMP")
        assert "temperature profile" in response.message.lower()
        assert response.figure == profile_response().figure

    def test_reasoning_trace_reaches_the_layer_via_resolver(self, monkeypatch):
        from unittest.mock import MagicMock, patch

        from floatchat.api.schemas import ChatRequest
        from floatchat.api.services.chat_service import handle_chat
        from floatchat.llm_service.classifier import QueryClassifier

        outcome = SimpleNamespace(
            context_resolutions=["inherited float_id=5906969 (active float)"],
            reasoning_rule="entity_inference",
            reasoning_resolutions=["no intent hint: float + variables → profile measurement"],
        )
        resolver = MagicMock()
        resolver.resolve = MagicMock(
            return_value=intent_of("profile_plot", variables=["TEMP"], float_id="5906969")
        )
        resolver.last_semantic_outcome = outcome
        engine = MagicMock()
        engine.execute = MagicMock(return_value=profile_response())

        with patch.object(QueryClassifier, "classify", return_value="DATA_QUERY"):
            response = handle_chat(
                ChatRequest(message="now plot temperature", session_id="s1"),
                MagicMock(), MagicMock(), MagicMock(), resolver, engine,
                MagicMock(), MagicMock(),
                response_layer=LAYER,
            )
        assert "**Context used**" in response.message
        assert "previously selected float (5906969)" in response.message
