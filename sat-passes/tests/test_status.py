import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from status import battery_percent, status_lines


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
