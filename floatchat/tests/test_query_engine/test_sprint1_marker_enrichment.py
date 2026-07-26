"""Bug Fix Sprint 1 (Bug 5) — spatial/metadata map marker enrichment.

Nearest-float, radius-search and metadata-lookup markers previously carried
no ``region_tag`` / ``network`` / ``wmo_id`` — unlike trajectory and data-query
markers. The frontend sidebar region filter drops markers with an empty
region tag, so spatial results disappeared from the map under active filters.
"""

from unittest.mock import MagicMock

import pandas as pd

from floatchat.models import ParsedIntent
from floatchat.query_engine.engine import QueryEngine
from floatchat.query_engine.helpers import _derive_marker_network, _marker_region_tag


def _make_engine(lake: MagicMock) -> QueryEngine:
    engine = QueryEngine(MagicMock(), MagicMock(), MagicMock(), MagicMock())
    engine._data_lake = lake
    return engine


class TestMarkerHelpers:
    def test_network_from_bgc_sensors(self) -> None:
        assert _derive_marker_network(["CTD_PRES", "CTD_TEMP", "OPTODE_DOXY"]) == "BGC Argo"

    def test_network_from_core_sensors(self) -> None:
        assert _derive_marker_network(["CTD_PRES", "CTD_TEMP", "CTD_PSAL"]) == "Core Argo"

    def test_network_defaults_core_without_evidence(self) -> None:
        assert _derive_marker_network([]) == "Core Argo"
        assert _derive_marker_network(None) == "Core Argo"

    def test_region_tag_known_regions(self) -> None:
        assert _marker_region_tag(13.2, 82.3) == "bay_of_bengal"
        assert _marker_region_tag(15.0, 65.0) == "arabian_sea"

    def test_region_tag_outside_regions_is_none(self) -> None:
        assert _marker_region_tag(0.0, 0.0) is None
        assert _marker_region_tag(None, None) is None


class TestNearestFloatMarkerEnrichment:
    def test_nearest_markers_carry_region_network_wmo(self) -> None:
        lake = MagicMock()
        lake.is_available = MagicMock(return_value=True)
        lake.is_phase2_available = MagicMock(return_value=False)
        lake.query_nearest_float = MagicMock(return_value=pd.DataFrame([
            {
                "float_id": "5907082",
                "lat": 13.2,
                "lon": 82.3,
                "distance_km": 220.2,
                "status": "active",
                "sensors": "CTD_PRES,CTD_TEMP,OPTODE_DOXY",
                "institution": "INCOIS",
                "last_report_date": "2024-03-15",
                "profiler_type": "",
            },
            {
                "float_id": "2902403",
                "lat": 15.0,
                "lon": 65.0,
                "distance_km": 500.0,
                "status": "active",
                "sensors": "CTD_PRES,CTD_TEMP,CTD_PSAL",
                "institution": "INCOIS",
                "last_report_date": "2024-03-14",
                "profiler_type": "",
            },
        ]))
        engine = _make_engine(lake)
        intent = ParsedIntent(intent="nearest_float", lat=13.08, lon=80.27, limit=5)
        response = engine.execute(intent)

        assert len(response.map_data) == 2
        bgc = next(m for m in response.map_data if m.float_id == "5907082")
        core = next(m for m in response.map_data if m.float_id == "2902403")
        assert bgc.network == "BGC Argo"
        assert bgc.region_tag == "bay_of_bengal"
        assert bgc.wmo_id == "5907082"
        assert core.network == "Core Argo"
        assert core.region_tag == "arabian_sea"
        assert core.wmo_id == "2902403"


class TestRadiusSearchMarkerEnrichment:
    def test_radius_markers_carry_region_network_wmo(self) -> None:
        lake = MagicMock()
        lake.is_available = MagicMock(return_value=True)
        lake.is_phase2_available = MagicMock(return_value=False)
        lake.query_radius_search = MagicMock(return_value=pd.DataFrame([
            {
                "float_id": "5907082",
                "lat": 13.2,
                "lon": 82.3,
                "status": "active",
                "sensors": "CTD_PRES,FLUOROMETER_CHLA",
                "institution": "INCOIS",
                "last_report_date": "2024-03-15",
                "profiler_type": "",
            },
        ]))
        engine = _make_engine(lake)
        intent = ParsedIntent(intent="radius_search", lat=13.0, lon=82.0, radius_km=300.0)
        response = engine.execute(intent)

        assert len(response.map_data) == 1
        marker = response.map_data[0]
        assert marker.network == "BGC Argo"
        assert marker.region_tag == "bay_of_bengal"
        assert marker.wmo_id == "5907082"


class TestMetadataLookupMarkerEnrichment:
    def test_metadata_marker_carries_region_network_wmo(self) -> None:
        lake = MagicMock()
        lake.is_available = MagicMock(return_value=True)
        lake.is_phase2_available = MagicMock(return_value=False)
        lake.query_metadata_lookup = MagicMock(return_value={
            "found": True,
            "float_id": "2903467",
            "status": "active",
            "sensors": ["CTD_PRES", "CTD_TEMP", "OPTODE_DOXY"],
            "institution": "incois",
            "platform_type": "APEX",
            "profiler_type": "845",
            "first_profile_date": "2023-01-01",
            "last_report_date": "2024-03-15",
            "profile_count": 42,
            "last_lat": 13.2,
            "last_lon": 82.3,
        })
        engine = _make_engine(lake)
        intent = ParsedIntent(intent="metadata_lookup", float_id="2903467")
        response = engine.execute(intent)

        assert len(response.map_data) == 1
        marker = response.map_data[0]
        assert marker.selected is True
        assert marker.network == "BGC Argo"
        assert marker.region_tag == "bay_of_bengal"
        assert marker.wmo_id == "2903467"
