"""Request validation for the planning API."""

from __future__ import annotations

from datetime import datetime, timezone

from django.conf import settings
from rest_framework import serializers

from .sampling import ALLOWED_INTERVALS_MILES
from .services import TripRequest


class TripRequestSerializer(serializers.Serializer):
    """Validates the driver's trip inputs."""

    origin = serializers.CharField(max_length=200, trim_whitespace=True)
    destination = serializers.CharField(max_length=200, trim_whitespace=True)
    depart_at = serializers.DateTimeField(
        help_text="ISO 8601 departure time. Naive values are treated as UTC."
    )
    load_lb = serializers.FloatField(min_value=0, max_value=settings.MAX_LOAD_LB)
    interval_miles = serializers.ChoiceField(
        choices=[(value, f"{value} miles") for value in ALLOWED_INTERVALS_MILES],
        default=25,
    )

    def validate_depart_at(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def validate(self, attrs: dict) -> dict:
        if attrs["origin"].strip().lower() == attrs["destination"].strip().lower():
            raise serializers.ValidationError(
                {"destination": "Destination must differ from origin."}
            )
        return attrs

    def to_trip_request(self) -> TripRequest:
        data = self.validated_data
        return TripRequest(
            origin=data["origin"],
            destination=data["destination"],
            depart_at=data["depart_at"],
            load_lb=float(data["load_lb"]),
            interval_miles=int(data["interval_miles"]),
        )


class HeatmapQuerySerializer(serializers.Serializer):
    """Validates heatmap lookups against a cached plan."""

    plan_id = serializers.CharField(max_length=64)
    route_id = serializers.CharField(max_length=64, required=False, allow_blank=True)
    hours = serializers.IntegerField(min_value=1, max_value=72, required=False)


class GeocodeQuerySerializer(serializers.Serializer):
    """Validates the typeahead lookup."""

    q = serializers.CharField(max_length=200, trim_whitespace=True)
    limit = serializers.IntegerField(min_value=1, max_value=8, required=False, default=5)
