"""Great-circle geometry helpers for route polylines.

Coordinates are ``(lon, lat)`` pairs in degrees, matching GeoJSON order, which
is what the routing provider returns.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from typing import Iterable, Sequence

EARTH_RADIUS_MI = 3958.7613
METERS_PER_MILE = 1609.344

LonLat = tuple[float, float]


def haversine_miles(a: LonLat, b: LonLat) -> float:
    """Great-circle distance between two ``(lon, lat)`` points, in miles."""
    lon1, lat1 = a
    lon2, lat2 = b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_MI * math.asin(math.sqrt(min(1.0, h)))


def cumulative(values: Iterable[float]) -> list[float]:
    """Running total prefixed with 0, so ``len(result) == len(values) + 1``."""
    out = [0.0]
    total = 0.0
    for v in values:
        total += v
        out.append(total)
    return out


def polyline_segment_miles(coords: Sequence[LonLat]) -> list[float]:
    """Per-segment lengths of a polyline, in miles."""
    return [haversine_miles(coords[i], coords[i + 1]) for i in range(len(coords) - 1)]


def interpolate_point(a: LonLat, b: LonLat, fraction: float) -> LonLat:
    """Linear interpolation between two nearby points.

    Segments between adjacent polyline nodes are short (tens of metres), so
    linear interpolation in degrees is well within the precision we need for
    weather sampling.
    """
    f = min(1.0, max(0.0, fraction))
    return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)


def locate_at_distance(
    coords: Sequence[LonLat],
    cum_miles: Sequence[float],
    target_miles: float,
) -> tuple[LonLat, int, float]:
    """Find the point ``target_miles`` along a polyline.

    ``cum_miles`` is the cumulative distance array for ``coords``. Returns the
    interpolated point, the index of the segment it falls in, and the fraction
    through that segment.
    """
    if not coords:
        raise ValueError("coords must not be empty")
    total = cum_miles[-1]
    target = min(max(0.0, target_miles), total)

    # bisect_right - 1 gives the segment whose start is at or before target.
    i = max(0, min(bisect_right(cum_miles, target) - 1, len(coords) - 2))
    seg_len = cum_miles[i + 1] - cum_miles[i]
    frac = 0.0 if seg_len <= 0 else (target - cum_miles[i]) / seg_len
    return interpolate_point(coords[i], coords[i + 1], frac), i, frac


def interpolate_series(
    cum_x: Sequence[float],
    cum_y: Sequence[float],
    target_x: float,
) -> float:
    """Piecewise-linear lookup of ``cum_y`` at ``target_x`` over ``cum_x``.

    Used to turn "miles travelled" into "seconds elapsed" using the routing
    engine's real per-segment durations, so an ETA reflects the actual speed
    profile (slow city segments, fast interstate) instead of a flat average.

    Where ``cum_x`` repeats a value (time passing without distance, e.g. a
    junction node) the later ``cum_y`` is returned, which keeps ETAs
    conservative rather than under-estimating arrival.
    """
    if not cum_x:
        raise ValueError("cum_x must not be empty")
    total = cum_x[-1]
    target = min(max(0.0, target_x), total)
    i = max(0, min(bisect_right(cum_x, target) - 1, len(cum_x) - 2))
    span = cum_x[i + 1] - cum_x[i]
    if span <= 0:
        return cum_y[i]
    frac = (target - cum_x[i]) / span
    return cum_y[i] + (cum_y[i + 1] - cum_y[i]) * frac


def bearing_degrees(a: LonLat, b: LonLat) -> float:
    """Initial great-circle bearing from ``a`` to ``b``, in degrees."""
    lon1, lat1 = math.radians(a[0]), math.radians(a[1])
    lon2, lat2 = math.radians(b[0]), math.radians(b[1])
    dl = lon2 - lon1
    y = math.sin(dl) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def offset_point(origin: LonLat, bearing_deg: float, distance_mi: float) -> LonLat:
    """Point ``distance_mi`` from ``origin`` along ``bearing_deg``."""
    d = distance_mi / EARTH_RADIUS_MI
    th = math.radians(bearing_deg)
    lon1, lat1 = math.radians(origin[0]), math.radians(origin[1])
    lat2 = math.asin(math.sin(lat1) * math.cos(d) + math.cos(lat1) * math.sin(d) * math.cos(th))
    lon2 = lon1 + math.atan2(
        math.sin(th) * math.sin(d) * math.cos(lat1),
        math.cos(d) - math.sin(lat1) * math.sin(lat2),
    )
    return ((math.degrees(lon2) + 540.0) % 360.0 - 180.0, math.degrees(lat2))


def bbox(coords: Sequence[LonLat]) -> tuple[float, float, float, float]:
    """Bounding box as ``(min_lon, min_lat, max_lon, max_lat)``."""
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    return (min(lons), min(lats), max(lons), max(lats))


def geometry_fingerprint(coords: Sequence[LonLat], precision: int = 1) -> frozenset:
    """Coarse grid cells a polyline passes through, for similarity comparison.

    ``precision=1`` buckets to ~7 miles, which is the right granularity for
    deciding whether two candidate routes are "the same road".
    """
    return frozenset((round(lon, precision), round(lat, precision)) for lon, lat in coords)


def similarity(a: frozenset, b: frozenset) -> float:
    """Jaccard overlap of two geometry fingerprints, in ``[0, 1]``."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
