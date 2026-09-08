"""Great-circle distance, for display values PostGIS does not compute for us."""

import math

EARTH_RADIUS_M = 6_371_008.8  # IUGG mean radius


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Metres between two points along a sphere.

    Within 0.3 % of PostGIS's spheroid ``ST_Distance`` — fine for a value the
    card rounds to 0.1 km. Search results keep using ``ST_Distance``; never mix
    the two in one sorted list.
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))
