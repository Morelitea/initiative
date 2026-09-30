"""repeats are RRULE lines, as picked, with a shift

A task's or an event's repeat was a JSON object of our own (frequency,
weekdays, "monthly_mode", ...). It becomes RFC 5545 recurrence lines, the days
as they were picked, and ``recurrence_shift`` beside it: the minutes from the
start's UTC time to where it was picked, whole days for a rule of days
(``app.core.recurrence``). ``recurrence_until`` is the latest start the series
can have, or null for one that never ends.

The old objects were picked in their creator's zone, so each shift is taken in
their profile timezone (UTC when there is none). That zone is used here, once,
and stored nowhere. The JSON shape is stated below in full, so this revision
reads the same whatever the modules say later; only the engine, which writes
what the current app reads, comes from ``app.core.recurrence``.

An all-day event becomes its dates: the creator's local first and last day, as
UTC midnight and 23:59:59, so every viewer sees the same days.

A repeat that doesn't convert (malformed, or asking for something the rule
can't hold) is dropped, and the count is logged per schema. Every reader already
ignored those rows. The downgrade drops the rules: a JSON object can't hold what
an RRULE can.

Revision ID: 20260930_0421
Revises: 20260930_0420
Create Date: 2026-09-30
"""

import json
import logging
from datetime import date, datetime, time, timezone, tzinfo
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from alembic import op

from app.core.recurrence import last_start, normalize, shift_for
from app.db.guild_migrations import guild_schema_names, run_for_each_guild_schema

revision = "20260930_0421"
down_revision = "20260930_0420"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

_TABLES = ("tasks", "calendar_events")
_END_OF_DAY = time(23, 59, 59)
_POSITIONS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "last": -1}
_WEEKDAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")


def _zone(name: str | None) -> tzinfo:
    try:
        return ZoneInfo(name or "UTC")
    except (KeyError, ValueError, OSError):
        return timezone.utc


def _picked_rule(data: dict, *, zone: tzinfo, all_day: bool) -> str | None:
    """The JSON repeat as the RRULE its creator picked, in their zone's days."""
    freq = str(data.get("frequency") or "").upper()
    if freq not in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY"):
        return None

    def code(day: object) -> str:
        # Tasks stored "monday"; events imported from a file stored "MO".
        return str(day)[:2].upper()

    parts = [f"FREQ={freq}"]
    if (interval := int(data.get("interval") or 1)) > 1:
        parts.append(f"INTERVAL={interval}")
    if freq == "WEEKLY" and data.get("weekdays"):
        days = [code(day) for day in data["weekdays"] if code(day) in _WEEKDAYS]
        if days:
            parts.append("BYDAY=" + ",".join(days))
    if freq in ("MONTHLY", "YEARLY"):
        if data.get("monthly_mode") == "weekday" and data.get("weekday"):
            position = _POSITIONS.get(data.get("weekday_position") or "first", 1)
            parts.append(f"BYDAY={position}{code(data['weekday'])}")
        elif day := data.get("day_of_month"):
            day = int(day)
            if day <= 28:
                parts.append(f"BYMONTHDAY={day}")
            else:
                # A day a short month lacked fell on that month's last day.
                days = ",".join(str(d) for d in range(28, day + 1))
                parts.append(f"BYMONTHDAY={days};BYSETPOS=-1")
        if freq == "YEARLY" and data.get("month"):
            parts.append(f"BYMONTH={int(data['month'])}")
    if data.get("ends") == "after_occurrences" and data.get("end_after_occurrences"):
        parts.append(f"COUNT={int(data['end_after_occurrences'])}")
    elif data.get("ends") == "on_date" and data.get("end_date"):
        # The last day as the form showed it: the date the value was written with.
        last = datetime.fromisoformat(str(data["end_date"])).date()
        if all_day:
            parts.append(f"UNTIL={last:%Y%m%d}")
        else:
            until = datetime.combine(last, _END_OF_DAY, zone).astimezone(timezone.utc)
            parts.append(f"UNTIL={until:%Y%m%dT%H%M%SZ}")
    return "RRULE:" + ";".join(parts)


def _stored(
    raw: object, start: datetime, *, zone: tzinfo, kind: str, all_day: bool
) -> tuple[str | None, int]:
    """One old JSON repeat as stored, and its shift, or none when it doesn't
    convert."""
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(data, dict):
            return None, 0
        picked = _picked_rule(data, zone=zone, all_day=all_day)
        if picked is None:
            return None, 0
        rule = normalize(picked, kind=kind)  # type: ignore[arg-type]
        return rule, shift_for(rule, start, zone)
    except (ValueError, TypeError, KeyError):
        return None, 0


def _day_start(value: date) -> datetime:
    return datetime.combine(value, time(), timezone.utc)


def _update(bind, statement: str, params: dict) -> None:
    if bind.execute(sa.text(statement), params).rowcount != 1:
        raise RuntimeError(f"a repeat conversion updated no row: {params['id']}")


