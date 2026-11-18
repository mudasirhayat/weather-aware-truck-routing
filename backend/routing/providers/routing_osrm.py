"""Route geometry via OSRM (public demo server), no API key needed.

Why perturbation
----------------
The brief asks for *three* route options. OSRM's ``alternatives`` parameter is
best-effort: on many corridors it returns only one or two genuinely different
roads. When it comes up short we synthesise extra candidates by routing through
a via-point offset perpendicular to the direct line, which is how a dispatcher
would force a different corridor ("go round the north side"). Candidates are
then de-duplicated geometrically so we never show the same road twice.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Optional, Sequence

from django.conf import settings

from ..geo import (
    LonLat,
    bearing_degrees,
    geometry_fingerprint,
    haversine_miles,
    offset_point,
    polyline_segment_miles,
    similarity,
)
from .base import ProviderError, get_json

logger = logging.getLogger(__name__)

METERS_PER_MILE = 1609.344

#: Lateral offsets tried when OSRM gives us too few alternatives, in miles.
#: Signed: positive is left of the direct bearing, negative is right.
VIA_OFFSETS_MILES: tuple[float, ...] = (45.0, -45.0, 90.0, -90.0, 150.0, -150.0)

#: Two candidates sharing more than this fraction of their coarse geometry are
#: treated as the same road.
DUPLICATE_SIMILARITY = 0.72


@dataclass
class RouteCandidate:
    """One route option with the per-segment data needed for honest ETAs."""

    coords: list[LonLat]
    distance_miles: float
    duration_seconds: float
    segment_miles: list[float]
    segment_seconds: list[float]
    source: str = "alternative"
    fingerprint: frozenset = field(default_factory=frozenset)

    @property
    def duration_hours(self) -> float:
        return self.duration_seconds / 3600.0

    @property
    def has_segment_timing(self) -> bool:
        return len(self.segment_seconds) == len(self.coords) - 1


def _osrm_url(points: Sequence[LonLat]) -> str:
    coords = ";".join(f"{lon:.6f},{lat:.6f}" for lon, lat in points)
    return f"{settings.OSRM_BASE_URL.rstrip('/')}/route/v1/{settings.OSRM_PROFILE}/{coords}"


def _candidate_from_route(route: dict, source: str) -> Optional[RouteCandidate]:
    """Convert one OSRM route object into a :class:`RouteCandidate`."""
    geometry = (route.get("geometry") or {}).get("coordinates") or []
    if len(geometry) < 2:
        return None
    coords: list[LonLat] = [(float(c[0]), float(c[1])) for c in geometry]

    # Concatenate per-leg annotations. Each leg of N nodes contributes N-1
    # segments and consecutive legs share their boundary node, so the
    # concatenation lines up with the overview geometry's segments.
    seg_m: list[float] = []
    seg_s: list[float] = []
    for leg in route.get("legs") or []:
        annotation = leg.get("annotation") or {}
        seg_m.extend(float(x) for x in annotation.get("distance") or [])
        seg_s.extend(float(x) for x in annotation.get("duration") or [])

    expected = len(coords) - 1
    if len(seg_m) == expected and len(seg_s) == expected:
        segment_miles = [m / METERS_PER_MILE for m in seg_m]
        segment_seconds = seg_s
    else:
        # Annotations missing or misaligned: fall back to measuring the polyline
        # and spreading the reported duration across it.
        logger.debug(
            "OSRM annotations misaligned (%d/%d vs %d); using geometric fallback",
            len(seg_m),
            len(seg_s),
            expected,
        )
        segment_miles = polyline_segment_miles(coords)
        total = sum(segment_miles) or 1.0
        duration = float(route.get("duration") or 0.0)
        segment_seconds = [duration * (m / total) for m in segment_miles]

    distance_miles = float(route.get("distance") or 0.0) / METERS_PER_MILE
    if distance_miles <= 0:
        distance_miles = sum(segment_miles)

    return RouteCandidate(
        coords=coords,
        distance_miles=distance_miles,
        duration_seconds=float(route.get("duration") or sum(segment_seconds)),
        segment_miles=segment_miles,
        segment_seconds=segment_seconds,
        source=source,
        fingerprint=geometry_fingerprint(coords),
    )


def _fetch(points: Sequence[LonLat], alternatives: int | bool) -> list[dict]:
    """Call OSRM and return its raw route list."""
    params = {
        "overview": "full",
        "geometries": "geojson",
        "annotations": "distance,duration",
        "steps": "false",
    }
    # OSRM only honours `alternatives` for two-point queries.
    if alternatives and len(points) == 2:
        params["alternatives"] = alternatives

    data = get_json(
        _osrm_url(points),
        params,
        provider="OSRM routing",
        timeout=settings.ROUTING_TIMEOUT_SECONDS,
        cache_prefix="osrm",
        cache_ttl=settings.ROUTING_CACHE_SECONDS,
    )

    code = data.get("code")
    if code == "NoRoute":
        raise ProviderError(
            "No drivable route exists between those points.", provider="OSRM routing"
        )
    if code != "Ok":
        raise ProviderError(
            f"Routing failed: {data.get('message') or code}", provider="OSRM routing"
        )
    return data.get("routes") or []


def _accept(candidate: RouteCandidate, chosen: list[RouteCandidate]) -> bool:
    """Keep a candidate only if it is a materially different road."""
    return all(
        similarity(candidate.fingerprint, existing.fingerprint) <= DUPLICATE_SIMILARITY
        for existing in chosen
    )


def _via_points(origin: LonLat, destination: LonLat) -> list[tuple[LonLat, float]]:
    """Candidate via-points offset perpendicular to the direct line."""
    direct = haversine_miles(origin, destination)
    bearing = bearing_degrees(origin, destination)
    midpoint = offset_point(origin, bearing, direct / 2.0)

    # Scale offsets to the trip: a 60-mile hop should not detour 150 miles.
    scale = max(0.15, min(1.0, direct / 400.0))
    out: list[tuple[LonLat, float]] = []
    for offset in VIA_OFFSETS_MILES:
        distance = offset * scale
        side_bearing = (bearing + (90.0 if offset > 0 else -90.0)) % 360.0
        out.append((offset_point(midpoint, side_bearing, abs(distance)), distance))
    return out


def route_options(
    origin: LonLat,
    destination: LonLat,
    want: int = 3,
) -> list[RouteCandidate]:
    """Return up to ``want`` materially different routes, best-effort.

    Always returns at least one route, or raises :class:`ProviderError`.
    """
    chosen: list[RouteCandidate] = []

    for index, route in enumerate(_fetch([origin, destination], alternatives=want)):
        candidate = _candidate_from_route(route, "fastest" if index == 0 else "alternative")
        if candidate and _accept(candidate, chosen):
            chosen.append(candidate)
        if len(chosen) >= want:
            return chosen[:want]

    if not chosen:
        raise ProviderError(
            "No drivable route exists between those points.", provider="OSRM routing"
        )

    # Still short: force different corridors with offset via-points. The
    # candidates are fetched concurrently (one round-trip of latency instead of
    # six) but accepted in a fixed offset order so results stay deterministic.
    needed = want - len(chosen)
    attempts = _via_points(origin, destination)[: max(0, needed) * 2]
    if not attempts:
        return chosen[:want]

    def fetch_via(attempt: tuple[LonLat, float]) -> tuple[float, list[dict]]:
        via, offset = attempt
        try:
            return offset, _fetch([origin, via, destination], alternatives=False)
        except ProviderError as exc:
            logger.debug("via-point detour failed, skipping: %s", exc)
            return offset, []

    with ThreadPoolExecutor(max_workers=min(3, len(attempts))) as pool:
        results = list(pool.map(fetch_via, attempts))

    for offset, routes in results:
        if len(chosen) >= want:
            break
        for route in routes:
            side = "north/west" if offset > 0 else "south/east"
            candidate = _candidate_from_route(route, f"detour {side}")
            if not candidate:
                continue
            # Reject absurd detours - a route 2.2x the fastest is not an option.
            if candidate.distance_miles > chosen[0].distance_miles * 2.2:
                continue
            if _accept(candidate, chosen):
                chosen.append(candidate)
                break

    return chosen[:want]
