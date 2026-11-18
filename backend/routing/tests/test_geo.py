"""Geometry helper tests."""

from django.test import SimpleTestCase

from routing.geo import (
    bbox,
    bearing_degrees,
    cumulative,
    geometry_fingerprint,
    haversine_miles,
    interpolate_series,
    locate_at_distance,
    offset_point,
    polyline_segment_miles,
    similarity,
)

DENVER = (-104.9903, 39.7392)
SALT_LAKE = (-111.8910, 40.7608)


class DistanceTests(SimpleTestCase):
    def test_known_distance(self):
        """Denver to Salt Lake City is ~371 miles as the crow flies."""
        self.assertAlmostEqual(haversine_miles(DENVER, SALT_LAKE), 370.6, delta=1.0)

    def test_zero_distance(self):
        self.assertEqual(haversine_miles(DENVER, DENVER), 0.0)

    def test_one_degree_of_latitude(self):
        self.assertAlmostEqual(haversine_miles((0.0, 0.0), (0.0, 1.0)), 69.1, delta=0.2)


class CumulativeTests(SimpleTestCase):
    def test_prefixes_zero(self):
        self.assertEqual(cumulative([1.0, 2.0, 3.0]), [0.0, 1.0, 3.0, 6.0])

    def test_empty(self):
        self.assertEqual(cumulative([]), [0.0])

    def test_segments_align_with_coords(self):
        coords = [(0.0, 0.0), (0.0, 0.5), (0.0, 1.0)]
        self.assertEqual(len(polyline_segment_miles(coords)), len(coords) - 1)


class LocateTests(SimpleTestCase):
    def setUp(self):
        self.coords = [(0.0, 0.0), (0.0, 0.5), (0.0, 1.0)]
        self.cum = cumulative(polyline_segment_miles(self.coords))

    def test_midpoint(self):
        point, _, _ = locate_at_distance(self.coords, self.cum, self.cum[-1] / 2)
        self.assertAlmostEqual(point[1], 0.5, places=4)

    def test_clamps_beyond_the_end(self):
        point, _, _ = locate_at_distance(self.coords, self.cum, 10_000.0)
        self.assertAlmostEqual(point[1], 1.0, places=4)

    def test_clamps_before_the_start(self):
        point, _, _ = locate_at_distance(self.coords, self.cum, -50.0)
        self.assertAlmostEqual(point[1], 0.0, places=4)

    def test_rejects_empty_geometry(self):
        with self.assertRaises(ValueError):
            locate_at_distance([], [0.0], 1.0)


class InterpolateSeriesTests(SimpleTestCase):
    def test_linear_within_a_segment(self):
        self.assertEqual(interpolate_series([0, 10, 20], [0, 100, 150], 15), 125.0)

    def test_exact_node(self):
        self.assertEqual(interpolate_series([0, 10, 20], [0, 100, 150], 10), 100.0)

    def test_clamped_at_both_ends(self):
        self.assertEqual(interpolate_series([0, 10], [0, 100], -5), 0.0)
        self.assertEqual(interpolate_series([0, 10], [0, 100], 99), 100.0)

    def test_zero_length_segment_does_not_divide_by_zero(self):
        """A duplicated distance resolves to the later value, never earlier.

        Two nodes at the same mile marker mean time passed without distance
        (a junction, a waiting node). Taking the post-jump value keeps ETAs
        conservative - the alternative would quietly under-estimate arrival.
        """
        self.assertEqual(interpolate_series([0, 0, 10], [0, 5, 50], 0), 5.0)
        self.assertEqual(interpolate_series([0, 0, 10], [0, 5, 50], 5), 27.5)


class BearingAndOffsetTests(SimpleTestCase):
    def test_due_north(self):
        self.assertAlmostEqual(bearing_degrees((0.0, 0.0), (0.0, 1.0)), 0.0, places=3)

    def test_due_east(self):
        self.assertAlmostEqual(bearing_degrees((0.0, 0.0), (1.0, 0.0)), 90.0, places=3)

    def test_offset_lands_at_the_requested_distance(self):
        moved = offset_point(DENVER, 90.0, 100.0)
        self.assertAlmostEqual(haversine_miles(DENVER, moved), 100.0, delta=0.5)

    def test_offset_respects_the_bearing(self):
        moved = offset_point((0.0, 0.0), 0.0, 69.1)
        self.assertAlmostEqual(moved[1], 1.0, delta=0.02)


class FingerprintTests(SimpleTestCase):
    def test_identical_routes_are_identical(self):
        coords = [(0.0, i / 10) for i in range(10)]
        self.assertEqual(similarity(geometry_fingerprint(coords), geometry_fingerprint(coords)), 1.0)

    def test_disjoint_routes_do_not_overlap(self):
        a = geometry_fingerprint([(0.0, i / 10) for i in range(10)])
        b = geometry_fingerprint([(50.0, i / 10) for i in range(10)])
        self.assertEqual(similarity(a, b), 0.0)

    def test_empty_fingerprint_is_safe(self):
        self.assertEqual(similarity(frozenset(), geometry_fingerprint([(0.0, 0.0)])), 0.0)

    def test_bbox(self):
        self.assertEqual(
            bbox([(-1.0, 2.0), (3.0, -4.0)]), (-1.0, -4.0, 3.0, 2.0)
        )
