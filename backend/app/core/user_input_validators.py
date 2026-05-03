"""Cross-endpoint validators for user-supplied profile fields.

These were originally module-private helpers in
``app.api.v1.endpoints.users``. Moving them here lets the registration
endpoint (``app.api.v1.endpoints.auth``) reuse the same rules without
reaching across to a sibling endpoint's underscore-prefixed symbol.
"""
from __future__ import annotations

import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, status

from app.core.messages import UserMessages

_TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def normalize_timezone(value: str | None) -> str | None:
    """Validate an IANA timezone name (e.g. ``"America/Los_Angeles"``).

    Returns the trimmed value when valid, ``None`` for missing/blank
    input, and raises ``400 USER_INVALID_TIMEZONE`` for anything
    Python's ``zoneinfo`` doesn't recognise.
    """
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        ZoneInfo(cleaned)
    except ZoneInfoNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=UserMessages.INVALID_TIMEZONE,
        )
    return cleaned


def normalize_notification_time(value: str | None) -> str | None:
    """Validate a ``"HH:MM"`` 24-hour clock string."""
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if not _TIME_PATTERN.match(cleaned):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=UserMessages.INVALID_TIME_FORMAT,
        )
    return cleaned


def normalize_week_starts_on(value: int | str | None) -> int | None:
    """Validate a Sunday-Saturday weekday index (0–6)."""
    if value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=UserMessages.INVALID_WEEK_START,
        )
    if number < 0 or number > 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=UserMessages.INVALID_WEEK_START,
        )
    return number
