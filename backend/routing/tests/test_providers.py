"""Provider adapter tests: OSRM parsing/de-duplication and weather indexing."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from django.test import SimpleTestCase

from routing.providers import routing_osrm
from routing.providers.base import ProviderError
from routing.providers.geocoding import geocode
from routing.providers.weather import GRID_DECIMALS, HourlySeries, WeatherGrid

ORIGIN = (-100.0, 35.0)
DESTINATION = (-100.0, 38.0)


def osrm_route(coords, distance_m, duration_s, legs=1):
    """Build an OSRM-shaped route with per-leg annotations."""
    segments = len(coords) - 1
    per_leg = segments // legs
    leg_objects = []
    consumed = 0
    for leg in range(legs):
        count = per_leg if leg < legs - 1 else segments - consumed
        leg_objects.append(
            {
                "distance": distance_m * (count / segments),
                "duration": duration_s * (count / segments),
                "annotation": {
                    "distance": [distance_m / segments] * count,
                    "duration": [duration_s / segments] * count,
                },
            }
        )
        consumed += count
    return {
        "distance": distance_m,
        "duration": duration_s,
        "geometry": {"coordinates": [list(c) for c in coords]},
        "legs": leg_objects,
    }


class CandidateParsingTests(SimpleTestCase):
    def test_annotations_are_used_when_aligned(self):
        coords = [(-100.0, 35.0 + i * 0.1) for i in range(11)]
        candidate = routing_osrm._candidate_from_route(
            osrm_route(coords, 160_934.4, 7_200.0), "fastest"
        )
        self.assertEqual(len(candidate.segment_seconds), len(coords) - 1)
        self.assertTrue(candidate.has_segment_timing)
        self.assertAlmostEqual(candidate.distance_miles, 100.0, places=2)
        self.assertAlmostEqual(candidate.duration_hours, 2.0, places=3)

    def test_multi_leg_annotations_concatenate_to_the_overview(self):
        """A via-point route has two legs that must line up with one polyline."""
        coords = [(-100.0, 35.0 + i * 0.1) for i in range(21)]
        candidate = routing_osrm._candidate_from_route(
            osrm_route(coords, 321_868.8, 14_400.0, legs=2), "detour north/west"
        )
        self.assertTrue(candidate.has_segment_timing)
        self.assertEqual(len(candidate.segment_miles), len(coords) - 1)

    def test_falls_back_to_geometry_when_annotations_are_missing(self):
        coords = [(-100.0, 35.0 + i * 0.1) for i in range(11)]
        route = osrm_route(coords, 160_934.4, 7_200.0)
        route["legs"] = [{"distance": 160_934.4, "duration": 7_200.0}]
        candidate = routing_osrm._candidate_from_route(route, "fastest")
        self.assertEqual(len(candidate.segment_seconds), len(coords) - 1)
        self.assertAlmostEqual(sum(candidate.segment_seconds), 7_200.0, places=1)

    def test_degenerate_geometry_is_rejected(self):
        route = osrm_route([(-100.0, 35.0), (-100.0, 35.1)], 1_000.0, 60.0)
        route["geometry"]["coordinates"] = [[-100.0, 35.0]]
        self.assertIsNone(routing_osrm._candidate_from_route(route, "fastest"))


class RouteOptionTests(SimpleTestCase):
    def test_duplicate_alternatives_are_dropped(self):
        """OSRM sometimes returns near-identical alternatives; we show one."""
        coords = [(-100.0, 35.0 + i * 0.05) for i in range(61)]
        nudged = [(lon + 0.0001, lat) for lon, lat in coords]
        with patch.object(
            routing_osrm,
            "_fetch",
            return_value=[
                osrm_route(coords, 321_868.8, 14_400.0),
                osrm_route(nudged, 322_000.0, 14_500.0),
            ],
        ) as fetch:
            routes = routing_osrm.route_options(ORIGIN, DESTINATION, want=3)
        self.assertEqual(len(routes), 1)
        # Having only one distinct road, it then tries via-point detours.
        self.assertGreater(fetch.call_count, 1)

    def test_distinct_alternatives_are_kept(self):
        direct = [(-100.0, 35.0 + i * 0.05) for i in range(61)]
        east = [(-95.0, 35.0 + i * 0.05) for i in range(61)]
        west = [(-105.0, 35.0 + i * 0.05) for i in range(61)]
        with patch.object(
            routing_osrm,
            "_fetch",
            return_value=[
                osrm_route(direct, 321_868.8, 14_400.0),
                osrm_route(east, 350_000.0, 16_000.0),
                osrm_route(west, 360_000.0, 17_000.0),
            ],
        ):
            routes = routing_osrm.route_options(ORIGIN, DESTINATION, want=3)
        self.assertEqual(len(routes), 3)
        self.assertEqual(routes[0].source, "fastest")
        self.assertEqual(routes[1].source, "alternative")

    def test_via_points_fill_in_missing_alternatives(self):
        direct = [(-100.0, 35.0 + i * 0.05) for i in range(61)]
        detour = [(-97.0, 35.0 + i * 0.05) for i in range(61)]

        calls = {"n": 0}

        def fake_fetch(points, alternatives):
            calls["n"] += 1
            if len(points) == 2:
                return [osrm_route(direct, 321_868.8, 14_400.0)]
            return [osrm_route(detour, 400_000.0, 19_000.0)]

        with patch.object(routing_osrm, "_fetch", side_effect=fake_fetch):
            routes = routing_osrm.route_options(ORIGIN, DESTINATION, want=3)

        self.assertGreaterEqual(len(routes), 2)
        self.assertTrue(any(r.source.startswith("detour") for r in routes))

    def test_absurd_detours_are_rejected(self):
        direct = [(-100.0, 35.0 + i * 0.05) for i in range(61)]
        silly = [(-80.0, 35.0 + i * 0.05) for i in range(61)]

        def fake_fetch(points, alternatives):
            if len(points) == 2:
                return [osrm_route(direct, 321_868.8, 14_400.0)]
            return [osrm_route(silly, 321_868.8 * 3, 50_000.0)]  # 3x the distance

        with patch.object(routing_osrm, "_fetch", side_effect=fake_fetch):
            routes = routing_osrm.route_options(ORIGIN, DESTINATION, want=3)
        self.assertEqual(len(routes), 1)

    def test_no_route_raises(self):
        with patch.object(routing_osrm, "_fetch", return_value=[]):
            with self.assertRaises(ProviderError):
                routing_osrm.route_options(ORIGIN, DESTINATION, want=3)

    def test_via_point_failures_do_not_sink_the_whole_plan(self):
        direct = [(-100.0, 35.0 + i * 0.05) for i in range(61)]

        def fake_fetch(points, alternatives):
            if len(points) == 2:
                return [osrm_route(direct, 321_868.8, 14_400.0)]
            raise ProviderError("via failed", provider="OSRM routing")

        with patch.object(routing_osrm, "_fetch", side_effect=fake_fetch):
            routes = routing_osrm.route_options(ORIGIN, DESTINATION, want=3)
        self.assertEqual(len(routes), 1)


class WeatherGridTests(SimpleTestCase):
    def setUp(self):
        self.start = datetime(2026, 11, 17, 0, 0, tzinfo=timezone.utc)
        self.series = HourlySeries(
            lat=35.0,
            lon=-100.0,
            start=self.start,
            hours=48,
            data={
                "wind_speed_10m": [float(h) for h in range(48)],
                "wind_gusts_10m": [float(h) * 1.4 for h in range(48)],
                "rain": [0.0] * 48,
                "snowfall": [0.0] * 48,
                "precipitation": [0.0] * 48,
                "temperature_2m": [-2.0] * 48,
                "weather_code": [0] * 48,
            },
        )
        self.grid = WeatherGrid({WeatherGrid.cell((-100.0, 35.0)): self.series}, self.start, 48)

    def test_hour_index_floors_to_the_containing_hour(self):
        self.assertEqual(self.series.index_for(self.start + timedelta(minutes=59)), 0)
        self.assertEqual(self.series.index_for(self.start + timedelta(minutes=61)), 1)

    def test_lookup_returns_that_hours_values(self):
        sample = self.grid.at((-100.0, 35.0), self.start + timedelta(hours=10, minutes=30))
        self.assertEqual(sample.wind_mph, 10.0)

    def test_out_of_coverage_returns_none(self):
        self.assertIsNone(self.grid.at((-100.0, 35.0), self.start - timedelta(hours=1)))
        self.assertIsNone(self.grid.at((-100.0, 35.0), self.start + timedelta(hours=48)))

    def test_naive_datetimes_are_treated_as_utc(self):
        naive = (self.start + timedelta(hours=5)).replace(tzinfo=None)
        self.assertEqual(self.series.at(naive).wind_mph, 5.0)

    def test_nearby_points_share_a_grid_cell(self):
        """Dedup is what keeps a 100-checkpoint plan to one weather call."""
        self.assertEqual(
            WeatherGrid.cell((-100.0001, 35.0001)),
            WeatherGrid.cell((-100.0, 35.0)),
        )
        self.assertIsNotNone(self.grid.at((-100.002, 35.002), self.start))

    def test_distant_points_do_not(self):
        self.assertNotEqual(
            WeatherGrid.cell((-100.0, 35.0)), WeatherGrid.cell((-100.5, 35.0))
        )
        self.assertIsNone(self.grid.at((-100.5, 35.0), self.start))

    def test_nulls_in_the_forecast_read_as_zero(self):
        self.series.data["rain"] = [None] * 48
        self.assertEqual(self.series.at(self.start).rain_in_hr, 0.0)

    def test_grid_decimals_is_about_a_kilometre(self):
        self.assertEqual(GRID_DECIMALS, 2)


class GeocodeTests(SimpleTestCase):
    def test_literal_coordinates_skip_the_network(self):
        with patch("routing.providers.geocoding.get_json") as get_json:
            places = geocode("39.7392, -104.9903")
        get_json.assert_not_called()
        self.assertEqual(places[0].lat, 39.7392)
        self.assertEqual(places[0].lon, -104.9903)

    def test_out_of_range_coordinates_fall_through_to_the_geocoder(self):
        with patch(
            "routing.providers.geocoding.get_json",
            return_value=[{"lat": "1.0", "lon": "2.0", "display_name": "Somewhere"}],
        ) as get_json:
            places = geocode("999, 999")
        get_json.assert_called_once()
        self.assertEqual(places[0].label, "Somewhere")

    def test_empty_query_is_rejected(self):
        with self.assertRaises(ProviderError):
            geocode("   ")

    def test_no_results_is_reported_as_a_client_error(self):
        with patch("routing.providers.geocoding.get_json", return_value=[]):
            with self.assertRaises(ProviderError) as ctx:
                geocode("nowhere at all")
        self.assertEqual(ctx.exception.status_code, 422)

    def test_malformed_entries_are_skipped(self):
        with patch(
            "routing.providers.geocoding.get_json",
            return_value=[
                {"display_name": "broken"},
                {"lat": "5.0", "lon": "6.0", "display_name": "good"},
            ],
        ):
            places = geocode("mixed", limit=2)
        self.assertEqual(len(places), 1)
        self.assertEqual(places[0].label, "good")
