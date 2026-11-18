"""Hourly forecasts via Open-Meteo, no API key needed.

Two things make this fast enough for a 3-route, 100-checkpoint plan:

* **Batching** - Open-Meteo accepts comma-separated coordinate lists, so every
  checkpoint on every route is fetched in one or two HTTP calls rather than one
  call per point.
* **Spatial de-duplication** - checkpoints are snapped to a ~1 km grid before
  the request. The three routes share their origin and destination, and a 10
  mile interval oversamples a model whose native resolution is coarser than
  that, so this routinely removes a third of the points for free.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional, Sequence

from django.conf import settings

from ..geo import LonLat
from .base import ProviderError, get_json

logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

HOURLY_VARIABLES = (
    "wind_speed_10m",
    "wind_gusts_10m",
    "rain",
    "snowfall",
    "precipitation",
    "temperature_2m",
    "weather_code",
)

#: Coordinate rounding used for de-duplication: 2dp is ~1.1 km, well inside the
#: forecast model's own resolution.
GRID_DECIMALS = 2

#: Open-Meteo's own limits: how many coordinates per request, and how far the
#: forecast/history window reaches.
MAX_POINTS_PER_REQUEST = 100
MAX_FORECAST_DAYS = 16
MAX_PAST_DAYS = 92


@dataclass(frozen=True)
class WeatherSample:
    """Forecast values at one point and one hour, in the brief's units."""

    time: datetime
    wind_mph: float
    gust_mph: float
    rain_in_hr: float
    snow_in_hr: float
    precipitation_in_hr: float
    temperature_c: Optional[float]
    weather_code: Optional[int]

    def to_dict(self) -> dict:
        return {
            "time": self.time.isoformat(),
            "wind_mph": round(self.wind_mph, 1),
            "gust_mph": round(self.gust_mph, 1),
            "rain_in_hr": round(self.rain_in_hr, 3),
            "snow_in_hr": round(self.snow_in_hr, 3),
            "precipitation_in_hr": round(self.precipitation_in_hr, 3),
            "temperature_c": None if self.temperature_c is None else round(self.temperature_c, 1),
            "weather_code": self.weather_code,
        }


def _f(values: Optional[list], index: int) -> float:
    """Read a float from an Open-Meteo array, treating nulls as zero."""
    if not values or index >= len(values):
        return 0.0
    value = values[index]
    return 0.0 if value is None else float(value)


