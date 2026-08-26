import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from passes import ACTIVE, RECENT, UPCOMING, next_wake_s, select_passes


def make_pass(label, aos, los):
    return {"label": label, "aos": aos, "los": los, "max_el": 30}


class SelectPassesTest(unittest.TestCase):
    def test_states_and_expiry(self):
        recent  = make_pass("REC", 500, 800)
        expired = make_pass("OLD", 100, 200)
        active  = make_pass("ACT", 950, 1100)
        soon    = make_pass("NXT", 1200, 1300)
        selected = select_passes(
            [soon, expired, active, recent], cur=1000,
            max_shown=4, recent_retention_s=300,
        )

        self.assertEqual(
            [(p["label"], state) for p, state in selected],
            [("REC", RECENT), ("ACT", ACTIVE), ("NXT", UPCOMING)],
        )

    def test_limits_rows_and_sorts_by_aos(self):
        all_passes = [make_pass(f"S{i}", 1000 + i * 100, 1050 + i * 100)
                      for i in range(5)]
        selected = select_passes(
            list(reversed(all_passes)), cur=900,
            max_shown=3, recent_retention_s=300,
        )

        self.assertEqual([p["label"] for p, _ in selected], ["S0", "S1", "S2"])

    def test_overlapping_passes_can_both_be_active(self):
        selected = select_passes(
            [make_pass("A", 900, 1100), make_pass("B", 950, 1200)],
            cur=1000, max_shown=4, recent_retention_s=300,
        )

        self.assertEqual([state for _, state in selected], [ACTIVE, ACTIVE])


class NextWakeTest(unittest.TestCase):
    def test_no_passes_uses_max_sleep(self):
        self.assertEqual(next_wake_s([], 1000, 300, 3600), 3600)

    def test_wakes_at_next_aos(self):
        visible = [(make_pass("A", 1600, 1900), UPCOMING)]

        self.assertEqual(next_wake_s(visible, 1000, 300, 3600), 605)

    def test_wakes_at_earliest_event_across_passes(self):
        visible = [
            (make_pass("A", 900, 1500), ACTIVE),     # LOS in 500s
            (make_pass("B", 1100, 2000), UPCOMING),  # AOS in 100s
        ]

        self.assertEqual(next_wake_s(visible, 1000, 300, 3600), 105)

    def test_wakes_to_drop_expiring_recent_pass(self):
        visible = [(make_pass("A", 500, 900), RECENT)]

        self.assertEqual(next_wake_s(visible, 1000, 300, 3600), 205)

    def test_clamps_to_min_and_max_sleep(self):
        imminent = [(make_pass("A", 1001, 5000), UPCOMING)]
        distant  = [(make_pass("B", 90000, 90500), UPCOMING)]

        self.assertEqual(next_wake_s(imminent, 1000, 300, 3600), 60)
        self.assertEqual(next_wake_s(distant, 1000, 300, 3600), 3600)


if __name__ == "__main__":
    unittest.main()
