"""Weather + load risk classification.

This module is deliberately pure (no I/O, no Django imports) so the rules in the
assessment brief can be unit-tested directly and reused anywhere.

Threshold tables from the brief
-------------------------------
            Low          Moderate    High       Severe      No Travel
Wind        <25 mph      25-34       35-44      45-54       >=55 mph
Rain        <0.10 in/hr  0.10-0.25   0.25-0.50  0.50-1.00   >1.00
Snow        <0.5 in/hr   0.5-1.0     1.0-2.0    2.0-3.0     >3.0

Load rules
----------
* >=55 mph                   -> No Travel for any load
* 45-54 mph + >30,000 lb     -> No Travel
* 35-44 mph + >40,000 lb     -> Severe

Reading the tables
------------------
The brief writes the wind bands with integer endpoints ("25-34", "35-44") which
leaves 34.x unlabelled, so wind is treated as a *continuous* scale with
inclusive lower bounds: [0,25) Low, [25,35) Moderate, [35,45) High, [45,55)
Severe, [55,inf) No Travel.

The rain/snow bands share endpoints between adjacent rows ("0.10-0.25" then
"0.25-0.50"). The shared value is resolved to the *lower* band, i.e. bands are
(prev, upper] with inclusive upper bounds. So 0.25 in/hr is Moderate and
0.50 in/hr is High.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional


class Level(IntEnum):
    """Risk levels, ordered so that ``max()`` picks the worse of two."""

    LOW = 0
    MODERATE = 1
    HIGH = 2
    SEVERE = 3
    NO_TRAVEL = 4

    @property
    def label(self) -> str:
        return self.name.lower()

    @classmethod
    def from_label(cls, label: str) -> "Level":
        return cls[label.upper()]


#: Wind bands as inclusive lower bounds, in mph.
WIND_LOWER_BOUNDS_MPH: tuple[tuple[float, Level], ...] = (
    (55.0, Level.NO_TRAVEL),
    (45.0, Level.SEVERE),
    (35.0, Level.HIGH),
    (25.0, Level.MODERATE),
    (0.0, Level.LOW),
)

#: Rain bands as inclusive upper bounds, in inches/hour.
RAIN_UPPER_BOUNDS_IN_HR: tuple[tuple[float, Level], ...] = (
    (0.10, Level.LOW),       # strictly < 0.10 is Low; see _classify_upper
    (0.25, Level.MODERATE),
    (0.50, Level.HIGH),
    (1.00, Level.SEVERE),
)

#: Snow bands as inclusive upper bounds, in inches/hour.
SNOW_UPPER_BOUNDS_IN_HR: tuple[tuple[float, Level], ...] = (
    (0.5, Level.LOW),        # strictly < 0.5 is Low; see _classify_upper
    (1.0, Level.MODERATE),
    (2.0, Level.HIGH),
    (3.0, Level.SEVERE),
)

#: Load thresholds, in pounds.
NO_TRAVEL_LOAD_LB = 30_000.0
SEVERE_LOAD_LB = 40_000.0


def classify_wind(wind_mph: float) -> Level:
    """Classify sustained wind speed in mph."""
    for lower, level in WIND_LOWER_BOUNDS_MPH:
        if wind_mph >= lower:
            return level
    return Level.LOW


def _classify_upper(value: float, bands: tuple[tuple[float, Level], ...]) -> Level:
    """Classify ``value`` against bands given as inclusive upper bounds.

    The first band is exclusive on its bound (the brief's "<0.10" / "<0.5" Low
    row); every later band is inclusive, so a value sitting exactly on a shared
    endpoint lands in the lower band.
    """
    first_bound, first_level = bands[0]
    if value < first_bound:
        return first_level
    for upper, level in bands[1:]:
        if value <= upper:
            return level
    return Level.NO_TRAVEL


def classify_rain(rain_in_hr: float) -> Level:
    """Classify rain rate in inches/hour."""
    return _classify_upper(rain_in_hr, RAIN_UPPER_BOUNDS_IN_HR)


def classify_snow(snow_in_hr: float) -> Level:
    """Classify snowfall rate in inches/hour."""
    return _classify_upper(snow_in_hr, SNOW_UPPER_BOUNDS_IN_HR)


def load_adjustment(wind_mph: float, load_lb: float) -> tuple[Level, Optional[str]]:
    """Apply the load rules, returning the floor they impose and an explanation.

    Returns ``Level.LOW`` (no floor) when no load rule fires.
    """
    if wind_mph >= 55.0:
        return Level.NO_TRAVEL, "Wind >=55 mph: no travel at any load"
    if 45.0 <= wind_mph < 55.0 and load_lb > NO_TRAVEL_LOAD_LB:
        return (
            Level.NO_TRAVEL,
            f"Wind 45-54 mph with load >{NO_TRAVEL_LOAD_LB:,.0f} lb: no travel",
        )
    if 35.0 <= wind_mph < 45.0 and load_lb > SEVERE_LOAD_LB:
        return (
            Level.SEVERE,
            f"Wind 35-44 mph with load >{SEVERE_LOAD_LB:,.0f} lb: severe",
        )
    return Level.LOW, None


@dataclass(frozen=True)
class RiskBreakdown:
    """Per-checkpoint risk result, including why the level was assigned."""

    level: Level
    wind_level: Level
    rain_level: Level
    snow_level: Level
    weather_level: Level
    load_rule: Optional[str] = None
    drivers: tuple[str, ...] = field(default_factory=tuple)

    @property
    def escalated_by_load(self) -> bool:
        return self.level > self.weather_level

    def to_dict(self) -> dict:
        return {
            "level": self.level.label,
            "level_score": int(self.level),
            "wind_level": self.wind_level.label,
            "rain_level": self.rain_level.label,
            "snow_level": self.snow_level.label,
            "weather_level": self.weather_level.label,
            "load_rule": self.load_rule,
            "escalated_by_load": self.escalated_by_load,
            "drivers": list(self.drivers),
        }


def assess(
    *,
    wind_mph: float,
    rain_in_hr: float,
    snow_in_hr: float,
    load_lb: float,
) -> RiskBreakdown:
    """Classify one checkpoint from its weather and the truck's load.

    The checkpoint level is the worst of the three weather conditions, then
    raised (never lowered) by whichever load rule applies.
    """
    wind = classify_wind(wind_mph)
    rain = classify_rain(rain_in_hr)
    snow = classify_snow(snow_in_hr)
    weather = max(wind, rain, snow)

    floor, rule = load_adjustment(wind_mph, load_lb)
    level = max(weather, floor)

    drivers: list[str] = []
    if wind == weather and wind > Level.LOW:
        drivers.append(f"wind {wind_mph:.0f} mph")
    if rain == weather and rain > Level.LOW:
        drivers.append(f"rain {rain_in_hr:.2f} in/hr")
    if snow == weather and snow > Level.LOW:
        drivers.append(f"snow {snow_in_hr:.2f} in/hr")
    if rule and level > weather:
        drivers.append(rule)

    return RiskBreakdown(
        level=level,
        wind_level=wind,
        rain_level=rain,
        snow_level=snow,
        weather_level=weather,
        load_rule=rule,
        drivers=tuple(drivers),
    )
