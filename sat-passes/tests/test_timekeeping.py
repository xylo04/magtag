import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from timekeeping import (
    parse_time_service_reply,
    unix_to_date,
    unix_to_hhmm,
)


def unix(year, month, day, hour=0, minute=0, second=0):
    return int(datetime(
        year, month, day, hour, minute, second, tzinfo=timezone.utc
    ).timestamp())


class ParseTimeServiceReplyTest(unittest.TestCase):
    def test_parses_unix_time_negative_offset_and_abbreviation(self):
        self.assertEqual(
            parse_time_service_reply("1787676660 -0600 MDT"),
            (1787676660, -21600, "MDT"),
        )

    def test_parses_half_hour_positive_offset(self):
        self.assertEqual(
            parse_time_service_reply("1787676660 +0530 IST"),
            (1787676660, 19800, "IST"),
        )

    def test_allows_missing_abbreviation(self):
        self.assertEqual(
            parse_time_service_reply("1787676660 +0000"),
            (1787676660, 0, "+0000"),
        )

    def test_rejects_malformed_reply(self):
        for reply in (
            "",
            "1787676660",
            "not-a-timestamp +0000 UTC",
            "1787676660 0600 MDT",
            "1787676660 +0060 MDT",
        ):
            with self.subTest(reply=reply):
                with self.assertRaises(ValueError):
                    parse_time_service_reply(reply)


class LocalDateTimeTest(unittest.TestCase):
    def test_negative_offset_crosses_to_previous_year(self):
        timestamp = unix(2026, 1, 1, 5, 30)
        self.assertEqual(unix_to_date(timestamp, -21600), "2025-12-31")
        self.assertEqual(unix_to_hhmm(timestamp, -21600), "23:30")

    def test_positive_offset_crosses_to_next_day(self):
        timestamp = unix(2026, 8, 25, 20, 45)
        self.assertEqual(unix_to_date(timestamp, 19800), "2026-08-26")
        self.assertEqual(unix_to_hhmm(timestamp, 19800), "02:15")

    def test_leap_day(self):
        timestamp = unix(2024, 2, 29, 12, 34)
        self.assertEqual(unix_to_date(timestamp, 0), "2024-02-29")
        self.assertEqual(unix_to_hhmm(timestamp, 0), "12:34")

    def test_unix_epoch_with_negative_offset(self):
        self.assertEqual(unix_to_date(0, -1), "1969-12-31")
        self.assertEqual(unix_to_hhmm(0, -1), "23:59")


if __name__ == "__main__":
    unittest.main()
