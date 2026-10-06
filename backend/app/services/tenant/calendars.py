"""Calendar container service — loaders and helpers for the calendar tool.

A calendar is the shareable DAC anchor for its events (``resource_type=
'calendar'``); events inherit access from it the way tasks inherit from their
project, so the loaders here eager-load ``grants`` and the level the request
holds on the calendar.

Two kinds of calendar live here. Nearly all of them belong to an initiative. A
**guild calendar** — the one the calendar plug-in installs — belongs to none, and
that is the whole of what it is: a set of its own events, holding nothing from
any initiative and reaching into none. Its ``initiative_id`` is NULL, so
anything derived from an initiative has nothing to derive from and refuses.
"""

from sqlalchemy import or_
from sqlalchemy.orm import selectinload, undefer
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.user import User
from app.models.tenant.calendar import Calendar
from app.models.tenant.calendar_event import (
    CalendarEvent,
    CalendarEventAttendee,
)
from app.models.tenant.initiative import Initiative
from app.services.tenant import properties as properties_service
from app.services.tenant import tags as tags_service


def tool_enabled_clause():
    """Calendars whose tool is switched on.

    An initiative calendar answers to that initiative's ``calendars_enabled``
    switch. A guild calendar answers to no initiative, so the switch has nothing
    to say about it — installing the plug-in is what turned it on, and removing the
    plug-in is what takes it away.

    Use this only where the question is "every calendar in scope". A query for
    *one initiative's* calendars must keep comparing ``initiative_id`` directly:
    a guild calendar belongs to no initiative and so belongs in no initiative's
    view.
    """
    return or_(
        Calendar.initiative_id.is_(None),
        Calendar.initiative_id.in_(
            select(Initiative.id).where(Initiative.calendars_enabled == True)  # noqa: E712
        ),
    )


def guild_scoped(calendar: Calendar) -> bool:
    """Whether this calendar belongs to the guild rather than an initiative."""
    return calendar.initiative_id is None


def calendar_loader_options() -> list:
    """Eager-load everything calendar serialization + authorization needs."""
    return [
        selectinload(Calendar.grants),
        selectinload(Calendar.initiative),
        undefer(Calendar.actions),
    ]


async def get_calendar(
    session: AsyncSession,
    calendar_id: int,
    *,
    populate_existing: bool = False,
    with_events: bool = False,
) -> Calendar | None:
    """Fetch a calendar with the relationships authorization + serialization
    need, and with ``with_events`` its events as an export serializes them.
    RLS scopes the row to the request's guild."""
    stmt = (
        select(Calendar)
        .where(Calendar.id == calendar_id)
        .options(
            *calendar_loader_options(),
            *(_event_export_loader_options() if with_events else ()),
        )
    )
    if populate_existing:
        stmt = stmt.execution_options(populate_existing=True)
    result = await session.exec(stmt)
    calendar = result.one_or_none()
    if calendar is not None:
        await tags_service.annotate_tags(session, [calendar])
        await properties_service.annotate_properties(session, [calendar])
        if with_events:
            await tags_service.annotate_tags(session, calendar.events or [])
            await properties_service.annotate_properties(session, calendar.events or [])
    return calendar


def _event_export_loader_options() -> list:
    """Eager-load each event's relationships that export serialization reads —
    ``event_export_dict`` walks attendees, tags, linked documents, and property
    values, and async SQLAlchemy forbids the lazy loads those would otherwise
    trigger on the worker's render-time replay."""
    return [
        selectinload(Calendar.events)
        .selectinload(CalendarEvent.attendees)
        .selectinload(CalendarEventAttendee.user),
    ]


async def list_calendar_ids_for_export(
    session: AsyncSession,
    current_user: User,
    guild_id: int,
    *,
    initiative_id: int | None = None,
) -> list[int]:
    """Ids of every calendar the user may export — the enumeration behind
    "export my calendars": calendars whose tool is on, DAC-visible to the user
    (a request that reaches the whole guild sees all), optionally narrowed to one
    initiative. Deterministic order for stable output.

    Narrowed to an initiative, a guild calendar is not among them: it belongs to
    no initiative, so it is in no initiative's export either. The tool switch
    applies in both shapes — the narrowing composes with it rather than
    replacing it, so a disabled initiative exports nothing here just as it
    lists nothing everywhere else."""

    conditions = [
        tool_enabled_clause(),
    ]
    if initiative_id is not None:
        conditions.append(Calendar.initiative_id == initiative_id)

    statement = (
        select(Calendar.id)
        .where(*conditions)
        .order_by(Calendar.name.asc(), Calendar.id.asc())
    )
    return list(await session.exec(statement))
