"""API endpoints."""

from __future__ import annotations

import logging
import time

from django.conf import settings
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import services
from .providers.geocoding import geocode
from .risk import (
    RAIN_UPPER_BOUNDS_IN_HR,
    SNOW_UPPER_BOUNDS_IN_HR,
    WIND_LOWER_BOUNDS_MPH,
    Level,
    NO_TRAVEL_LOAD_LB,
    SEVERE_LOAD_LB,
)
from .sampling import ALLOWED_INTERVALS_MILES
from .serializers import (
    GeocodeQuerySerializer,
    HeatmapQuerySerializer,
    TripRequestSerializer,
)

logger = logging.getLogger(__name__)


@api_view(["GET"])
def health(request):
    """Liveness probe for the host platform."""
    return Response({"status": "ok"})


@api_view(["GET"])
def rules(request):
    """The risk thresholds the backend is actually using.

    Exposed so the UI legend and the engine can never drift apart.
    """
    return Response(
        {
            "levels": [
                {"name": level.label, "score": int(level)} for level in Level
            ],
            "wind_mph_lower_bounds": [
                {"level": level.label, "at_or_above": bound}
                for bound, level in reversed(WIND_LOWER_BOUNDS_MPH)
            ],
            "rain_in_hr_upper_bounds": [
                {"level": level.label, "up_to": bound}
                for bound, level in RAIN_UPPER_BOUNDS_IN_HR
            ],
            "snow_in_hr_upper_bounds": [
                {"level": level.label, "up_to": bound}
                for bound, level in SNOW_UPPER_BOUNDS_IN_HR
            ],
            "load_rules": [
                "Wind >= 55 mph: no travel at any load",
                f"Wind 45-54 mph with load > {NO_TRAVEL_LOAD_LB:,.0f} lb: no travel",
                f"Wind 35-44 mph with load > {SEVERE_LOAD_LB:,.0f} lb: severe",
            ],
            "recommendation_criteria": [
                "fewest no-travel miles",
                "fewest severe miles",
                "fewest high miles",
                "lowest average risk",
                "shortest travel time",
            ],
            "interval_options_miles": list(ALLOWED_INTERVALS_MILES),
            "max_load_lb": settings.MAX_LOAD_LB,
        }
    )


@api_view(["GET"])
def geocode_view(request):
    """Resolve a partial place name to coordinates, for the input typeahead."""
    query = GeocodeQuerySerializer(data=request.query_params)
    query.is_valid(raise_exception=True)
    places = geocode(
        query.validated_data["q"],
        limit=query.validated_data.get("limit") or 5,
    )
    return Response({"results": [place.to_dict() for place in places]})


@api_view(["POST"])
def plan_view(request):
    """Plan a trip: three routes, checkpoint risk, and a recommendation."""
    serializer = TripRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    trip = serializer.to_trip_request()

    started = time.perf_counter()
    payload = services.plan_trip(trip)
    elapsed_ms = round((time.perf_counter() - started) * 1000)

    payload["meta"]["elapsed_ms"] = elapsed_ms
    logger.info(
        "planned %s -> %s in %dms (%d routes)",
        trip.origin,
        trip.destination,
        elapsed_ms,
        len(payload["routes"]),
    )
    return Response(payload)


@api_view(["GET"])
def heatmap_view(request):
    """Corridor heatmap series for one route of a previously planned trip."""
    query = HeatmapQuerySerializer(data=request.query_params)
    query.is_valid(raise_exception=True)
    data = query.validated_data

    started = time.perf_counter()
    payload = services.corridor_heatmap(
        plan_id=data["plan_id"],
        route_id=data.get("route_id") or None,
        hours=data.get("hours"),
    )
    payload["meta"]["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
    return Response(payload)
