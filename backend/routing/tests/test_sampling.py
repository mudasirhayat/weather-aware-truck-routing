"""Checkpoint sampling and ETA tests."""

from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase

from routing.sampling import (
    MAX_CHECKPOINTS_PER_ROUTE,
    corridor_points,
    effective_interval,
    sample_checkpoints,
)

DEPART = datetime(2026, 11, 18, 8, 0, tzinfo=timezone.utc)

# A due-north line: one degree of latitude is ~69 miles.
NORTH_LINE = [(0.0, i * 0.1) for i in range(11)]


class IntervalTests(SimpleTestCase):
    def test_short_route_keeps_requested_interval(self):
        self.assertEqual(effective_interval(300.0, 25), (25.0, False))

    def test_long_route_is_coarsened_to_a_cap(self):
        interval, coarsened = effective_interval(3_000.0, 10)
        self.assertTrue(coarsened)
        self.assertAlmostEqual(interval, 3_000.0 / MAX_CHECKPOINTS_PER_ROUTE)
        self.assertLessEqual(3_000.0 / interval, MAX_CHECKPOINTS_PER_ROUTE)


class SampleCheckpointTests(SimpleTestCase):
    def test_includes_origin_and_destination(self):
        checkpoints, total, _ = sample_checkpoints(
            NORTH_LINE, DEPART, 25, total_duration_seconds=7_200
        )
        self.assertEqual(checkpoints[0].distance_miles, 0.0)
        self.assertAlmostEqual(checkpoints[-1].distance_miles, round(total, 3), places=2)
        self.assertEqual(checkpoints[0].eta, DEPART)

    def test_spacing_matches_requested_interval(self):
        checkpoints, _, _ = sample_checkpoints(
            NORTH_LINE, DEPART, 25, total_duration_seconds=7_200
        )
        interior = [c.distance_miles for c in checkpoints[:-1]]
        self.assertEqual(interior, [0.0, 25.0, 50.0])

    def test_arrival_matches_route_duration(self):
        checkpoints, _, _ = sample_checkpoints(
            NORTH_LINE, DEPART, 25, total_duration_seconds=7_200
        )
        self.assertEqual(checkpoints[-1].eta, DEPART + timedelta(hours=2))

    def test_etas_increase_monotonically(self):
        checkpoints, _, _ = sample_checkpoints(
            NORTH_LINE, DEPART, 10, total_duration_seconds=7_200
        )
        etas = [c.eta for c in checkpoints]
        self.assertEqual(etas, sorted(etas))

    def test_segment_timing_beats_a_flat_average(self):
        """A slow final segment must push the last ETAs later, not smear evenly."""
        segment_miles = [6.9] * 10
        segment_seconds = [300.0] * 9 + [5_400.0]  # last stretch crawls
        checkpoints, _, _ = sample_checkpoints(
            NORTH_LINE,
            DEPART,
            25,
            segment_miles=segment_miles,
            segment_seconds=segment_seconds,
        )
        # 50 miles in: still on the fast stretch, ~36 min elapsed.
        midway = next(c for c in checkpoints if c.distance_miles == 50.0)
        self.assertLess(midway.elapsed_hours, 0.7)
        # Total duration is 2h15m and must be respected at the destination.
        self.assertAlmostEqual(checkpoints[-1].elapsed_seconds, 8_100.0, places=1)

    def test_rejects_degenerate_geometry(self):
        with self.assertRaises(ValueError):
            sample_checkpoints([(0.0, 0.0)], DEPART, 25, total_duration_seconds=1)

    def test_rejects_misaligned_segment_data(self):
        with self.assertRaises(ValueError):
            sample_checkpoints(NORTH_LINE, DEPART, 25, segment_miles=[1.0, 2.0])

    def test_very_long_route_stays_within_the_checkpoint_cap(self):
        long_line = [(0.0, i * 0.1) for i in range(500)]  # ~3,400 miles
        checkpoints, _, coarsened = sample_checkpoints(
            long_line, DEPART, 10, total_duration_seconds=180_000
        )
        self.assertTrue(coarsened)
        self.assertLessEqual(len(checkpoints), MAX_CHECKPOINTS_PER_ROUTE + 1)


class CorridorPointTests(SimpleTestCase):
    def test_density_targets_the_point_budget(self):
        points = corridor_points(NORTH_LINE, 5.0, 70)
        self.assertGreaterEqual(len(points), 10)
        self.assertLessEqual(len(points), 70)

    def test_minimum_spacing_is_respected_on_short_routes(self):
        short = [(0.0, 0.0), (0.0, 0.1)]  # ~6.9 miles
        points = corridor_points(short, 5.0, 70)
        self.assertEqual(len(points), 2)

    def test_endpoints_are_included(self):
        points = corridor_points(NORTH_LINE, 5.0, 70)
        self.assertEqual(points[0].distance_miles, 0.0)
        self.assertGreater(points[-1].distance_miles, points[0].distance_miles)
