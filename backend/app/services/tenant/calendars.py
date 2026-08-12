"""Calendar container service — loaders and helpers for the calendar tool.

A calendar is the shareable DAC anchor for its events (``resource_type=
'calendar'``); events inherit access from it the way tasks inherit from their
project, so the loaders here eager-load ``grants`` + ``initiative.memberships``
for the permission engine.

Two kinds of calendar live here. Nearly all of them belong to an initiative. A
**guild calendar** — the one the calendar app installs — belongs to none, and
that is the whole of what it is: a set of its own events, holding nothing from
any initiative and reaching into none. Its ``initiative_id`` is NULL, so
anything derived from an initiative has nothing to derive from and refuses.
"""

from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import CalendarMessages
from app.core.tools import Tool
from app.models.platform.user import User
from app.models.tenant.calendar import Calendar
from app.models.tenant.calendar_event import (
    CalendarEvent,
    CalendarEventAttendee,
    CalendarEventDocument,
    CalendarEventTag,
)
from app.models.tenant.initiative import Initiative
from app.models.tenant.property import CalendarEventPropertyValue
from app.models.tenant.resource_grant import ResourceGrant
from app.services.tenant import tags as tags_service


def tool_enabled_clause():
    """Calendars whose tool is switched on.

    An initiative calendar answers to that initiative's ``calendars_enabled``
    switch. A guild calendar answers to no initiative, so the switch has nothing
    to say about it — installing the app is what turned it on, and removing the
    app is what takes it away.

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
        selectinload(Calendar.grants).selectinload(ResourceGrant.role),
        selectinload(Calendar.initiative).selectinload(Initiative.memberships),
        tags_service.TOOL_TAG_LINKS[Tool.calendar].load_options(),
    ]


async def get_calendar(
    session: AsyncSession,
    calendar_id: int,
    *,
    populate_existing: bool = False,
) -> Calendar | None:
    """Fetch a calendar with the relationships authorization + serialization
    need. RLS scopes the row to the request's guild."""
    stmt = (
        select(Calendar)
        .where(Calendar.id == calendar_id)
        .options(*calendar_loader_options())
    )
    if populate_existing:
        stmt = stmt.execution_options(populate_existing=True)
    result = await session.exec(stmt)
    return result.one_or_none()


def _event_export_loader_options() -> list:
    """Eager-load each event's relationships that export serialization reads —
    ``event_export_dict`` walks attendees, tags, linked documents, and property
    values, and async SQLAlchemy forbids the lazy loads those would otherwise
    trigger on the worker's render-time replay."""
    return [
        selectinload(Calendar.events)
        .selectinload(CalendarEvent.attendees)
        .selectinload(CalendarEventAttendee.user),
        selectinload(Calendar.events)
        .selectinload(CalendarEvent.tag_links)
        .selectinload(CalendarEventTag.tag),
        selectinload(Calendar.events)
        .selectinload(CalendarEvent.document_links)
        .selectinload(CalendarEventDocument.document),
        selectinload(Calendar.events)
        .selectinload(CalendarEvent.property_values)
        .selectinload(CalendarEventPropertyValue.property_definition),
        selectinload(Calendar.events)
        .selectinload(CalendarEvent.property_values)
        .selectinload(CalendarEventPropertyValue.value_user),
    ]


async def get_calendar_for_export(
    session: AsyncSession,
    current_user: User,
    guild_id: int,
    *,
    calendar_id: int,
) -> Calendar:
    """The calendar-export adapter's seam: fetch + authorize in one place so the
    rule holds on the worker's render-time replay too. READ access suffices —
    exporting is a formatted read. The guild role is resolved here rather than
    taken from a request context, so the seam works transport-free. Events are
    eager-loaded with everything export serialization needs."""
    from app.services import permissions as permissions_service
    from app.services.platform import guilds as guilds_service

    stmt = (
        select(Calendar)
        .where(Calendar.id == calendar_id)
        .options(*calendar_loader_options(), *_event_export_loader_options())
    )
    calendar = (await session.exec(stmt)).one_or_none()
    if calendar is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=CalendarMessages.NOT_FOUND,
        )
    if calendar.initiative is not None and not calendar.initiative.calendars_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=CalendarMessages.FEATURE_DISABLED,
        )
    membership = await guilds_service.get_membership(
        session, guild_id=guild_id, user_id=current_user.id
    )
    permissions_service.require_access(
        permissions_service.DAC_RESOURCES[Tool.calendar],
        calendar,
        current_user,
        access="read",
        guild_role=membership.role if membership else None,
    )
    return calendar


async def list_calendar_ids_for_export(
    session: AsyncSession,
    current_user: User,
    guild_id: int,
    *,
    initiative_id: int | None = None,
) -> list[int]:
    """Ids of every calendar the user may export — the enumeration behind
    "export my calendars": calendars whose tool is on, DAC-visible to the user
    (guild admins see all via the membership role), optionally narrowed to one
    initiative. Deterministic order for stable output.

    Narrowed to an initiative, a guild calendar is not among them: it belongs to
    no initiative, so it is in no initiative's export either."""
    from app.services import permissions as permissions_service
    from app.services.platform import guilds as guilds_service
    from app.services.rls import is_guild_admin

    if initiative_id is not None:
        conditions = [Calendar.initiative_id == initiative_id]
    else:
        conditions = [tool_enabled_clause()]

    membership = await guilds_service.get_membership(
        session, guild_id=guild_id, user_id=current_user.id
    )
    if membership is None or not is_guild_admin(membership.role):
        # Non-admins: only calendars shared with them (the same visible-ids
        # subquery the list endpoint applies).
        conditions.append(
            Calendar.id.in_(
                permissions_service.visible_resource_ids_subquery(
                    "calendar", current_user.id
                )
            )
        )

    statement = (
        select(Calendar.id)
        .where(*conditions)
        .order_by(Calendar.name.asc(), Calendar.id.asc())
    )
    return list(await session.exec(statement))
