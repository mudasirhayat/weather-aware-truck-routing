"""Mile attribution and route recommendation tests."""

from datetime import datetime, timezone

from django.test import SimpleTestCase

from routing.risk import Level
from routing.sampling import Checkpoint
from routing.scoring import (
    attribute_miles,
    explain_choice,
    rank_routes,
    summarize_route,
)

EPOCH = datetime(2026, 11, 18, 8, 0, tzinfo=timezone.utc)


def checkpoints_at(distances):
    return [
        Checkpoint(
            index=i, lon=0.0, lat=0.0, distance_miles=d, elapsed_seconds=0.0, eta=EPOCH
        )
        for i, d in enumerate(distances)
    ]


class AttributionTests(SimpleTestCase):
    def test_attributed_miles_sum_to_route_length(self):
        checkpoints = checkpoints_at([0, 25, 50, 75, 100])
        weights = attribute_miles(checkpoints, 100.0)
        self.assertAlmostEqual(sum(weights), 100.0)

    def test_endpoints_own_half_intervals(self):
        """Origin and destination each cover half an interval, not a full one."""
        weights = attribute_miles(checkpoints_at([0, 25, 50, 75, 100]), 100.0)
        self.assertEqual(weights, [12.5, 25.0, 25.0, 25.0, 12.5])

    def test_single_checkpoint_owns_everything(self):
        self.assertEqual(attribute_miles(checkpoints_at([0]), 40.0), [40.0])

    def test_no_checkpoints(self):
        self.assertEqual(attribute_miles([], 40.0), [])


class SummaryTests(SimpleTestCase):
    def test_severe_miles_are_a_distance_not_a_count(self):
        metrics = summarize_route(
            checkpoints_at([0, 25, 50, 75, 100]),
            [Level.LOW, Level.LOW, Level.SEVERE, Level.HIGH, Level.LOW],
            100.0,
            2.0,
        )
        self.assertAlmostEqual(metrics.severe_miles, 25.0)
        self.assertAlmostEqual(metrics.high_miles, 25.0)
        self.assertEqual(metrics.worst_level, Level.SEVERE)

    def test_average_risk_is_distance_weighted(self):
        metrics = summarize_route(
            checkpoints_at([0, 50, 100]),
            [Level.LOW, Level.SEVERE, Level.LOW],
            100.0,
            2.0,
        )
        # Severe covers the middle 50 miles: (3 * 50) / 100 = 1.5
        self.assertAlmostEqual(metrics.average_risk, 1.5)

    def test_missing_forecasts_are_excluded_not_assumed_safe(self):
        metrics = summarize_route(
            checkpoints_at([0, 25, 50, 75, 100]),
            [Level.LOW, None, None, Level.HIGH, Level.LOW],
            100.0,
            2.0,
        )
        self.assertAlmostEqual(metrics.unknown_weather_miles, 50.0)
        self.assertAlmostEqual(metrics.scored_miles, 50.0)
        self.assertEqual(metrics.miles_by_level["low"], 25.0)

    def test_no_travel_clears_the_advised_flag(self):
        metrics = summarize_route(
            checkpoints_at([0, 50, 100]),
            [Level.LOW, Level.NO_TRAVEL, Level.LOW],
            100.0,
            2.0,
        )
        self.assertFalse(metrics.travel_advised)


class RankingTests(SimpleTestCase):
    def setUp(self):
        self.cps = checkpoints_at([0, 25, 50, 75, 100])

    def route(self, levels, hours):
        return summarize_route(self.cps, levels, 100.0, hours)

    def test_fewest_severe_miles_wins_over_speed(self):
        clean_but_slow = self.route([Level.LOW] * 5, 9.0)
        fast_but_severe = self.route([Level.SEVERE] + [Level.LOW] * 4, 2.0)
        self.assertEqual(rank_routes([fast_but_severe, clean_but_slow]), [1, 0])

    def test_high_miles_break_a_severe_tie(self):
        a = self.route([Level.SEVERE, Level.HIGH, Level.LOW, Level.LOW, Level.LOW], 5.0)
        b = self.route([Level.SEVERE, Level.LOW, Level.LOW, Level.LOW, Level.LOW], 5.0)
        self.assertEqual(rank_routes([a, b]), [1, 0])

    def test_average_risk_breaks_a_high_tie(self):
        a = self.route([Level.MODERATE] * 5, 5.0)
        b = self.route([Level.LOW] * 5, 5.0)
        self.assertEqual(rank_routes([a, b]), [1, 0])

    def test_travel_time_is_the_final_tie_break(self):
        slow = self.route([Level.LOW] * 5, 9.0)
        quick = self.route([Level.LOW] * 5, 6.0)
        self.assertEqual(rank_routes([slow, quick]), [1, 0])

    def test_no_travel_outranks_every_other_criterion(self):
        blocked_but_perfect = self.route([Level.NO_TRAVEL] + [Level.LOW] * 4, 1.0)
        severe_but_open = self.route([Level.SEVERE] * 5, 20.0)
        self.assertEqual(rank_routes([blocked_but_perfect, severe_but_open]), [1, 0])

    def test_explanation_names_the_deciding_criterion(self):
        clean = self.route([Level.LOW] * 5, 9.0)
        severe = self.route([Level.SEVERE] + [Level.LOW] * 4, 2.0)
        self.assertIn("severe", explain_choice(clean, severe))
        slow = self.route([Level.LOW] * 5, 9.0)
        quick = self.route([Level.LOW] * 5, 6.0)
        self.assertIn("travel time", explain_choice(quick, slow))

    def test_single_route_explanation(self):
        self.assertIn("one route", explain_choice(self.route([Level.LOW] * 5, 5.0), None))
