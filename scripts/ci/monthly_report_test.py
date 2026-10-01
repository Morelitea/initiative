"""Tests for monthly_report.py. Run: python3 scripts/ci/monthly_report_test.py"""

import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import monthly_report  # noqa: E402
from monthly_report import Release, Run  # noqa: E402

T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)


def at(hours: float) -> datetime:
    return T0 + timedelta(hours=hours)


class ReleasesTest(unittest.TestCase):
    def test_a_patch_soon_after_or_a_regression_is_a_fix(self):
        releases = [
            Release("v0.71.0", at(0)),
            Release("v0.71.1", at(8)),  # the fix for 0.71.0
            Release("v0.72.0", at(100)),
            Release("v0.72.1", at(300)),  # outside the window: not a fix
            Release("v0.73.0", at(400)),  # another minor: not a patch of 0.72
        ]

        fixes = monthly_report.needed_a_fix(releases, regressions={"0.72.1"})

        self.assertEqual(
            fixes,
            {
                "v0.71.0": "v0.71.1 8 h later",
                "v0.72.1": "a regression was reported against it",
            },
        )


class MergeToGreenTest(unittest.TestCase):
    def test_a_push_waits_for_the_next_green_run(self):
        runs = [
            Run(at(0), at(0.5), "success"),
            Run(at(1), at(1.2), "cancelled"),  # replaced by the next push
            Run(at(1.1), at(1.6), "failure"),
            Run(at(2), at(2.5), "success"),
            Run(at(3), at(3.4), None),  # still running: no green after it yet
        ]

        waits = monthly_report.merge_to_green(runs)

        self.assertEqual(
            [wait.total_seconds() / 3600 for wait in waits],
            [0.5, 1.5, 1.4, 0.5],
        )


class MonthTest(unittest.TestCase):
    def test_a_month_is_read_a_week_at_a_time(self):
        start, end = monthly_report.month_bounds("2026-09")
        self.assertEqual(
            monthly_report.weeks(start, end),
            [
                "2026-09-01..2026-09-07",
                "2026-09-08..2026-09-14",
                "2026-09-15..2026-09-21",
                "2026-09-22..2026-09-28",
                "2026-09-29..2026-09-30",
            ],
        )

    def test_the_previous_month_and_its_bounds(self):
        self.assertEqual(monthly_report.previous_month(date(2026, 1, 1)), "2025-12")
        self.assertEqual(
            monthly_report.month_bounds("2026-12"),
            (
                datetime(2026, 12, 1, tzinfo=timezone.utc),
                datetime(2027, 1, 1, tzinfo=timezone.utc),
            ),
        )


if __name__ == "__main__":
    unittest.main()
