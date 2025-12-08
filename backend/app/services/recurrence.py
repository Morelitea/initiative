from __future__ import annotations

from calendar import monthrange
from datetime import datetime, timedelta, timezone

from app.schemas.task import TaskRecurrence

WEEKDAY_NAMES = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]

WEEKDAY_TO_INDEX = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

WEEK_POSITION_TO_OFFSET = {
    "first": 0,
    "second": 1,
    "third": 2,
    "fourth": 3,
    "last": -1,
}


def _ensure_timezone(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _clamp_day(year: int, month: int, day: int) -> int:
    _, days_in_month = monthrange(year, month)
    return max(1, min(day, days_in_month))


def _add_months(source: datetime, months: int) -> tuple[int, int]:
    total_months = source.month - 1 + months
    year = source.year + total_months // 12
    month = total_months % 12 + 1
    return year, month


def _nth_weekday_of_month(year: int, month: int, weekday: int, position: str) -> int:
    offset = WEEK_POSITION_TO_OFFSET.get(position, 0)
    _, days_in_month = monthrange(year, month)
    matches = [day for day in range(1, days_in_month + 1) if datetime(year, month, day).weekday() == weekday]
    if not matches:
        return 1
    if position == "last":
        return matches[-1]
    if 0 <= offset < len(matches):
        return matches[offset]
    return matches[-1]


def _next_weekly_date(base: datetime, recurrence: TaskRecurrence) -> datetime:
    weekdays = recurrence.weekdays or [WEEKDAY_NAMES[base.weekday()]]
    weekday_indexes = sorted(WEEKDAY_TO_INDEX.get(day, base.weekday()) for day in weekdays)

    # For weekly recurrence, we assume the base date is already on one of the target weekdays
    # (as determined by the frontend in the user's timezone). We simply add the interval in weeks.
    # This avoids timezone-related weekday mismatches.
    if len(weekdays) == 1:
        # Simple case: single weekday, just add interval weeks
        return base + timedelta(weeks=max(1, recurrence.interval))

    # Multiple weekdays: find the next one in the current week, or wrap to next interval
    current = base.weekday()
    for target in weekday_indexes:
        if target > current:
            delta = target - current
            return base + timedelta(days=delta)

    # No weekday found in current week, wrap to first weekday of next interval
    weeks_to_add = max(1, recurrence.interval)
    days_until_first = (7 - current + weekday_indexes[0]) % 7
    if days_until_first == 0:
        days_until_first = 7
    delta_days = (weeks_to_add - 1) * 7 + days_until_first
    return base + timedelta(days=delta_days)


def _next_monthly_date(base: datetime, recurrence: TaskRecurrence) -> datetime:
    months_to_add = max(1, recurrence.interval)
    year, month = _add_months(base, months_to_add)

    if recurrence.monthly_mode == "weekday":
        weekday_position = recurrence.weekday_position or "first"
        weekday_value = recurrence.weekday or "monday"
        weekday_index = WEEKDAY_TO_INDEX.get(weekday_value, 0)
        target_day = _nth_weekday_of_month(year, month, weekday_index, weekday_position)
    else:
        # If day_of_month is specified, use it and account for timezone offset
        if recurrence.day_of_month:
            # Calculate the offset between stored day (local) and actual day (UTC)
            # This handles cases where time causes date to roll over in UTC
            day_offset = base.day - recurrence.day_of_month
            target_day = recurrence.day_of_month + day_offset
        else:
            target_day = base.day
        target_day = _clamp_day(year, month, target_day)

    return base.replace(year=year, month=month, day=target_day)


def _next_yearly_date(base: datetime, recurrence: TaskRecurrence) -> datetime:
    years_to_add = max(1, recurrence.interval)
    target_year = base.year + years_to_add
    target_month = recurrence.month or base.month

    if recurrence.monthly_mode == "weekday":
        weekday_position = recurrence.weekday_position or "first"
        weekday_value = recurrence.weekday or "monday"
        weekday_index = WEEKDAY_TO_INDEX.get(weekday_value, 0)
        target_day = _nth_weekday_of_month(target_year, target_month, weekday_index, weekday_position)
    else:
        # If day_of_month is specified, use it and account for timezone offset
        if recurrence.day_of_month:
            # Calculate the offset between stored day (local) and actual day (UTC)
            # This handles cases where time causes date to roll over in UTC
            day_offset = base.day - recurrence.day_of_month
            target_day = recurrence.day_of_month + day_offset
        else:
            target_day = base.day
        target_day = _clamp_day(target_year, target_month, target_day)

    return base.replace(year=target_year, month=target_month, day=target_day)


def get_next_due_date(
    base_date: datetime,
    recurrence: TaskRecurrence,
    *,
    completed_occurrences: int = 0,
) -> datetime | None:
    base = _ensure_timezone(base_date)
    if base is None:
        return None

    if recurrence.ends == "after_occurrences":
        limit = recurrence.end_after_occurrences
        if limit is not None and completed_occurrences + 1 >= limit:
            return None

    if recurrence.frequency == "daily":
        next_date = base + timedelta(days=max(1, recurrence.interval))
    elif recurrence.frequency == "weekly":
        next_date = _next_weekly_date(base, recurrence)
    elif recurrence.frequency == "monthly":
        next_date = _next_monthly_date(base, recurrence)
    elif recurrence.frequency == "yearly":
        next_date = _next_yearly_date(base, recurrence)
    else:
        return None

    if recurrence.ends == "on_date" and recurrence.end_date is not None:
        end_date = _ensure_timezone(recurrence.end_date)
        if end_date is not None and next_date > end_date:
            return None

    return next_date
