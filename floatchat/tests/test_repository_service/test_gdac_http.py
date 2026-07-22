"""Tests for GDACRepositoryService."""

import httpx
import pytest
import respx
from pathlib import Path
from httpx import Response

from floatchat.exceptions import RepositoryError
from floatchat.repository_service import gdac_http as gdac_service
from floatchat.repository_service.gdac_http import GDACRepositoryService


class TestGDACRepositoryService:
    @pytest.fixture(autouse=True)
    def isolate_cache(self, tmp_path, monkeypatch):
        """Ensure each test uses a fresh temporary cache directory."""
        monkeypatch.setattr(gdac_service, "_NETCDF_CACHE_DIR", tmp_path / "netcdf")

    @respx.mock
    def test_fetch_success(self, sample_netcdf_dataset) -> None:
        # Re-use the bytes from the fixture to mock the HTTP response
        route = respx.get(
            "https://data-argo.ifremer.fr/dac/coriolis/6903091/profiles/BR6903091_001.nc"
        ).mock(return_value=Response(200, content=sample_netcdf_dataset._data))

        svc = GDACRepositoryService()
        ncd = svc.fetch("coriolis/6903091/profiles/BR6903091_001.nc")

        assert ncd.dataset is not None
        assert "PRES" in ncd.dataset.variables
        assert "DOXY" in ncd.dataset.variables
        ncd.close()
        assert route.called

    @respx.mock
    def test_fetch_404_raises(self) -> None:
        route = respx.get(
            "https://data-argo.ifremer.fr/dac/missing/file.nc"
        ).mock(return_value=Response(404))

        svc = GDACRepositoryService()
        with pytest.raises(RepositoryError):
            svc.fetch("missing/file.nc")
        assert route.called

    @respx.mock
    def test_fetch_retries_then_succeeds(self, sample_netcdf_dataset, monkeypatch) -> None:
        """Regression: service retries on transient errors with exponential backoff."""
        monkeypatch.setattr("floatchat.config.settings.http_max_retries", 3)

        call_count = 0

        def _side_effect(request):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return Response(502)
            return Response(200, content=sample_netcdf_dataset._data)

        route = respx.get(
            "https://data-argo.ifremer.fr/dac/coriolis/6903091/profiles/BR6903091_002.nc"
        ).mock(side_effect=_side_effect)

        svc = GDACRepositoryService()
        ncd = svc.fetch("coriolis/6903091/profiles/BR6903091_002.nc")

        assert ncd.dataset is not None
        assert call_count == 3
        ncd.close()

    @respx.mock
    def test_fetch_retries_exhausted_raises(self, monkeypatch) -> None:
        """Regression: after all retries are exhausted, RepositoryError is raised."""
        monkeypatch.setattr("floatchat.config.settings.http_max_retries", 2)

        route = respx.get(
            "https://data-argo.ifremer.fr/dac/missing/file.nc"
        ).mock(return_value=Response(503))

        svc = GDACRepositoryService()
        with pytest.raises(RepositoryError) as exc_info:
            svc.fetch("missing/file.nc")

        assert "503" in str(exc_info.value.message)
        assert route.call_count == 2
