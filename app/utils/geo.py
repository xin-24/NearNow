"""Geographic utility functions shared across providers and planners."""

from __future__ import annotations

from math import atan2, cos, radians, sin, sqrt

from app.domain.models import Coordinates


def distance_km(origin: Coordinates, destination: Coordinates) -> float:
    """Haversine distance between two coordinate pairs, in kilometres."""
    earth_radius_km = 6371.0
    lat_1 = radians(origin.lat)
    lat_2 = radians(destination.lat)
    delta_lat = radians(destination.lat - origin.lat)
    delta_lng = radians(destination.lng - origin.lng)
    a = sin(delta_lat / 2) ** 2 + cos(lat_1) * cos(lat_2) * sin(delta_lng / 2) ** 2
    return earth_radius_km * 2 * atan2(sqrt(a), sqrt(1 - a))


def format_location(coordinates: Coordinates) -> str:
    """Format coordinates as ``lng,lat`` string for Amap APIs."""
    return f"{coordinates.lng:.6f},{coordinates.lat:.6f}"


def parse_location(value: object) -> Coordinates | None:
    """Parse a ``lng,lat`` string into a :class:`Coordinates` object."""
    parts = str(value or "").split(",")
    if len(parts) < 2:
        return None
    try:
        return Coordinates(lat=float(parts[1]), lng=float(parts[0]))
    except (TypeError, ValueError):
        return None