@dataclass
class HourlySeries:
    """A contiguous hourly forecast series for one location."""

    lat: float
    lon: float
    start: datetime
    hours: int
    data: dict[str, list]

    def index_for(self, when: datetime) -> Optional[int]:
        """Hour index containing ``when``, or ``None`` if out of coverage."""
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        offset = (when.astimezone(timezone.utc) - self.start).total_seconds() / 3600.0
        index = int(offset // 1)
        if index < 0 or index >= self.hours:
            return None
        return index

    def at_index(self, index: int) -> Optional[WeatherSample]:
        if index < 0 or index >= self.hours:
            return None
        temps = self.data.get("temperature_2m") or []
        codes = self.data.get("weather_code") or []
        return WeatherSample(
            time=self.start + timedelta(hours=index),
            wind_mph=_f(self.data.get("wind_speed_10m"), index),
            gust_mph=_f(self.data.get("wind_gusts_10m"), index),
            rain_in_hr=_f(self.data.get("rain"), index),
            snow_in_hr=_f(self.data.get("snowfall"), index),
            precipitation_in_hr=_f(self.data.get("precipitation"), index),
            temperature_c=(
                None
                if index >= len(temps) or temps[index] is None
                else float(temps[index])
            ),
            weather_code=(
                None
                if index >= len(codes) or codes[index] is None
                else int(codes[index])
            ),
        )

    def at(self, when: datetime) -> Optional[WeatherSample]:
        """Forecast for the hour containing ``when``."""
        index = self.index_for(when)
        return None if index is None else self.at_index(index)


class WeatherGrid:
    """Forecast lookup keyed by position, backed by de-duplicated series."""

    def __init__(self, series_by_cell: dict[tuple[float, float], HourlySeries], start: datetime, hours: int):
        self._series = series_by_cell
        self.start = start
        self.hours = hours

    @staticmethod
    def cell(point: LonLat) -> tuple[float, float]:
        return (round(point[0], GRID_DECIMALS), round(point[1], GRID_DECIMALS))

    def series_for(self, point: LonLat) -> Optional[HourlySeries]:
        return self._series.get(self.cell(point))

    def at(self, point: LonLat, when: datetime) -> Optional[WeatherSample]:
        series = self.series_for(point)
        return None if series is None else series.at(when)

    def at_hour_offset(self, point: LonLat, offset: int) -> Optional[WeatherSample]:
        """Sample ``offset`` hours after the grid's start hour."""
        series = self.series_for(point)
        return None if series is None else series.at_index(offset)

    @property
    def point_count(self) -> int:
        return len(self._series)


def _window(start_at: datetime, end_at: datetime) -> tuple[int, int, datetime]:
    """Translate an absolute time window into Open-Meteo's day parameters.

    ``past_days``/``forecast_days`` are used rather than ``start_date``/
    ``end_date`` because they always yield a contiguous hourly series anchored
    at midnight UTC, which is what the O(1) index lookup relies on.
    """
    today = datetime.now(timezone.utc).date()
    start_day: date = start_at.astimezone(timezone.utc).date()
    end_day: date = end_at.astimezone(timezone.utc).date()

    past_days = max(0, min((today - start_day).days, MAX_PAST_DAYS))
    forecast_days = max(1, min((end_day - today).days + 1, MAX_FORECAST_DAYS))

    series_start = datetime.combine(
        today - timedelta(days=past_days),
        datetime.min.time(),
        tzinfo=timezone.utc,
    )
    return past_days, forecast_days, series_start


def _chunks(items: Sequence, size: int) -> Iterable[Sequence]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def fetch_grid(
    points: Iterable[LonLat],
    start_at: datetime,
    end_at: datetime,
) -> WeatherGrid:
    """Fetch hourly forecasts covering ``[start_at, end_at]`` for ``points``."""
    cells: list[tuple[float, float]] = []
    seen: set[tuple[float, float]] = set()
    for point in points:
        cell = WeatherGrid.cell(point)
        if cell not in seen:
            seen.add(cell)
            cells.append(cell)

    if not cells:
        raise ProviderError("No points to fetch weather for.", provider="Open-Meteo")

    past_days, forecast_days, series_start = _window(start_at, end_at)
    expected_hours = (past_days + forecast_days) * 24

    series_by_cell: dict[tuple[float, float], HourlySeries] = {}

    for chunk in _chunks(cells, MAX_POINTS_PER_REQUEST):
        params = {
            "latitude": ",".join(f"{lat:.4f}" for _, lat in chunk),
            "longitude": ",".join(f"{lon:.4f}" for lon, _ in chunk),
            "hourly": ",".join(HOURLY_VARIABLES),
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
            "timezone": "UTC",
            "past_days": past_days,
            "forecast_days": forecast_days,
            "cell_selection": "nearest",
        }
        payload = get_json(
            OPEN_METEO_URL,
            params,
            provider="Open-Meteo weather",
            timeout=settings.WEATHER_TIMEOUT_SECONDS,
            cache_prefix="weather",
            cache_ttl=settings.WEATHER_CACHE_SECONDS,
        )

        # A single coordinate returns an object; several return a list.
        entries = payload if isinstance(payload, list) else [payload]
        if len(entries) != len(chunk):
            raise ProviderError(
                "Weather provider returned a mismatched number of locations.",
                provider="Open-Meteo weather",
            )

        for cell, entry in zip(chunk, entries):
            hourly = entry.get("hourly") or {}
            times = hourly.get("time") or []
            if not times:
                continue
            series_by_cell[cell] = HourlySeries(
                lat=float(entry.get("latitude", cell[1])),
                lon=float(entry.get("longitude", cell[0])),
                start=series_start,
                hours=len(times),
                data=hourly,
            )

    if not series_by_cell:
        raise ProviderError(
            "Weather provider returned no usable forecast.",
            provider="Open-Meteo weather",
        )

    hours = max(s.hours for s in series_by_cell.values())
    logger.debug(
        "weather grid: %d unique cells, %d hours (expected %d)",
        len(series_by_cell),
        hours,
        expected_hours,
    )
    return WeatherGrid(series_by_cell, series_start, hours)
