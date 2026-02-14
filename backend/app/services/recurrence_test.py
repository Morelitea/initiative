"""
Unit tests for the recurrence service.

Tests the recurrence calculation logic including:
- Daily, weekly, monthly, yearly frequency calculations
- Time preservation across recurrence calculations
- End conditions (after_occurrences, on_date)
"""

from datetime import datetime, timezone

from app.schemas.task import TaskRecurrence
from app.services.recurrence import get_next_due_date


class TestDailyRecurrence:
    """Tests for daily recurrence calculations."""

    def test_daily_recurrence_preserves_time(self):
        """Verify daily interval preserves time component."""
        base_date = datetime(2026, 1, 20, 17, 30, 45, tzinfo=timezone.utc)
        recurrence = TaskRecurrence(frequency="daily", interval=3)

        next_due = get_next_due_date(base_date, recurrence)

        assert next_due is not None
        assert next_due.date() == datetime(2026, 1, 23).date()
        assert next_due.hour == 17
        assert next_due.minute == 30
        assert next_due.second == 45

    def test_daily_recurrence_interval_one(self):
        """Test daily recurrence with interval of 1."""
        base_date = datetime(2026, 1, 20, 9, 0, 0, tzinfo=timezone.utc)
        recurrence = TaskRecurrence(frequency="daily", interval=1)

        next_due = get_next_due_date(base_date, recurrence)

        assert next_due is not None
        assert next_due.date() == datetime(2026, 1, 21).date()
        assert next_due.hour == 9

    def test_midnight_time_preserved(self):
        """Ensure 00:00 is not treated as 'no time' and is preserved."""
        base_date = datetime(2026, 1, 20, 0, 0, 0, tzinfo=timezone.utc)
        recurrence = TaskRecurrence(frequency="daily", interval=2)

        next_due = get_next_due_date(base_date, recurrence)

        assert next_due is not None
        assert next_due.date() == datetime(2026, 1, 22).date()
        assert next_due.hour == 0
        assert next_due.minute == 0
        assert next_due.second == 0


class TestWeeklyRecurrence:
    """Tests for weekly recurrence calculations."""

    def test_weekly_recurrence_preserves_time(self):
        """Verify weekly interval preserves time component."""
        # Monday, Jan 19, 2026 at 14:15
        base_date = datetime(2026, 1, 19, 14, 15, 0, tzinfo=timezone.utc)
        recurrence = TaskRecurrence(frequency="weekly", interval=1, weekdays=["monday"])

        next_due = get_next_due_date(base_date, recurrence)

        assert next_due is not None
        assert next_due.hour == 14
        assert next_due.minute == 15

    def test_weekly_recurrence_multiple_weekdays(self):
        """Test weekly recurrence with multiple target weekdays."""
        # Tuesday, Jan 20, 2026
        base_date = datetime(2026, 1, 20, 10, 0, 0, tzinfo=timezone.utc)
        recurrence = TaskRecurrence(
            frequency="weekly", interval=1, weekdays=["tuesday", "thursday", "saturday"]
        )

        next_due = get_next_due_date(base_date, recurrence)

        assert next_due is not None
        # Should be Thursday (2 days later - Jan 22)
        assert next_due.date() == datetime(2026, 1, 22).date()
        assert next_due.hour == 10


class TestMonthlyRecurrence:
    """Tests for monthly recurrence calculations."""

    def test_monthly_recurrence_preserves_time(self):
        """Verify monthly interval preserves time component."""
        base_date = datetime(2026, 1, 15, 23, 45, 30, tzinfo=timezone.utc)
        recurrence = TaskRecurrence(
            frequency="monthly", interval=1, day_of_month=15
        )

        next_due = get_next_due_date(base_date, recurrence)

        assert next_due is not None
        assert next_due.month == 2
        assert next_due.day == 15
        assert next_due.hour == 23
        assert next_due.minute == 45
        assert next_due.second == 30

    def test_monthly_recurrence_end_of_month_clamp(self):
        """Test that monthly recurrence clamps to valid day when target month is shorter."""
        # Jan 31 -> Feb should clamp to Feb 28 (or 29 in leap year)
        base_date = datetime(2026, 1, 31, 12, 0, 0, tzinfo=timezone.utc)
        recurrence = TaskRecurrence(
            frequency="monthly", interval=1, day_of_month=31
        )

        next_due = get_next_due_date(base_date, recurrence)

        assert next_due is not None
        assert next_due.month == 2
        assert next_due.day == 28  # 2026 is not a leap year
        assert next_due.hour == 12

    def test_monthly_recurrence_weekday_mode(self):
        """Test monthly recurrence with weekday mode (e.g., 'second Tuesday')."""
        base_date = datetime(2026, 1, 13, 9, 0, 0, tzinfo=timezone.utc)  # Second Tuesday of Jan
        recurrence = TaskRecurrence(
            frequency="monthly",
            interval=1,
            monthly_mode="weekday",
            weekday_position="second",
            weekday="tuesday",
        )

        next_due = get_next_due_date(base_date, recurrence)

        assert next_due is not None
        assert next_due.month == 2
        # Second Tuesday of Feb 2026 is the 10th
        assert next_due.day == 10
        assert next_due.hour == 9


