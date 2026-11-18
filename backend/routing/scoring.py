"""Aggregate checkpoint risk into route metrics and pick a recommendation.

Recommendation order from the brief
-----------------------------------
1. Fewest Severe miles
2. Fewest High miles
3. Lowest average risk
4. Shortest travel time

One addition, made explicit here and surfaced in the API: *No Travel* miles are
compared before Severe miles. A No Travel checkpoint means the truck legally /
safely cannot pass, which is strictly worse than Severe, and the brief's table
treats it as its own level above Severe. Routes with any No Travel mileage are
also flagged ``travel_advised: false`` so the UI can warn rather than silently
recommend an impassable route.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from .risk import Level
from .sampling import Checkpoint

#: Tie-break order for route comparison. Lower is better on every key.
RANKING_KEYS: tuple[str, ...] = (
    "no_travel_miles",
    "severe_miles",
    "high_miles",
    "average_risk",
    "duration_hours",
)


def attribute_miles(
    checkpoints: Sequence[Checkpoint],
    total_miles: float,
) -> list[float]:
    """Split the route's mileage across its checkpoints.

    Each checkpoint owns the stretch from the midpoint behind it to the midpoint
    ahead of it, so the attributed miles sum to the route length and no stretch
    of road is counted twice. That is what makes "Severe miles" a real distance
    rather than a count of samples.
    """
    n = len(checkpoints)
    if n == 0:
        return []
    if n == 1:
        return [total_miles]

    d = [c.distance_miles for c in checkpoints]
    out: list[float] = []
    for i in range(n):
        lower = 0.0 if i == 0 else (d[i - 1] + d[i]) / 2.0
        upper = total_miles if i == n - 1 else (d[i] + d[i + 1]) / 2.0
        out.append(max(0.0, upper - lower))
    return out


@dataclass
class RouteMetrics:
    """Risk-weighted summary of one route option."""

    distance_miles: float
    duration_hours: float
    miles_by_level: dict[str, float]
    average_risk: float
    worst_level: Level
    checkpoints_by_level: dict[str, int]
    scored_miles: float
    unknown_weather_miles: float

    @property
    def no_travel_miles(self) -> float:
        return self.miles_by_level[Level.NO_TRAVEL.label]

    @property
    def severe_miles(self) -> float:
        return self.miles_by_level[Level.SEVERE.label]

    @property
    def high_miles(self) -> float:
        return self.miles_by_level[Level.HIGH.label]

    @property
    def travel_advised(self) -> bool:
        return self.no_travel_miles <= 0.0

    def ranking_key(self) -> tuple[float, ...]:
        return (
            round(self.no_travel_miles, 2),
            round(self.severe_miles, 2),
            round(self.high_miles, 2),
            round(self.average_risk, 4),
            round(self.duration_hours, 4),
        )

    def to_dict(self) -> dict:
        return {
            "distance_miles": round(self.distance_miles, 1),
            "duration_hours": round(self.duration_hours, 2),
            "miles_by_level": {k: round(v, 1) for k, v in self.miles_by_level.items()},
            "checkpoints_by_level": self.checkpoints_by_level,
            "average_risk": round(self.average_risk, 3),
            "worst_level": self.worst_level.label,
            "travel_advised": self.travel_advised,
            "scored_miles": round(self.scored_miles, 1),
            "unknown_weather_miles": round(self.unknown_weather_miles, 1),
        }


def summarize_route(
    checkpoints: Sequence[Checkpoint],
    levels: Sequence[Optional[Level]],
    total_miles: float,
    duration_hours: float,
) -> RouteMetrics:
    """Build :class:`RouteMetrics` from classified checkpoints.

    ``levels`` may contain ``None`` where the forecast did not cover a
    checkpoint's ETA; those miles are tracked separately as
    ``unknown_weather_miles`` and excluded from the average rather than being
    optimistically scored as Low.
    """
    if len(checkpoints) != len(levels):
        raise ValueError("checkpoints and levels must be the same length")

    weights = attribute_miles(checkpoints, total_miles)
    miles_by_level = {lv.label: 0.0 for lv in Level}
    counts = {lv.label: 0 for lv in Level}
    weighted_sum = 0.0
    scored_miles = 0.0
    unknown_miles = 0.0
    worst = Level.LOW

    for level, miles in zip(levels, weights):
        if level is None:
            unknown_miles += miles
            continue
        miles_by_level[level.label] += miles
        counts[level.label] += 1
        weighted_sum += float(level) * miles
        scored_miles += miles
        worst = max(worst, level)

    average_risk = (weighted_sum / scored_miles) if scored_miles > 0 else 0.0

    return RouteMetrics(
        distance_miles=total_miles,
        duration_hours=duration_hours,
        miles_by_level=miles_by_level,
        average_risk=average_risk,
        worst_level=worst,
        checkpoints_by_level=counts,
        scored_miles=scored_miles,
        unknown_weather_miles=unknown_miles,
    )


def rank_routes(metrics: Sequence[RouteMetrics]) -> list[int]:
    """Indices of ``metrics`` ordered best-first by the brief's preference list."""
    return sorted(range(len(metrics)), key=lambda i: metrics[i].ranking_key())


def explain_choice(
    winner: RouteMetrics,
    runner_up: Optional[RouteMetrics],
) -> str:
    """Plain-English reason the winner beat the next-best route."""
    if runner_up is None:
        return "Only one route option was available."

    comparisons = (
        ("no_travel_miles", "no-travel", "mi", 0.1),
        ("severe_miles", "severe", "mi", 0.1),
        ("high_miles", "high-risk", "mi", 0.1),
        ("average_risk", "average risk", "", 0.005),
        ("duration_hours", "travel time", "h", 0.01),
    )
    for attr, name, unit, tol in comparisons:
        w = getattr(winner, attr)
        r = getattr(runner_up, attr)
        if abs(w - r) > tol:
            better = "fewer" if unit == "mi" else "lower"
            if attr == "duration_hours":
                return f"{w:.1f}h vs {r:.1f}h travel time, with risk otherwise tied."
            if attr == "average_risk":
                return f"{better} {name} ({w:.2f} vs {r:.2f}), with severe and high miles tied."
            return f"{w:.0f} {name} miles vs {r:.0f} on the next-best route."

    return "Tied with the next-best route on every criterion; kept the first option."
