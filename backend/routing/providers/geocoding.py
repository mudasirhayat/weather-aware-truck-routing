"""Place-name -> coordinates via Nominatim (OpenStreetMap), no API key needed."""

from __future__ import annotations

import re
from dataclasses import dataclass

from django.conf import settings

from .base import NotFound, ProviderError, get_json

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

#: "39.7392, -104.9903" typed straight into the box.
_LATLON_RE = re.compile(
    r"^\s*(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)\s*$"
)


@dataclass(frozen=True)
class Place:
    """A resolved origin or destination."""

    query: str
    label: str
    lat: float
    lon: float

    @property
    def lonlat(self) -> tuple[float, float]:
        return (self.lon, self.lat)

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "label": self.label,
            "lat": self.lat,
            "lon": self.lon,
        }


def _parse_literal_coords(text: str) -> Place | None:
    """Accept raw ``lat, lon`` input without a round-trip to the geocoder."""
    match = _LATLON_RE.match(text)
    if not match:
        return None
    lat, lon = float(match.group(1)), float(match.group(2))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return Place(query=text, label=f"{lat:.4f}, {lon:.4f}", lat=lat, lon=lon)


def geocode(query: str, *, limit: int = 1) -> list[Place]:
    """Resolve a free-text place name to candidate coordinates."""
    text = (query or "").strip()
    if not text:
        raise NotFound("Please enter a location.", provider="geocoder")

    literal = _parse_literal_coords(text)
    if literal:
        return [literal]

    data = get_json(
        NOMINATIM_URL,
        {
            "q": text,
            "format": "jsonv2",
            "limit": max(1, min(limit, 8)),
            "addressdetails": 0,
        },
        provider="Nominatim geocoder",
        timeout=settings.GEOCODE_TIMEOUT_SECONDS,
        cache_prefix="geocode",
        cache_ttl=settings.GEOCODE_CACHE_SECONDS,
        # Nominatim's usage policy requires an identifying UA; SESSION sets it.
        headers={"Accept-Language": "en"},
    )

    if not isinstance(data, list) or not data:
        raise NotFound(
            f"Could not find a location matching “{text}”. "
            "Try adding a state or country.",
            provider="geocoder",
        )

    places: list[Place] = []
    for item in data:
        try:
            places.append(
                Place(
                    query=text,
                    label=item.get("display_name") or text,
                    lat=float(item["lat"]),
                    lon=float(item["lon"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue

    if not places:
        raise NotFound(
            f"Could not find a location matching “{text}”. "
            "Try adding a state or country.",
            provider="geocoder",
        )
    return places


def geocode_one(query: str) -> Place:
    """Resolve a place name to its single best match."""
    return geocode(query, limit=1)[0]
