"""End-to-end API tests with the third-party providers stubbed out.

The providers are replaced so these tests are deterministic and offline: the
point is to prove the planner wires geocoding, routing, sampling, risk and
ranking together correctly, not to re-test OSRM or Open-Meteo.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from django.test import SimpleTestCase

from routing.geo import polyline_segment_miles
from routing.providers.base import NotFound
from routing.providers.geocoding import Place
from routing.providers.routing_osrm import RouteCandidate
from routing.providers.weather import WeatherSample

DEPART = datetime(2026, 11, 18, 8, 0, tzinfo=timezone.utc)

# Two corridors leaving the same origin for the same destination: a direct one
# through longitude -100, and a detour that swings east to -95.
DIRECT = [(-100.0, 35.0 + i * 0.2) for i in range(16)]
DETOUR = [(-100.0, 35.0)] + [(-95.0, 35.5 + i * 0.2) for i in range(14)] + [(-100.0, 38.0)]

ORIGIN = Place(query="Origin", label="Origin, TX", lat=35.0, lon=-100.0)
DESTINATION = Place(query="Destination", label="Destination, NE", lat=38.0, lon=-100.0)


def candidate(coords, hours, source):
    segment_miles = polyline_segment_miles(coords)
    total_seconds = hours * 3600.0
    total_miles = sum(segment_miles) or 1.0
    return RouteCandidate(
        coords=list(coords),
        distance_miles=total_miles,
        duration_seconds=total_seconds,
        segment_miles=segment_miles,
        segment_seconds=[total_seconds * (m / total_miles) for m in segment_miles],
        source=source,
    )


class StubGrid:
    """Duck-typed stand-in for :class:`routing.providers.weather.WeatherGrid`.

    A fixed storm box sits mid-corridor around (-100, 36-37). The direct route
    drives straight through it; the eastern detour at -95 misses it. Both share
    their origin and destination, and both are outside the box, so a ranking
    difference can only come from the storm.
    """

    STORM_LON = -100.0
    STORM_LAT_RANGE = (35.9, 37.1)

    def __init__(self, hours=96):
        self.start = DEPART.replace(hour=0)
        self.hours = hours
        self.point_count = 0

    def _sample(self, point, when):
        lon, lat = point
        in_storm = (
            abs(lon - self.STORM_LON) < 1.0
            and self.STORM_LAT_RANGE[0] <= lat <= self.STORM_LAT_RANGE[1]
        )
        return WeatherSample(
            time=when,
            wind_mph=48.0 if in_storm else 8.0,
            gust_mph=60.0 if in_storm else 14.0,
            rain_in_hr=0.0,
            snow_in_hr=1.5 if in_storm else 0.0,
            precipitation_in_hr=1.5 if in_storm else 0.0,
            temperature_c=-4.0,
            weather_code=75 if in_storm else 0,
        )

    def at(self, point, when):
        return self._sample(point, when)

    def series_for(self, point):
        return self

    def index_for(self, when):
        return int((when - self.start).total_seconds() // 3600)

    def at_index(self, index):
        return None

    def at_hour_offset(self, point, offset):
        return self._sample(point, self.start + timedelta(hours=offset))


class PlanApiTests(SimpleTestCase):
    maxDiff = None

    def setUp(self):
        self.payload = {
            "origin": "Origin, TX",
            "destination": "Destination, NE",
            "depart_at": "2026-11-18T08:00:00Z",
            "load_lb": 42_000,
            "interval_miles": 25,
        }
        self.candidates = [
            candidate(DIRECT, 4.0, "fastest"),
            candidate(DETOUR, 7.0, "detour north/west"),
        ]

    def plan(self, payload=None, candidates=None, grid=None):
        with patch("routing.services.geocode_one", side_effect=[ORIGIN, DESTINATION]), patch(
            "routing.services.route_options", return_value=candidates or self.candidates
        ), patch("routing.services.fetch_grid", return_value=grid or StubGrid()):
            return self.client.post(
                "/api/plan",
                data=payload or self.payload,
                content_type="application/json",
            )

    def test_plan_returns_every_route_with_metrics(self):
        response = self.plan()
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["routes"]), 2)
        for route in body["routes"]:
            self.assertIn("metrics", route)
            self.assertIn("checkpoints", route)
            self.assertIn("geometry", route)
            self.assertIn("rank", route)
            self.assertTrue(route["checkpoints"])

    def test_the_clear_detour_is_recommended_over_the_faster_blizzard(self):
        """The brief ranks severe miles above travel time, so the slow route wins.

        Uses a 10,000 lb load so the storm classifies as Severe rather than No
        Travel, which keeps this test on the severe-vs-time criterion.
        """
        body = self.plan(payload=dict(self.payload, load_lb=10_000)).json()
        recommended = next(r for r in body["routes"] if r["recommended"])
        self.assertEqual(recommended["source"], "detour north/west")
        self.assertEqual(recommended["metrics"]["miles_by_level"]["severe"], 0.0)
        self.assertGreater(recommended["metrics"]["duration_hours"], 6.0)
        self.assertIn("severe", body["recommendation"]["reason"])

    def test_a_blocked_route_loses_on_no_travel_miles_first(self):
        """With a heavy load the storm is impassable, and that decides it."""
        body = self.plan().json()
        recommended = next(r for r in body["routes"] if r["recommended"])
        self.assertEqual(recommended["source"], "detour north/west")
        self.assertTrue(recommended["metrics"]["travel_advised"])
        self.assertIn("no-travel", body["recommendation"]["reason"])

    def test_load_escalation_reaches_the_checkpoints(self):
        """48 mph wind with a 42,000 lb load is No Travel, not merely Severe."""
        body = self.plan().json()
        blizzard = next(r for r in body["routes"] if r["source"] == "fastest")
        levels = {cp["risk"]["level"] for cp in blizzard["checkpoints"] if cp["risk"]}
        self.assertIn("no_travel", levels)
        self.assertFalse(blizzard["metrics"]["travel_advised"])

    def test_a_light_load_in_the_same_wind_is_only_severe(self):
        light = dict(self.payload, load_lb=10_000)
        body = self.plan(payload=light).json()
        blizzard = next(r for r in body["routes"] if r["source"] == "fastest")
        levels = {cp["risk"]["level"] for cp in blizzard["checkpoints"] if cp["risk"]}
        self.assertNotIn("no_travel", levels)
        self.assertIn("severe", levels)

    def test_ranking_is_consistent_with_the_recommendation(self):
        body = self.plan().json()
        ranking = body["recommendation"]["ranking"]
        self.assertEqual(ranking[0], body["recommendation"]["route_id"])
        by_rank = sorted(body["routes"], key=lambda r: r["rank"])
        self.assertEqual([r["id"] for r in by_rank], ranking)

    def test_checkpoint_etas_start_at_departure_and_increase(self):
        body = self.plan().json()
        route = body["routes"][0]
        etas = [cp["eta"] for cp in route["checkpoints"]]
        self.assertEqual(etas[0], "2026-11-18T08:00:00+00:00")
        self.assertEqual(etas, sorted(etas))

    def test_attributed_miles_sum_to_the_route_distance(self):
        body = self.plan().json()
        for route in body["routes"]:
            by_level = route["metrics"]["miles_by_level"]
            total = sum(by_level.values()) + route["metrics"]["unknown_weather_miles"]
            self.assertAlmostEqual(total, route["metrics"]["distance_miles"], delta=0.3)

    def test_geometry_is_decimated_for_transport(self):
        dense = [(-100.0, 35.0 + i * 0.001) for i in range(3_000)]
        body = self.plan(candidates=[candidate(dense, 5.0, "fastest")]).json()
        self.assertLessEqual(len(body["routes"][0]["geometry"]), 700)
        # Both endpoints must survive decimation.
        self.assertAlmostEqual(body["routes"][0]["geometry"][0][0], 35.0, places=3)

    def test_unknown_location_is_a_client_error_not_a_bad_gateway(self):
        with patch(
            "routing.services.geocode_one",
            side_effect=NotFound("Could not find a location.", provider="geocoder"),
        ):
            response = self.client.post(
                "/api/plan", data=self.payload, content_type="application/json"
            )
        self.assertEqual(response.status_code, 422)
        self.assertIn("error", response.json())

    def test_identical_endpoints_are_rejected_before_any_api_call(self):
        response = self.client.post(
            "/api/plan",
            data=dict(self.payload, destination="origin, tx"),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_invalid_interval_is_rejected(self):
        response = self.client.post(
            "/api/plan",
            data=dict(self.payload, interval_miles=33),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_naive_departure_is_treated_as_utc(self):
        body = self.plan(payload=dict(self.payload, depart_at="2026-11-18T08:00:00")).json()
        self.assertEqual(body["request"]["depart_at"], "2026-11-18T08:00:00+00:00")


class HeatmapApiTests(SimpleTestCase):
    def setUp(self):
        self.candidates = [candidate(DIRECT, 4.0, "fastest")]

    def make_plan(self):
        with patch("routing.services.geocode_one", side_effect=[ORIGIN, DESTINATION]), patch(
            "routing.services.route_options", return_value=self.candidates
        ), patch("routing.services.fetch_grid", return_value=StubGrid()):
            response = self.client.post(
                "/api/plan",
                data={
                    "origin": "Origin, TX",
                    "destination": "Destination, NE",
                    "depart_at": "2026-11-18T08:00:00Z",
                    "load_lb": 42_000,
                    "interval_miles": 25,
                },
                content_type="application/json",
            )
        return response.json()["plan_id"]

    def test_heatmap_returns_every_hour_in_one_response(self):
        plan_id = self.make_plan()
        with patch("routing.services.fetch_grid", return_value=StubGrid()):
            response = self.client.get("/api/heatmap", {"plan_id": plan_id, "hours": 48})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["hours"], 48)
        self.assertEqual(len(body["timeline"]), 49)
        self.assertTrue(body["points"])
        for point in body["points"]:
            self.assertEqual(len(point["risk"]), 49)
            self.assertEqual(len(point["wind_mph"]), 49)

    def test_heatmap_anchors_on_the_departure_hour(self):
        plan_id = self.make_plan()
        with patch("routing.services.fetch_grid", return_value=StubGrid()):
            body = self.client.get("/api/heatmap", {"plan_id": plan_id}).json()
        self.assertEqual(body["anchor"], "2026-11-18T08:00:00+00:00")
        self.assertEqual(body["timeline"][0], "2026-11-18T08:00:00+00:00")

    def test_heatmap_applies_the_load_rules_from_the_plan(self):
        plan_id = self.make_plan()
        with patch("routing.services.fetch_grid", return_value=StubGrid()):
            body = self.client.get("/api/heatmap", {"plan_id": plan_id}).json()
        # 48 mph wind + 42,000 lb load is No Travel (level 4) inside the storm
        # box mid-corridor, while the origin outside it stays Low.
        worst_per_point = [max(p["risk"]) for p in body["points"]]
        self.assertIn(4, worst_per_point)
        self.assertEqual(max(body["points"][0]["risk"]), 0)

    def test_expired_plan_is_reported_clearly(self):
        response = self.client.get("/api/heatmap", {"plan_id": "does-not-exist"})
        self.assertEqual(response.status_code, 422)
        self.assertIn("expired", response.json()["error"]["detail"])

    def test_plan_id_is_required(self):
        self.assertEqual(self.client.get("/api/heatmap").status_code, 400)


class MetaEndpointTests(SimpleTestCase):
    def test_health(self):
        self.assertEqual(self.client.get("/api/health").json(), {"status": "ok"})

    def test_rules_expose_the_thresholds_the_engine_uses(self):
        body = self.client.get("/api/rules").json()
        self.assertEqual(
            [level["name"] for level in body["levels"]],
            ["low", "moderate", "high", "severe", "no_travel"],
        )
        self.assertEqual(body["interval_options_miles"], [10, 25, 50])
        self.assertEqual(len(body["load_rules"]), 3)
        self.assertIn("fewest severe miles", body["recommendation_criteria"])

    def test_service_descriptor(self):
        self.assertEqual(self.client.get("/").status_code, 200)
