"""Trip planning orchestration: geocode -> route -> sample -> score -> rank."""

from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from django.conf import settings
from django.core.cache import cache

from .exceptions import PlanningError
from .geo import LonLat, bbox
from .providers.geocoding import Place, geocode_one
from .providers.routing_osrm import RouteCandidate, route_options
from .providers.weather import WeatherGrid, WeatherSample, fetch_grid
from .risk import Level, assess
from .sampling import Checkpoint, corridor_points, sample_checkpoints
from .scoring import RouteMetrics, explain_choice, rank_routes, summarize_route

logger = logging.getLogger(__name__)

#: Plans are cached so the heatmap endpoint can re-use the chosen geometry
#: without the client posting a 5,000-point polyline back to us.
PLAN_CACHE_SECONDS = 3600
PLAN_CACHE_PREFIX = "plan"

#: Polyline resolution sent to the browser. The full OSRM overview can be 5,000+
#: points per route; Leaflet renders a ~700-point line identically at map zooms
#: and three of those keep the payload small and panning smooth.
MAX_POLYLINE_POINTS = 700


@dataclass(frozen=True)
class TripRequest:
    """Validated planning inputs."""

    origin: str
    destination: str
    depart_at: datetime
    load_lb: float
    interval_miles: int


def _simplify(coords: Sequence[LonLat], max_points: int = MAX_POLYLINE_POINTS) -> list[list[float]]:
    """Evenly decimate a polyline for transport, always keeping both ends."""
    n = len(coords)
    if n <= max_points:
        return [[round(lat, 5), round(lon, 5)] for lon, lat in coords]
    step = n / float(max_points - 1)
    picked = [coords[min(n - 1, int(i * step))] for i in range(max_points - 1)]
    picked.append(coords[-1])
    return [[round(lat, 5), round(lon, 5)] for lon, lat in picked]


def _resolve_endpoints(request: TripRequest) -> tuple[Place, Place]:
    """Geocode origin and destination, and reject a zero-length trip."""
    origin = geocode_one(request.origin)
    destination = geocode_one(request.destination)

    from .geo import haversine_miles

    if haversine_miles(origin.lonlat, destination.lonlat) < 0.5:
        raise PlanningError(
            "Origin and destination resolve to the same place; pick two different locations."
        )
    return origin, destination


def _classify_checkpoints(
    checkpoints: Sequence[Checkpoint],
    grid: WeatherGrid,
    load_lb: float,
) -> tuple[list[Optional[Level]], list[dict]]:
    """Attach weather + risk to each checkpoint."""
    levels: list[Optional[Level]] = []
    payload: list[dict] = []

    for checkpoint in checkpoints:
        sample: Optional[WeatherSample] = grid.at(checkpoint.lonlat, checkpoint.eta)
        if sample is None:
            levels.append(None)
            payload.append(
                {
                    "index": checkpoint.index,
                    "lat": checkpoint.lat,
                    "lon": checkpoint.lon,
                    "distance_miles": round(checkpoint.distance_miles, 1),
                    "eta": checkpoint.eta.isoformat(),
                    "elapsed_hours": round(checkpoint.elapsed_hours, 2),
                    "weather": None,
                    "risk": None,
                    "note": "No forecast available for this arrival time.",
                }
            )
            continue

        breakdown = assess(
            wind_mph=sample.wind_mph,
            rain_in_hr=sample.rain_in_hr,
            snow_in_hr=sample.snow_in_hr,
            load_lb=load_lb,
        )
        levels.append(breakdown.level)
        payload.append(
            {
                "index": checkpoint.index,
                "lat": checkpoint.lat,
                "lon": checkpoint.lon,
                "distance_miles": round(checkpoint.distance_miles, 1),
                "eta": checkpoint.eta.isoformat(),
                "elapsed_hours": round(checkpoint.elapsed_hours, 2),
                "weather": sample.to_dict(),
                "risk": breakdown.to_dict(),
            }
        )

    return levels, payload