class TestYearlyRecurrence:
    """Tests for yearly recurrence calculations."""

    def test_yearly_recurrence_preserves_time(self):
        """Verify yearly interval preserves time component."""
        base_date = datetime(2026, 3, 15, 8, 30, 0, tzinfo=timezone.utc)
        recurrence = TaskRecurrence(
            frequency="yearly", interval=1, month=3, day_of_month=15
        )

        next_due = get_next_due_date(base_date, recurrence)

        assert next_due is not None
        assert next_due.year == 2027
        assert next_due.month == 3
        assert next_due.day == 15
        assert next_due.hour == 8
        assert next_due.minute == 30

    def test_yearly_recurrence_leap_year(self):
        """Test yearly recurrence from leap year date (Feb 29)."""
        # Feb 29, 2024 (leap year) -> 2025 (not a leap year) should clamp
        base_date = datetime(2024, 2, 29, 12, 0, 0, tzinfo=timezone.utc)
        recurrence = TaskRecurrence(
            frequency="yearly", interval=1, month=2, day_of_month=29
        )

        next_due = get_next_due_date(base_date, recurrence)

        assert next_due is not None
        assert next_due.year == 2025
        assert next_due.month == 2
        assert next_due.day == 28  # Clamped from 29
        assert next_due.hour == 12


class TestEndConditions:
    """Tests for recurrence end conditions."""

    def test_ends_after_occurrences(self):
        """Test that recurrence ends after specified number of occurrences."""
        base_date = datetime(2026, 1, 20, 12, 0, 0, tzinfo=timezone.utc)
        recurrence = TaskRecurrence(
            frequency="daily",
            interval=1,
            ends="after_occurrences",
            end_after_occurrences=3,
        )

        # First and second occurrences should return a date
        next1 = get_next_due_date(base_date, recurrence, completed_occurrences=0)
        assert next1 is not None

        next2 = get_next_due_date(next1, recurrence, completed_occurrences=1)
        assert next2 is not None

        # Third occurrence (completed_occurrences=2) should return None
        next3 = get_next_due_date(next2, recurrence, completed_occurrences=2)
        assert next3 is None

    def test_ends_on_date(self):
        """Test that recurrence ends on specified date."""
        base_date = datetime(2026, 1, 20, 12, 0, 0, tzinfo=timezone.utc)
        end_date = datetime(2026, 1, 25, 0, 0, 0, tzinfo=timezone.utc)
        recurrence = TaskRecurrence(
            frequency="daily",
            interval=2,
            ends="on_date",
            end_date=end_date,
        )

        # Jan 20 + 2 days = Jan 22 (should be allowed)
        next1 = get_next_due_date(base_date, recurrence)
        assert next1 is not None
        assert next1.day == 22

        # Jan 22 + 2 days = Jan 24 (should be allowed)
        next2 = get_next_due_date(next1, recurrence)
        assert next2 is not None
        assert next2.day == 24

        # Jan 24 + 2 days = Jan 26 (should be blocked, past end_date)
        next3 = get_next_due_date(next2, recurrence)
        assert next3 is None


class TestEdgeCases:
    """Tests for edge cases and special scenarios."""

    def test_naive_datetime_gets_utc_timezone(self):
        """Test that naive datetime is converted to UTC."""
        base_date = datetime(2026, 1, 20, 12, 0, 0)  # No timezone
        recurrence = TaskRecurrence(frequency="daily", interval=1)

        next_due = get_next_due_date(base_date, recurrence)

        assert next_due is not None
        assert next_due.tzinfo == timezone.utc

    def test_none_base_date_returns_none(self):
        """Test that None base_date returns None."""
        recurrence = TaskRecurrence(frequency="daily", interval=1)

        result = get_next_due_date(None, recurrence)

        assert result is None

    def test_interval_minimum_is_one(self):
        """Test that minimum valid interval is 1."""
        base_date = datetime(2026, 1, 20, 12, 0, 0, tzinfo=timezone.utc)
        recurrence = TaskRecurrence(frequency="daily", interval=1)

        next_due = get_next_due_date(base_date, recurrence)

        assert next_due is not None
        # Should be 1 day later
        assert next_due.day == 21
        assert next_due.hour == 12
