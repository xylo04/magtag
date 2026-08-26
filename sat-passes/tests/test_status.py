import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from status import battery_percent, is_low_battery, status_lines


class BatteryPercentTest(unittest.TestCase):
    def test_scales_between_empty_and_full(self):
        self.assertEqual(battery_percent(3.20), 0)
        self.assertEqual(battery_percent(3.70), 50)
        self.assertEqual(battery_percent(4.20), 100)

    def test_clamps_out_of_range_voltages(self):
        self.assertEqual(battery_percent(2.50), 0)
        self.assertEqual(battery_percent(4.50), 100)

    def test_missing_reading_passes_through(self):
        self.assertIsNone(battery_percent(None))


class IsLowBatteryTest(unittest.TestCase):
    def test_at_or_below_threshold_on_battery(self):
        self.assertTrue(is_low_battery(5, False))
        self.assertTrue(is_low_battery(0, False))

    def test_above_threshold_is_normal(self):
        self.assertFalse(is_low_battery(6, False))

    def test_plugged_in_is_never_low(self):
        self.assertFalse(is_low_battery(2, True))

    def test_unknown_battery_is_never_low(self):
        self.assertFalse(is_low_battery(None, False))

    def test_threshold_is_configurable(self):
        self.assertTrue(is_low_battery(10, False, threshold=10))
        self.assertFalse(is_low_battery(10, False, threshold=9))


class StatusLinesTest(unittest.TestCase):
    def test_lines_with_battery(self):
        self.assertEqual(
            status_lines("14:05", "2026-08-25", 84),
            ["Updated 14:05", "2026-08-25", "Battery 84%"],
        )

    def test_lines_without_battery(self):
        self.assertEqual(
            status_lines("14:05", "2026-08-25", None),
            ["Updated 14:05", "2026-08-25", "Battery unknown"],
        )

    def test_rate_limited_adds_a_line(self):
        self.assertEqual(
            status_lines("14:05", "2026-08-25", 84, rate_limited=True)[-1],
            "N2YO rate limited",
        )


if __name__ == "__main__":
    unittest.main()