def _route_label(index: int, candidate: RouteCandidate) -> str:
    if index == 0 and candidate.source == "fastest":
        return "Fastest route"
    if candidate.source.startswith("detour"):
        return f"Alternate via {candidate.source.removeprefix('detour ')}"
    return f"Alternate {index + 1}"


def plan_trip(request: TripRequest) -> dict:
    """Plan a trip and return the full API payload."""
    origin, destination = _resolve_endpoints(request)

    candidates = route_options(
        origin.lonlat,
        destination.lonlat,
        want=settings.MAX_ROUTE_OPTIONS,
    )
    if not candidates:
        raise PlanningError("No drivable route was found between those locations.")

    # Sample every candidate first so one batched weather call covers them all.
    sampled: list[tuple[RouteCandidate, list[Checkpoint], float, bool]] = []
    for candidate in candidates:
        checkpoints, total_miles, coarsened = sample_checkpoints(
            candidate.coords,
            request.depart_at,
            request.interval_miles,
            segment_miles=candidate.segment_miles,
            segment_seconds=candidate.segment_seconds if candidate.has_segment_timing else None,
            total_duration_seconds=candidate.duration_seconds,
        )
        sampled.append((candidate, checkpoints, total_miles, coarsened))

    all_points = [cp.lonlat for _, checkpoints, _, _ in sampled for cp in checkpoints]
    latest_arrival = max(
        checkpoints[-1].eta for _, checkpoints, _, _ in sampled
    )
    grid = fetch_grid(all_points, request.depart_at, latest_arrival)

    routes: list[dict] = []
    metrics: list[RouteMetrics] = []
    for index, (candidate, checkpoints, total_miles, coarsened) in enumerate(sampled):
        levels, checkpoint_payload = _classify_checkpoints(checkpoints, grid, request.load_lb)
        route_metrics = summarize_route(
            checkpoints, levels, total_miles, candidate.duration_hours
        )
        metrics.append(route_metrics)

        min_lon, min_lat, max_lon, max_lat = bbox(candidate.coords)
        routes.append(
            {
                "id": f"route-{index}",
                "label": _route_label(index, candidate),
                "source": candidate.source,
                "geometry": _simplify(candidate.coords),
                "bounds": [[min_lat, min_lon], [max_lat, max_lon]],
                "arrival": checkpoints[-1].eta.isoformat(),
                "checkpoint_interval_miles": request.interval_miles,
                "checkpoint_interval_coarsened": coarsened,
                "checkpoints": checkpoint_payload,
                "metrics": route_metrics.to_dict(),
            }
        )

    order = rank_routes(metrics)
    best = order[0]
    runner_up = metrics[order[1]] if len(order) > 1 else None

    for rank, route_index in enumerate(order):
        routes[route_index]["rank"] = rank + 1
        routes[route_index]["recommended"] = rank == 0

    plan_id = uuid.uuid4().hex[:16]
    cache.set(
        f"{PLAN_CACHE_PREFIX}:{plan_id}",
        {
            "depart_at": request.depart_at.isoformat(),
            "load_lb": request.load_lb,
            "routes": [
                {"id": routes[i]["id"], "label": routes[i]["label"], "coords": candidates[i].coords}
                for i in range(len(candidates))
            ],
        },
        PLAN_CACHE_SECONDS,
    )

    return {
        "plan_id": plan_id,
        "request": {
            "origin": origin.to_dict(),
            "destination": destination.to_dict(),
            "depart_at": request.depart_at.isoformat(),
            "load_lb": request.load_lb,
            "interval_miles": request.interval_miles,
        },
        "routes": routes,
        "recommendation": {
            "route_id": routes[best]["id"],
            "route_index": best,
            "reason": explain_choice(metrics[best], runner_up),
            "travel_advised": metrics[best].travel_advised,
            "ranking": [routes[i]["id"] for i in order],
            "criteria": [
                "fewest no-travel miles",
                "fewest severe miles",
                "fewest high miles",
                "lowest average risk",
                "shortest travel time",
            ],
        },
        "meta": {
            "weather_points_fetched": grid.point_count,
            "weather_points_requested": len(all_points),
            "forecast_start": grid.start.isoformat(),
            "forecast_hours": grid.hours,
            "providers": {
                "geocoding": "Nominatim (OpenStreetMap)",
                "routing": f"OSRM ({settings.OSRM_PROFILE})",
                "weather": "Open-Meteo",
            },
        },
    }


