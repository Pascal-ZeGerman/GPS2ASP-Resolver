"""WGS84 to NY State Plane (EPSG:2263) coordinate transformation.

Converts GPS coordinates (latitude/longitude in WGS84) to NY State Plane
Long Island coordinates (EPSG:2263) in US survey feet. The State Plane
coordinate system is used by NYC for all official geographic data including
street centerlines and parking sign locations.

Units: Output coordinates are in US survey feet (1 ft = 0.3048006 m).
Axis order: Input is (lat, lon) matching GPS convention. Internally,
pyproj uses (lon, lat) order with always_xy=True.
"""

from pyproj import Transformer

from gps2asp.resolver.exceptions import OutsideNYCError

# NYC bounding box (approximate, with small buffer for edge cases)
# Lat: 40.49 (south Staten Island) to 40.92 (north Bronx)
# Lon: -74.27 (west Staten Island) to -73.68 (east Queens/Nassau border)
NYC_LAT_MIN = 40.49
NYC_LAT_MAX = 40.92
NYC_LON_MIN = -74.27
NYC_LON_MAX = -73.68

# Create transformer once at module level, reuse for all conversions.
# always_xy=True means transform() expects (x=longitude, y=latitude) input order.
_transformer = Transformer.from_crs(
    "EPSG:4326",  # WGS84 (GPS)
    "EPSG:2263",  # NY State Plane Long Island (US survey feet)
    always_xy=True,
)


def convert(lat: float, lon: float) -> tuple[float, float]:
    """Convert WGS84 GPS coordinates to NY State Plane (EPSG:2263).

    Args:
        lat: Latitude in WGS84 (e.g., 40.6778 for Prospect Heights).
        lon: Longitude in WGS84 (e.g., -73.9690 for Prospect Heights).

    Returns:
        Tuple of (x, y) in NY State Plane coordinates (US survey feet).
        Example: (992700, 186200) for Prospect Heights.

    Raises:
        OutsideNYCError: If coordinates are outside the NYC bounding box.
    """
    if not (NYC_LAT_MIN <= lat <= NYC_LAT_MAX):
        raise OutsideNYCError(lat, lon)
    if not (NYC_LON_MIN <= lon <= NYC_LON_MAX):
        raise OutsideNYCError(lat, lon)

    # CRITICAL: pass (lon, lat) because always_xy=True means x=longitude, y=latitude
    x, y = _transformer.transform(lon, lat)
    return x, y
