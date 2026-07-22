"""Tests for geographic polygon region filtering."""

from floatchat.metadata_service.polygons import point_in_region


class TestRegionPolygons:
    # Arabian Sea: roughly 0-30°N, 45-80°E
    def test_arabian_sea_inside(self) -> None:
        assert point_in_region(65.0, 15.0, "arabian_sea") is True

    def test_arabian_sea_outside_east(self) -> None:
        # Bay of Bengal longitude
        assert point_in_region(90.0, 15.0, "arabian_sea") is False

    def test_arabian_sea_outside_north(self) -> None:
        assert point_in_region(65.0, 35.0, "arabian_sea") is False

    def test_arabian_sea_outside_west(self) -> None:
        assert point_in_region(40.0, 15.0, "arabian_sea") is False

    # Bay of Bengal: roughly 0-25°N, 78-100°E
    def test_bay_of_bengal_inside(self) -> None:
        assert point_in_region(88.0, 15.0, "bay_of_bengal") is True

    def test_bay_of_bengal_outside_west(self) -> None:
        # Arabian Sea longitude
        assert point_in_region(65.0, 15.0, "bay_of_bengal") is False

    # Mediterranean
    def test_mediterranean_inside(self) -> None:
        # Gulf of Gabes, Tunisia
        assert point_in_region(10.0, 36.0, "mediterranean_sea") is True

    def test_mediterranean_outside(self) -> None:
        # Atlantic off Portugal
        assert point_in_region(-10.0, 40.0, "mediterranean_sea") is False

    # Southern Ocean
    def test_southern_ocean_inside(self) -> None:
        assert point_in_region(0.0, -60.0, "southern_ocean") is True

    def test_southern_ocean_outside_north(self) -> None:
        assert point_in_region(0.0, -40.0, "southern_ocean") is False

    # Unknown region returns True (no filtering)
    def test_unknown_region_returns_true(self) -> None:
        assert point_in_region(0.0, 0.0, "atlantis") is True
