"""Tests for QueryEngine.

Priority 1A: ALL data intents now route through DuckDBDataLake.
The legacy GDAC pipeline is only used when FLOATCHAT_ALLOW_REMOTE_GDAC_FALLBACK=True.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pandas as pd

from floatchat.models import ChatResponse, MetadataRecord, ParsedIntent
from floatchat.query_engine.engine import QueryEngine


class TestQueryEngine:
    def _make_engine(self, records=None, df=None, figure=None):
        metadata = MagicMock()
        metadata.search = MagicMock(return_value=records or [])

        repository = MagicMock()
        ncd = MagicMock()
        repository.fetch = MagicMock(return_value=ncd)

        reader = MagicMock()
        reader.read = MagicMock(return_value=df if df is not None else pd.DataFrame())

        viz = MagicMock()
        viz.render = MagicMock(return_value=figure or {"data": [], "layout": {}})

        return QueryEngine(metadata, repository, reader, viz)

    def test_execute_no_records(self) -> None:
        """Priority 1A: With no data lake data, returns a zero-result explanation."""
        engine = self._make_engine(records=[])
        # Mock the data lake to return no data
        mock_lake = MagicMock()
        mock_lake.is_available = MagicMock(return_value=False)
        mock_lake.is_phase2_available = MagicMock(return_value=False)
        engine._data_lake = mock_lake

        intent = ParsedIntent(intent="profile_plot", variables=["DOXY"])
        response = engine.execute(intent)

        assert isinstance(response, ChatResponse)
        # Priority 1A: No longer says "No Argo profiles matched" (that was GDAC path)
        # Now says data lake is unavailable or returns zero-result explanation
        assert response.data_summary.get("matched_records") == 0

    def test_execute_success_via_data_lake(self) -> None:
        """Priority 1A: Data queries go through the data lake, not GDAC."""
        engine = self._make_engine(records=[], figure={"data": [1]})
        # Mock the data lake to return data
        from floatchat.data_lake.base import LakeQueryResult

        mock_df = pd.DataFrame({
            "float_id": ["6900001"] * 5,
            "cycle_number": [1] * 5,
            "date": [datetime(2024, 1, 1)] * 5,
            "year": [2024] * 5,
            "month": [1] * 5,
            "lat": [15.0] * 5,
            "lon": [65.0] * 5,
            "data_mode": ["D"] * 5,
            "pressure": [10.0, 50.0, 100.0, 200.0, 500.0],
            "temp": [25.0, 24.0, 20.0, 15.0, 10.0],
            "temp_adjusted": [25.1, 24.1, 20.1, 15.1, 10.1],
            "psal": [35.0] * 5,
            "psal_adjusted": [35.1] * 5,
            "doxy": [200.0] * 5,
            "doxy_adjusted": [201.0] * 5,
            "chla": [0.5] * 5,
            "chla_adjusted": [0.5] * 5,
            "region_tag": ["arabian_sea"] * 5,
            "source_file": ["test.nc"] * 5,
            "dac": ["IN"] * 5,
        })
        mock_result = LakeQueryResult(
            df=mock_df,
            stats={},
            unique_floats=1,
            unique_profiles=1,
            total_measurements=5,
            has_data=True,
            source="test",
        )
        mock_lake = MagicMock()
        mock_lake.query = MagicMock(return_value=mock_result)
        mock_lake.is_available = MagicMock(return_value=True)
        mock_lake.is_phase2_available = MagicMock(return_value=False)
        mock_lake.list_available_years = MagicMock(return_value=[2024])
        mock_lake.get_map_markers = MagicMock(return_value=[])
        mock_lake.probe_availability = MagicMock(return_value={})
        mock_lake._lake_root = MagicMock()
        engine._data_lake = mock_lake

        intent = ParsedIntent(intent="profile_plot", variables=["DOXY"])
        response = engine.execute(intent)

        # GDAC should NOT have been called
        engine.metadata.search.assert_not_called()
        engine.repository.fetch.assert_not_called()
        # Lake was called instead
        assert isinstance(response, ChatResponse)

    def test_execute_builds_summary_once_for_explanation_and_response(self) -> None:
        """Summary is built once even when explanation engine uses it."""
        engine = self._make_engine(records=[])
        # Use a mock lake that returns data
        from floatchat.data_lake.base import LakeQueryResult
        mock_df = pd.DataFrame({
            "float_id": ["6900001"],
            "cycle_number": [1],
            "date": [datetime(2024, 1, 1)],
            "year": [2024],
            "month": [1],
            "lat": [15.0],
            "lon": [65.0],
            "data_mode": ["D"],
            "pressure": [10.0],
            "temp": [25.0],
            "psal": [35.0],
            "region_tag": ["arabian_sea"],
            "source_file": ["test.nc"],
            "dac": ["IN"],
        })
        mock_result = LakeQueryResult(
            df=mock_df, stats={}, unique_floats=1, unique_profiles=1,
            total_measurements=1, has_data=True, source="test",
        )
        mock_lake = MagicMock()
        mock_lake.query = MagicMock(return_value=mock_result)
        mock_lake.is_available = MagicMock(return_value=True)
        mock_lake.is_phase2_available = MagicMock(return_value=False)
        mock_lake.list_available_years = MagicMock(return_value=[2024])
        mock_lake.get_map_markers = MagicMock(return_value=[])
        mock_lake.probe_availability = MagicMock(return_value={})
        mock_lake._lake_root = MagicMock()
        engine._data_lake = mock_lake

        # M4: _build_lake_summary now lives in query_engine.response_builder;
        # the data-query executor resolves it as a module attribute at call
        # time, so wrap + patch there (behavioural contract unchanged).
        from floatchat.query_engine import response_builder

        original_build_summary = response_builder._build_lake_summary
        with patch.object(
            response_builder, "_build_lake_summary", wraps=original_build_summary
        ) as mock_build_summary:
            engine.execute(ParsedIntent(intent="profile_plot", variables=["DOXY"]))

        mock_build_summary.assert_called_once()

    def test_metadata_lookup_falls_back_to_gdac_when_allowed(self) -> None:
        """Priority 1A: GDAC metadata fallback only when FLOATCHAT_ALLOW_REMOTE_GDAC_FALLBACK=True."""
        from floatchat.config import settings

        rec = MetadataRecord(
            file="coriolis/6903091/profiles/BR6903091_001.nc",
            date=datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC),
            latitude=15.5,
            longitude=72.0,
            ocean="I",
            profiler_type="841",
            institution="INCOIS",
            parameters="PRES TEMP PSAL DOXY CHLA",
            parameter_data_mode="R A R R",
            date_update=datetime(2024, 1, 2, 0, 0, 0, tzinfo=UTC),
        )

        metadata = MagicMock()
        metadata.search = MagicMock(return_value=[rec])

        engine = QueryEngine(metadata, MagicMock(), MagicMock(), MagicMock())
        mock_lake = MagicMock()
        mock_lake.query_metadata_lookup = MagicMock(return_value={"found": False, "float_id": "6903091"})
        mock_lake.is_available = MagicMock(return_value=True)
        mock_lake.is_phase2_available = MagicMock(return_value=False)
        engine._data_lake = mock_lake

        # With allow_remote_gdac_fallback=True, GDAC fallback should work
        with patch.object(settings, "allow_remote_gdac_fallback", True), patch.object(
            settings, "enable_gdac_runtime", True
        ):
            intent = ParsedIntent(intent="metadata_lookup", float_id="6903091")
            response = engine.execute(intent)

        assert response.intent == "metadata_lookup"
        assert response.data_summary["float_info"]["found"] is True
        assert "CTD" in response.data_summary["float_info"]["sensors"]
        assert "OPTODE" in response.data_summary["float_info"]["sensors"]
        assert len(response.map_data) == 1
        assert response.map_data[0].latitude == 15.5
        assert response.map_data[0].longitude == 72.0

    def test_metadata_lookup_no_gdac_fallback_by_default(self) -> None:
        """Priority 1A: When FLOATCHAT_ALLOW_REMOTE_GDAC_FALLBACK=False (default),
        metadata_lookup does NOT call GDAC even when float not in lake."""
        from floatchat.config import settings

        metadata = MagicMock()
        metadata.search = MagicMock(return_value=[])

        engine = QueryEngine(metadata, MagicMock(), MagicMock(), MagicMock())
        mock_lake = MagicMock()
        mock_lake.query_metadata_lookup = MagicMock(return_value={"found": False, "float_id": "9999999"})
        mock_lake.is_available = MagicMock(return_value=True)
        mock_lake.is_phase2_available = MagicMock(return_value=False)
        engine._data_lake = mock_lake

        with patch.object(settings, "allow_remote_gdac_fallback", False):
            intent = ParsedIntent(intent="metadata_lookup", float_id="9999999")
            response = engine.execute(intent)

        assert response.intent == "metadata_lookup"
        # GDAC should NOT have been called
        metadata.search.assert_not_called()
        # Clear message about disabled remote access
        assert "disabled" in response.message.lower() or "not found" in response.message.lower()


class TestDataLakeRouting:
    """Priority 1A: ALL data intents route through DuckDBDataLake."""

    def _make_mock_lake(self, has_data: bool = True, df_rows: int = 10) -> MagicMock:
        """Create a mock data lake that returns predictable data."""
        from floatchat.data_lake.base import LakeQueryResult

        mock_result = MagicMock(spec=LakeQueryResult)
        mock_result.has_data = has_data
        mock_result.total_measurements = df_rows if has_data else 0
        mock_result.unique_floats = 2 if has_data else 0
        mock_result.unique_profiles = 1 if has_data else 0
        mock_result.date_min = datetime(2024, 3, 15)
        mock_result.date_max = datetime(2024, 3, 15)
        mock_result.source = "Argo Data Lake (test)"
        mock_result.stats = {}

        mock_df = pd.DataFrame({
            "float_id": ["6900001"],
            "cycle_number": [1],
            "date": [datetime(2024, 3, 15)],
            "year": [2024],
            "month": [3],
            "lat": [15.0],
            "lon": [65.0],
            "data_mode": ["D"],
            "pressure": [10.0],
            "temp": [28.0],
            "temp_adjusted": [28.1],
            "psal": [35.5],
            "psal_adjusted": [35.5],
            "doxy": [200.0],
            "doxy_adjusted": [201.0],
            "chla": [0.5],
            "chla_adjusted": [0.5],
            "region_tag": ["arabian_sea"],
            "source_file": ["coriolis/6900001/profiles/BR6900001_001.nc"],
            "dac": ["coriolis"],
        })
        mock_result.df = mock_df

        mock_lake = MagicMock()
        mock_lake.query = MagicMock(return_value=mock_result)
        mock_lake.is_available = MagicMock(return_value=has_data)
        mock_lake.is_phase2_available = MagicMock(return_value=False)
        mock_lake.list_available_years = MagicMock(return_value=[2024] if has_data else [])
        mock_lake.get_map_markers = MagicMock(return_value=[])
        mock_lake.probe_availability = MagicMock(return_value={})
        mock_lake._lake_root = MagicMock()
        mock_lake.build_zero_result_message = MagicMock(return_value="No data found")
        return mock_lake

    def _make_engine(self) -> QueryEngine:
        """Create a minimal engine for testing."""
        from floatchat.scientific_explanation.engine import ScientificExplanationEngine

        metadata = MagicMock()
        repository = MagicMock()
        reader = MagicMock()
        viz = MagicMock()
        viz.render = MagicMock(return_value={"data": []})
        engine = QueryEngine(
            metadata, repository, reader, viz,
            explanation_engine=ScientificExplanationEngine(),
        )
        return engine

    def test_region_search_uses_data_lake(self) -> None:
        """Priority 1A: region_search goes through data lake, NOT GDAC."""
        from floatchat.config import settings

        engine = self._make_engine()
        mock_lake = self._make_mock_lake()
        engine._data_lake = mock_lake

        with patch.object(settings, "data_lake_enabled", True):
            intent = ParsedIntent(
                intent="region_search",
                region="arabian_sea",
                variables=["TEMP"],
                year=2024,
            )
            response = engine.execute(intent)

        # GDAC should NOT have been called
        engine.metadata.search.assert_not_called()
        engine.repository.fetch.assert_not_called()

        assert isinstance(response, ChatResponse)

    def test_region_search_with_lake_unavailable_no_gdac(self) -> None:
        """Priority 1A: When lake returns no data, NO GDAC fallback (default)."""
        from floatchat.config import settings

        engine = self._make_engine()
        mock_lake = self._make_mock_lake(has_data=False)
        engine._data_lake = mock_lake

        with patch.object(settings, "data_lake_enabled", True):
            with patch.object(settings, "allow_remote_gdac_fallback", False):
                intent = ParsedIntent(
                    intent="region_search",
                    region="arabian_sea",
                    variables=["TEMP"],
                )
                response = engine.execute(intent)

        # GDAC should NOT have been called
        engine.metadata.search.assert_not_called()
        assert response.data_summary.get("matched_records") == 0

    def test_profile_plot_uses_data_lake(self) -> None:
        """Priority 1A: profile_plot NOW goes through data lake (was previously GDAC-only)."""
        from floatchat.config import settings

        engine = self._make_engine()
        mock_lake = self._make_mock_lake()
        engine._data_lake = mock_lake

        with patch.object(settings, "data_lake_enabled", True):
            with patch.object(settings, "allow_remote_gdac_fallback", False):
                intent = ParsedIntent(intent="profile_plot", variables=["DOXY"])
                response = engine.execute(intent)

        # Priority 1A: GDAC should NOT have been called for profile_plot
        engine.metadata.search.assert_not_called()
        engine.repository.fetch.assert_not_called()

        # Data lake should have been used
        assert isinstance(response, ChatResponse)
