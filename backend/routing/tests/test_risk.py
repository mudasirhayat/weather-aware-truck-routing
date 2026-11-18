"""Threshold tests taken directly from the brief's tables."""

from django.test import SimpleTestCase

from routing.risk import (
    Level,
    assess,
    classify_rain,
    classify_snow,
    classify_wind,
    load_adjustment,
)


class WindThresholdTests(SimpleTestCase):
    def test_band_edges(self):
        cases = [
            (0.0, Level.LOW),
            (24.9, Level.LOW),
            (25.0, Level.MODERATE),
            (34.0, Level.MODERATE),
            (34.9, Level.MODERATE),
            (35.0, Level.HIGH),
            (44.9, Level.HIGH),
            (45.0, Level.SEVERE),
            (54.9, Level.SEVERE),
            (55.0, Level.NO_TRAVEL),
            (120.0, Level.NO_TRAVEL),
        ]
        for mph, expected in cases:
            with self.subTest(mph=mph):
                self.assertEqual(classify_wind(mph), expected)


class RainThresholdTests(SimpleTestCase):
    def test_band_edges(self):
        cases = [
            (0.0, Level.LOW),
            (0.099, Level.LOW),
            (0.10, Level.MODERATE),
            (0.25, Level.MODERATE),
            (0.251, Level.HIGH),
            (0.50, Level.HIGH),
            (0.501, Level.SEVERE),
            (1.00, Level.SEVERE),
            (1.001, Level.NO_TRAVEL),
        ]
        for rate, expected in cases:
            with self.subTest(rate=rate):
                self.assertEqual(classify_rain(rate), expected)


class SnowThresholdTests(SimpleTestCase):
    def test_band_edges(self):
        cases = [
            (0.0, Level.LOW),
            (0.49, Level.LOW),
            (0.5, Level.MODERATE),
            (1.0, Level.MODERATE),
            (1.01, Level.HIGH),
            (2.0, Level.HIGH),
            (2.01, Level.SEVERE),
            (3.0, Level.SEVERE),
            (3.01, Level.NO_TRAVEL),
        ]
        for rate, expected in cases:
            with self.subTest(rate=rate):
                self.assertEqual(classify_snow(rate), expected)


class LoadRuleTests(SimpleTestCase):
    def test_hurricane_wind_stops_any_load(self):
        level, rule = load_adjustment(55.0, 0.0)
        self.assertEqual(level, Level.NO_TRAVEL)
        self.assertIn("any load", rule)

    def test_heavy_load_in_severe_wind_becomes_no_travel(self):
        self.assertEqual(load_adjustment(45.0, 30_001.0)[0], Level.NO_TRAVEL)
        self.assertEqual(load_adjustment(54.9, 50_000.0)[0], Level.NO_TRAVEL)

    def test_load_at_threshold_does_not_trigger(self):
        """The rule says ">30,000 lb", so exactly 30,000 is not escalated."""
        self.assertEqual(load_adjustment(50.0, 30_000.0), (Level.LOW, None))
        self.assertEqual(load_adjustment(40.0, 40_000.0), (Level.LOW, None))

    def test_heavy_load_in_high_wind_becomes_severe(self):
        self.assertEqual(load_adjustment(35.0, 40_001.0)[0], Level.SEVERE)
        self.assertEqual(load_adjustment(44.9, 80_000.0)[0], Level.SEVERE)

    def test_load_rules_do_not_apply_below_35_mph(self):
        self.assertEqual(load_adjustment(34.9, 100_000.0), (Level.LOW, None))


class AssessTests(SimpleTestCase):
    def test_worst_condition_wins(self):
        result = assess(wind_mph=10.0, rain_in_hr=0.0, snow_in_hr=2.5, load_lb=1_000.0)
        self.assertEqual(result.level, Level.SEVERE)
        self.assertEqual(result.snow_level, Level.SEVERE)
        self.assertEqual(result.wind_level, Level.LOW)

    def test_load_escalates_high_wind_to_severe(self):
        light = assess(wind_mph=40.0, rain_in_hr=0.0, snow_in_hr=0.0, load_lb=20_000.0)
        heavy = assess(wind_mph=40.0, rain_in_hr=0.0, snow_in_hr=0.0, load_lb=45_000.0)
        self.assertEqual(light.level, Level.HIGH)
        self.assertEqual(heavy.level, Level.SEVERE)
        self.assertTrue(heavy.escalated_by_load)
        self.assertFalse(light.escalated_by_load)

    def test_load_never_lowers_a_weather_level(self):
        """A light load must not rescue a route from severe snow."""
        result = assess(wind_mph=5.0, rain_in_hr=0.0, snow_in_hr=3.5, load_lb=0.0)
        self.assertEqual(result.level, Level.NO_TRAVEL)

    def test_drivers_name_the_cause(self):
        result = assess(wind_mph=46.0, rain_in_hr=0.0, snow_in_hr=0.0, load_lb=35_000.0)
        self.assertEqual(result.level, Level.NO_TRAVEL)
        self.assertTrue(any("wind" in d for d in result.drivers))
        self.assertTrue(any("no travel" in d for d in result.drivers))

    def test_calm_weather_is_low(self):
        result = assess(wind_mph=3.0, rain_in_hr=0.0, snow_in_hr=0.0, load_lb=79_000.0)
        self.assertEqual(result.level, Level.LOW)
        self.assertEqual(result.drivers, ())