def _convert(bind, schema: str, zones: dict[int, tzinfo]) -> None:
    dropped = 0
    tasks = bind.execute(
        sa.text(
            "SELECT id, recurrence::text AS recurrence, due_date, start_date,"
            " recurrence_occurrence_count, created_by FROM tasks"
            " WHERE recurrence IS NOT NULL"
        )
    ).mappings()
    for row in tasks.all():
        start = row["due_date"] or row["start_date"]
        zone = zones.get(row["created_by"], timezone.utc)
        rule, shift = (
            _stored(row["recurrence"], start, zone=zone, kind="task", all_day=False)
            if start
            else (None, 0)
        )
        dropped += rule is None
        _update(
            bind,
            "UPDATE tasks SET recurrence_rule = :rule, recurrence_shift = :shift,"
            " recurrence_until = :until WHERE id = :id",
            {
                "id": row["id"],
                "rule": rule,
                "shift": shift,
                "until": last_start(
                    rule, start, shift, done=row["recurrence_occurrence_count"]
                )
                if rule
                else None,
            },
        )

    events = bind.execute(
        sa.text(
            "SELECT id, recurrence, start_at, end_at, all_day, created_by"
            " FROM calendar_events WHERE recurrence IS NOT NULL OR all_day"
        )
    ).mappings()
    for row in events.all():
        zone = zones.get(row["created_by"], timezone.utc)
        start, end = row["start_at"], row["end_at"]
        if row["all_day"]:
            first = start.astimezone(zone).date()
            start = _day_start(first)
            end = datetime.combine(
                max(end.astimezone(zone).date(), first), _END_OF_DAY, timezone.utc
            )
        rule, shift = None, 0
        if row["recurrence"] is not None:
            # An all-day event's days are UTC dates now, so its rule's are too.
            rule, shift = _stored(
                row["recurrence"],
                start,
                zone=timezone.utc if row["all_day"] else zone,
                kind="event",
                all_day=row["all_day"],
            )
            dropped += rule is None
        _update(
            bind,
            "UPDATE calendar_events SET recurrence_rule = :rule,"
            " recurrence_shift = :shift, recurrence_until = :until,"
            " start_at = :start, end_at = :end WHERE id = :id",
            {
                "id": row["id"],
                "rule": rule,
                "shift": shift,
                "until": last_start(rule, start, shift) if rule else None,
                "start": start,
                "end": end,
            },
        )
    if dropped:
        logger.warning(
            "%s: %d repeat(s) did not convert and were dropped", schema, dropped
        )


def _add_columns() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column("recurrence_rule", sa.Text(), nullable=True))
        op.add_column(
            table,
            sa.Column("recurrence_until", sa.DateTime(timezone=True), nullable=True),
        )
        op.add_column(
            table,
            sa.Column(
                "recurrence_shift", sa.Integer(), nullable=False, server_default="0"
            ),
        )


def _swap_columns() -> None:
    for table in _TABLES:
        op.drop_column(table, "recurrence")
        op.alter_column(table, "recurrence_rule", new_column_name="recurrence")


def _creator_zones(bind) -> dict[int, tzinfo]:
    # A migration carries no request context, so the owner's policies are
    # lifted while the profile zones are read.
    bind.execute(sa.text("ALTER TABLE public.users NO FORCE ROW LEVEL SECURITY"))
    try:
        rows = bind.execute(sa.text("SELECT id, timezone FROM public.users")).all()
    finally:
        bind.execute(sa.text("ALTER TABLE public.users FORCE ROW LEVEL SECURITY"))
    return {user_id: _zone(name) for user_id, name in rows}


def upgrade() -> None:
    bind = op.get_bind()
    run_for_each_guild_schema(bind, _add_columns)
    zones = _creator_zones(bind)
    for schema in guild_schema_names(bind):
        if not schema.removeprefix("guild_").isdigit():
            continue
        bind.execute(
            sa.text("SELECT set_config('search_path', :sp, true)"),
            {"sp": f"{schema}, public"},
        )
        # The tables' policies and request triggers (the freeze, change
        # capture, search) are held while rows change.
        for table in _TABLES:
            op.execute(f"ALTER TABLE {schema}.{table} NO FORCE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {schema}.{table} DISABLE TRIGGER USER")
        try:
            _convert(bind, schema, zones)
        finally:
            for table in _TABLES:
                op.execute(f"ALTER TABLE {schema}.{table} ENABLE TRIGGER USER")
                op.execute(f"ALTER TABLE {schema}.{table} FORCE ROW LEVEL SECURITY")
    bind.execute(sa.text("SELECT set_config('search_path', 'public', true)"))
    run_for_each_guild_schema(bind, _swap_columns)


def _restore_columns() -> None:
    op.drop_column("tasks", "recurrence")
    op.drop_column("tasks", "recurrence_until")
    op.drop_column("tasks", "recurrence_shift")
    op.add_column("tasks", sa.Column("recurrence", sa.JSON(), nullable=True))
    op.drop_column("calendar_events", "recurrence")
    op.drop_column("calendar_events", "recurrence_until")
    op.drop_column("calendar_events", "recurrence_shift")
    op.add_column("calendar_events", sa.Column("recurrence", sa.Text(), nullable=True))


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _restore_columns)
