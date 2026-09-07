"""Grouping a tool's rows into the periods a timeline rail scrolls.

One aggregate, written once, taking the two things that differ per tool: the
expression that dates a row, and the conditions that decide which rows this
reader may count. Everything else — the month truncation, the reader's own time
zone, the order, the anchor a jump lands on — is the same question whatever the
rows are.

The conditions are the caller's because they are the part that must not be
shared. A board's rows are gated by sharing and publication, a calendar's by
something else; passing them in means each tool answers for its own rows
through its own gates, and this never becomes a route that can see across
tools.
"""

from collections.abc import Sequence
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.schemas.tenant.timeline import TimelineBucket

#: What the client is shown when it asks for no zone. Months are a human
#: boundary, so they are cut in the reader's day rather than in UTC — but a
#: caller that says nothing gets the one zone that needs no guessing.
DEFAULT_TIMEZONE = "UTC"


def resolve_zone(tz: str | None) -> str:
    """The zone to cut months in, or a ``ValueError`` naming a bad one.

    Checked here rather than left to the database. Postgres answers an unknown
    zone with an error of its own, which surfaces as a 500 — a request that is
    simply wrong should say so, and it should say so the same way for every
    tool that asks for a timeline.
    """
    if not tz:
        return DEFAULT_TIMEZONE
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(tz) from exc
    return tz


async def month_buckets(
    session: AsyncSession,
    *,
    date_expr: Any,
    conditions: Sequence[Any],
    tz: str | None = None,
) -> list[TimelineBucket]:
    """Rows grouped by the month they fall in, newest month first.

    ``date_expr`` is whatever dates a row for this tool — a board uses the same
    ``board_time()`` its feed is ordered by, so the rail and the feed cannot
    disagree about which month a notice is in.

    The month boundary is cut in ``tz``, bound as a parameter rather than
    written into the SQL: a month is a boundary in somebody's day, and a reader
    in Auckland should not find a notice they posted this morning filed under
    last month.

    ``anchor`` is the newest instant in each month rather than the month's own
    end. It is what a jump asks for, and taking it from the data means the
    client never has to work out when a month ends somewhere else.
    """
    zone = resolve_zone(tz)
    # ``timezone(zone, ts)`` renders the instant as local wall time, which is
    # what a month boundary is drawn against.
    local = func.timezone(zone, date_expr)
    month = func.date_trunc("month", local)

    rows = (
        await session.exec(
            select(
                func.to_char(month, "YYYY-MM").label("period"),
                func.count().label("count"),
                func.max(date_expr).label("anchor"),
            )
            .where(*conditions)
            .group_by(month)
            .order_by(month.desc())
        )
    ).all()

    return [
        TimelineBucket(period=period, count=count, anchor=anchor)
        for period, count, anchor in rows
    ]
