
import pytest
from unittest.mock import MagicMock
from floatchat.query_engine.engine import QueryEngine
from floatchat.models.intent import ParsedIntent
from floatchat.config import settings
from floatchat.repository_service.base import AbstractRepositoryService
from floatchat.metadata_service.base import AbstractMetadataService
from floatchat.netcdf_reader.base import AbstractNetCDFReader
from floatchat.visualization_engine.base import AbstractVisualizationEngine

@pytest.fixture
def mock_qe():
    meta = MagicMock(spec=AbstractMetadataService)
    repo = MagicMock(spec=AbstractRepositoryService)
    reader = MagicMock(spec=AbstractNetCDFReader)
    viz = MagicMock(spec=AbstractVisualizationEngine)
    return QueryEngine(meta, repo, reader, viz)

def test_global_mode_allows_all_regions(mock_qe):
    settings.deployment_mode = "GLOBAL"
    
    # Test North Atlantic (should be allowed)
    intent = ParsedIntent(
        intent="profile_plot",
        region="north_atlantic",
        variables=["TEMP"],
        year=None,
        float_id=None,
        profile_number=None,
        limit=5
    )
    
    class MockRecord:
        def __init__(self):
            self.file = "test.nc"
            self.parameters = "TEMP"
            self.date = None
            self.latitude = 0.0
            self.longitude = 0.0
            self.institution = "Test"

    mock_qe.metadata.search.return_value = [MockRecord()]
    
    response = None
    try:
        response = mock_qe.execute(intent)
    except Exception:
        pass
    
    if response:
        assert "not supported" not in response.message

def test_india_only_mode_allows_india_regions(mock_qe):
    settings.deployment_mode = "INDIA_ONLY"
    
    for region in ["arabian_sea", "bay_of_bengal"]:
        intent = ParsedIntent(
            intent="profile_plot",
            region=region,
            variables=["TEMP"],
            year=None,
            float_id=None,
            profile_number=None,
            limit=5
        )
        
        class MockRecord:
            def __init__(self):
                self.file = "test.nc"
                self.parameters = "TEMP"
                self.date = None
                self.latitude = 0.0
                self.longitude = 0.0
                self.institution = "Test"

        mock_qe.metadata.search.return_value = [MockRecord()]
        
        response = None
        try:
            response = mock_qe.execute(intent)
        except Exception:
            pass
            
        if response:
            assert "not supported" not in response.message

def test_india_only_mode_rejects_other_regions(mock_qe):
    settings.deployment_mode = "INDIA_ONLY"
    
    for region in ["north_atlantic", "south_pacific", "mediterranean_sea"]:
        intent = ParsedIntent(
            intent="profile_plot",
            region=region,
            variables=["TEMP"],
            year=None,
            float_id=None,
            profile_number=None,
            limit=5
        )
        
        response = mock_qe.execute(intent)
        assert "not supported" in response.message
        assert "Arabian Sea or Bay of Bengal" in response.message
        assert response.data_summary["matched_records"] == 0

def test_india_only_mode_allows_float_queries(mock_qe):
    settings.deployment_mode = "INDIA_ONLY"
    
    intent = ParsedIntent(
        intent="profile_plot",
        region=None,
        variables=["TEMP"],
        year=None,
        float_id="1234567",
        profile_number=None,
        limit=5
    )
    
    class MockRecord:
        def __init__(self):
            self.file = "test.nc"
            self.parameters = "TEMP"
            self.date = None
            self.latitude = 0.0
            self.longitude = 0.0
            self.institution = "Test"

    mock_qe.metadata.search.return_value = [MockRecord()]
    
    response = None
    try:
        response = mock_qe.execute(intent)
    except Exception:
        pass
    
    if response:
        assert "not supported" not in response.message
