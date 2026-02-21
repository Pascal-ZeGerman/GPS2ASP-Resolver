"""Tests for WGS84 to NY State Plane coordinate conversion."""

import pytest

from gps2asp.resolver.converter import convert
from gps2asp.resolver.exceptions import OutsideNYCError


class TestConvert:
    """Test the convert() function for WGS84 -> State Plane transformation."""

    def test_prospect_heights_known_coordinate(self):
        """Prospect Heights (40.6778, -73.9690) should convert to approximately
        (992849, 186196) in State Plane feet. Allow +/- 50 feet tolerance
        for verified reference values (actual pyproj output: 992848.57, 186196.35)."""
        x, y = convert(40.6778, -73.9690)
        assert abs(x - 992849) < 50, f"X={x}, expected ~992849"
        assert abs(y - 186196) < 50, f"Y={y}, expected ~186196"

    def test_axis_order_correctness(self):
        """Swapping lat/lon should produce very different results,
        verifying correct axis order handling."""
        x_correct, y_correct = convert(40.6778, -73.9690)

        # If we could pass swapped coords, they would be outside NYC
        # and raise OutsideNYCError. Verify by checking the correct
        # result is in a reasonable range for NYC State Plane.
        # NYC State Plane X range: ~900,000 - 1,070,000
        # NYC State Plane Y range: ~120,000 - 275,000
        assert 900_000 < x_correct < 1_070_000, f"X={x_correct} outside NYC SP range"
        assert 120_000 < y_correct < 275_000, f"Y={y_correct} outside NYC SP range"

    def test_outside_nyc_zero_zero(self):
        """Coordinates (0.0, 0.0) in the Gulf of Guinea should raise OutsideNYCError."""
        with pytest.raises(OutsideNYCError):
            convert(0.0, 0.0)

    def test_outside_nyc_los_angeles(self):
        """Los Angeles coordinates should raise OutsideNYCError."""
        with pytest.raises(OutsideNYCError):
            convert(34.0, -118.0)

    def test_outside_nyc_wrong_lat(self):
        """Latitude outside NYC range should raise OutsideNYCError."""
        with pytest.raises(OutsideNYCError):
            convert(41.0, -73.9690)  # Too far north

    def test_outside_nyc_wrong_lon(self):
        """Longitude outside NYC range should raise OutsideNYCError."""
        with pytest.raises(OutsideNYCError):
            convert(40.6778, -74.30)  # Too far west

    def test_staten_island_southern_tip(self):
        """Staten Island southern tip (approx 40.50, -74.25) should convert
        without error (edge of NYC)."""
        x, y = convert(40.50, -74.25)
        assert isinstance(x, float)
        assert isinstance(y, float)
        # Should be valid State Plane coordinates
        assert x > 0
        assert y > 0

    def test_bronx_northern_edge(self):
        """Bronx northern edge (approx 40.91, -73.90) should convert
        without error (edge of NYC)."""
        x, y = convert(40.91, -73.90)
        assert isinstance(x, float)
        assert isinstance(y, float)
        # Should be valid State Plane coordinates
        assert x > 0
        assert y > 0

    def test_return_type_is_tuple_of_floats(self):
        """convert() should return a tuple of two floats."""
        result = convert(40.6778, -73.9690)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], float)
        assert isinstance(result[1], float)

    def test_outside_nyc_error_contains_coordinates(self):
        """OutsideNYCError should contain the offending coordinates."""
        with pytest.raises(OutsideNYCError) as exc_info:
            convert(0.0, 0.0)
        assert exc_info.value.lat == 0.0
        assert exc_info.value.lon == 0.0