def load_plan(plan_id: str) -> dict:
    """Retrieve a cached plan, or explain that it has expired."""
    plan = cache.get(f"{PLAN_CACHE_PREFIX}:{plan_id}")
    if not plan:
        raise PlanningError(
            "That plan has expired. Re-run the search to refresh the heatmap."
        )
    return plan


def corridor_heatmap(
    plan_id: str,
    route_id: Optional[str] = None,
    hours: Optional[int] = None,
) -> dict:
    """Build the corridor heatmap series for one route of a cached plan.

    Returns every hour in one response (not one request per slider position) so
    dragging the 0-48h slider is instant and makes no network calls.
    """
    plan = load_plan(plan_id)
    routes = plan["routes"]
    chosen = next((r for r in routes if r["id"] == route_id), routes[0])

    coords: list[LonLat] = [tuple(c) for c in chosen["coords"]]
    points = corridor_points(
        coords,
        settings.HEATMAP_MIN_SPACING_MILES,
        settings.HEATMAP_MAX_POINTS,
    )
    if not points:
        raise PlanningError("That route is too short to build a corridor heatmap.")

    depart_at = datetime.fromisoformat(plan["depart_at"])
    if depart_at.tzinfo is None:
        depart_at = depart_at.replace(tzinfo=timezone.utc)
    load_lb = float(plan["load_lb"])

    span = max(1, min(int(hours or settings.HEATMAP_HOURS), 72))
    # The slider is anchored on the departure hour: hour 0 is "when the truck
    # rolls", which is the window a dispatcher actually cares about.
    anchor = depart_at.replace(minute=0, second=0, microsecond=0)
    grid = fetch_grid([p.lonlat for p in points], anchor, anchor + timedelta(hours=span))

    base_index = grid.series_for(points[0].lonlat)
    start_offset = 0
    if base_index is not None:
        resolved = base_index.index_for(anchor)
        start_offset = 0 if resolved is None else resolved

    timeline = [(anchor + timedelta(hours=h)).isoformat() for h in range(span + 1)]

    series: list[dict] = []
    for point in points:
        risk: list[Optional[int]] = []
        wind: list[Optional[float]] = []
        rain: list[Optional[float]] = []
        snow: list[Optional[float]] = []
        for h in range(span + 1):
            sample = grid.at_hour_offset(point.lonlat, start_offset + h)
            if sample is None:
                risk.append(None)
                wind.append(None)
                rain.append(None)
                snow.append(None)
                continue
            breakdown = assess(
                wind_mph=sample.wind_mph,
                rain_in_hr=sample.rain_in_hr,
                snow_in_hr=sample.snow_in_hr,
                load_lb=load_lb,
            )
            risk.append(int(breakdown.level))
            wind.append(round(sample.wind_mph, 1))
            rain.append(round(sample.rain_in_hr, 3))
            snow.append(round(sample.snow_in_hr, 3))

        series.append(
            {
                "lat": point.lat,
                "lon": point.lon,
                "distance_miles": point.distance_miles,
                "risk": risk,
                "wind_mph": wind,
                "rain_in_hr": rain,
                "snow_in_hr": snow,
            }
        )

    return {
        "plan_id": plan_id,
        "route_id": chosen["id"],
        "route_label": chosen["label"],
        "anchor": anchor.isoformat(),
        "hours": span,
        "timeline": timeline,
        "levels": [level.label for level in Level],
        "points": series,
        "meta": {
            "point_count": len(series),
            "min_spacing_miles": settings.HEATMAP_MIN_SPACING_MILES,
            "load_lb": load_lb,
        },
    }
