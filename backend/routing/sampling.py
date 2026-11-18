"""Turn a route polyline into weather checkpoints with arrival times."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Sequence

from .geo import (
    LonLat,
    cumulative,
    interpolate_series,
    locate_at_distance,
    polyline_segment_miles,
)

#: Sampling intervals offered by the UI, in miles.
ALLOWED_INTERVALS_MILES: tuple[int, ...] = (10, 25, 50)

#: Safety valve: a 10-mile interval on a 3,000-mile route would be 300 weather
#: points per route. Past this we coarsen the interval and report that we did.
MAX_CHECKPOINTS_PER_ROUTE = 160


@dataclass(frozen=True)
class Checkpoint:
    """A sampled point along a route with the truck's predicted arrival."""

    index: int
    lon: float
    lat: float
    distance_miles: float
    elapsed_seconds: float
    eta: datetime

    @property
    def lonlat(self) -> LonLat:
        return (self.lon, self.lat)

    @property
    def elapsed_hours(self) -> float:
        return self.elapsed_seconds / 3600.0


def effective_interval(total_miles: float, requested_miles: int) -> tuple[float, bool]:
    """Clamp the sampling interval so one route can't explode into 300 calls.

    Returns the interval actually used and whether it was coarsened.
    """
    requested = float(max(1, requested_miles))
    if total_miles <= 0:
        return requested, False
    needed = total_miles / requested
    if needed <= MAX_CHECKPOINTS_PER_ROUTE:
        return requested, False
    return total_miles / MAX_CHECKPOINTS_PER_ROUTE, True


def sample_checkpoints(
    coords: Sequence[LonLat],
    depart_at: datetime,
    interval_miles: int,
    segment_miles: Optional[Sequence[float]] = None,
    segment_seconds: Optional[Sequence[float]] = None,
    total_duration_seconds: Optional[float] = None,
) -> tuple[list[Checkpoint], float, bool]:
    """Sample a route every ``interval_miles``, including both endpoints.

    ``segment_seconds`` is the routing engine's per-segment duration array
    (aligned to ``coords``, so ``len == len(coords) - 1``). When present, ETAs
    follow the real speed profile; otherwise they fall back to spreading
    ``total_duration_seconds`` evenly across distance.

    Returns ``(checkpoints, total_miles, interval_was_coarsened)``.
    """
    if len(coords) < 2:
        raise ValueError("a route needs at least two coordinates")

    seg_mi = list(segment_miles) if segment_miles else polyline_segment_miles(coords)
    if len(seg_mi) != len(coords) - 1:
        raise ValueError("segment_miles must align with coords")

    cum_mi = cumulative(seg_mi)
    total_miles = cum_mi[-1]

    if segment_seconds is not None and len(segment_seconds) == len(coords) - 1:
        cum_sec = cumulative(segment_seconds)
    else:
        # No per-segment timing: assume a constant average speed.
        total = float(total_duration_seconds or 0.0)
        cum_sec = [0.0] * len(cum_mi) if total_miles <= 0 else [
            total * (m / total_miles) for m in cum_mi
        ]

    interval, coarsened = effective_interval(total_miles, interval_miles)

    # Build target distances: 0, interval, 2*interval, ... then the destination.
    targets: list[float] = []
    d = 0.0
    while d < total_miles:
        targets.append(d)
        d += interval
    # Always finish at the destination, but don't emit a near-duplicate of it.
    if targets and (total_miles - targets[-1]) < interval * 0.25 and len(targets) > 1:
        targets[-1] = total_miles
    else:
        targets.append(total_miles)

    checkpoints: list[Checkpoint] = []
    for i, target in enumerate(targets):
        point, _, _ = locate_at_distance(coords, cum_mi, target)
        elapsed = interpolate_series(cum_mi, cum_sec, target)
        checkpoints.append(
            Checkpoint(
                index=i,
                lon=round(point[0], 6),
                lat=round(point[1], 6),
                distance_miles=round(target, 3),
                elapsed_seconds=round(elapsed, 1),
                eta=depart_at + timedelta(seconds=elapsed),
            )
        )
    return checkpoints, total_miles, coarsened


def corridor_points(
    coords: Sequence[LonLat],
    min_spacing_miles: float,
    max_points: int,
) -> list[Checkpoint]:
    """Evenly spaced points along a route, for the corridor heatmap.

    Density targets ``max_points`` so a 90-mile run and a 900-mile run both
    produce a usable heatmap, with ``min_spacing_miles`` as a floor to avoid
    oversampling a short corridor far past the forecast model's resolution.

    Unlike :func:`sample_checkpoints` these carry no timing - the heatmap shows
    a chosen forecast hour everywhere at once rather than the truck's ETA.
    """
    seg_mi = polyline_segment_miles(coords)
    cum_mi = cumulative(seg_mi)
    total = cum_mi[-1]
    if total <= 0:
        return []

    spacing = max(min_spacing_miles, total / max(1, max_points - 1))
    count = max(2, min(max_points, int(total / spacing) + 1))
    step = total / (count - 1)

    out: list[Checkpoint] = []
    epoch = datetime(1970, 1, 1)
    for i in range(count):
        target = min(total, i * step)
        point, _, _ = locate_at_distance(coords, cum_mi, target)
        out.append(
            Checkpoint(
                index=i,
                lon=round(point[0], 5),
                lat=round(point[1], 5),
                distance_miles=round(target, 2),
                elapsed_seconds=0.0,
                eta=epoch,
            )
        )
    return out
