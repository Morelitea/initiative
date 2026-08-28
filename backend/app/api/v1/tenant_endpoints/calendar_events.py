"""Calendar event endpoints — CRUD, attendees, tags, and documents.

Events live inside a calendar and carry no grants of their own: read access is
read on the parent calendar, and every write is write on the parent calendar —
exactly the way tasks inherit project access. Sharing is managed on the
calendar (``PUT /calendars/{id}/grants``), never per event.
"""

import logging
from datetime import datetime, timezone
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import ColumnElement, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.api.deps import (
    IncludeDeletedDep,
    RLSSessionDep,
    get_current_active_user,
    get_guild_membership,
    GuildContext,
)
from app.db.session import get_admin_session
from app.models.tenant.calendar import Calendar
from app.models.tenant.calendar_event import (
    CalendarEvent,
    CalendarEventAttendee,
    CalendarEventDocument,
    CalendarEventTag,
    RSVPStatus,
)
from app.models.tenant.initiative import Initiative
from app.models.tenant.property import CalendarEventPropertyValue
from app.models.platform.user import User
from app.core.messages import CalendarEventMessages
from app.schemas.tenant.calendar_event import (
    CalendarEventCreate,
    CalendarEventUpdate,
    CalendarEventRead,
    CalendarEventListResponse,
    CalendarEventRSVPUpdate,
    serialize_calendar_event,
    serialize_calendar_event_summary,
)
from app.schemas.tenant.ical import (
    ICalImportRequest,
    ICalImportResult,
    ICalParseRequest,
    ICalParseResult,
)
from app.schemas.tenant.property import PropertyValuesSetRequest
from app.schemas.tenant.tag import TagSetRequest
from app.api import resource_access
from app.core.tools import Tool
from app.models.tenant.resource_grant import ResourceGrant
from app.services import permissions as permissions_service
from app.services.tenant import calendar_events as events_service
from app.services.tenant import calendars as calendars_service
from app.services.cross_guild import gather_across_guilds, member_guild_ids
from app.services.tenant import ical_service
from app.services import notifications as notifications_service
from app.services.tenant import properties as properties_service
from app.services.tenant import tags as tags_service

router = APIRouter()
# Cross-guild "my calendar" aggregate (My Calendar page). Mounted under
# /api/v1/me; routes per member guild via gather_across_guilds.
me_router = APIRouter()
logger = logging.getLogger(__name__)

AdminSessionDep = Annotated[AsyncSession, Depends(get_admin_session)]

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_event_or_404(
    session: RLSSessionDep,
    event_id: int,
    user: User,
    guild_context: GuildContext,
    *,
    access: str = "read",
) -> CalendarEvent:
    event = await events_service.get_event(session, event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=CalendarEventMessages.NOT_FOUND,
        )
    # Feature gate + DAC, both resolved on the parent calendar: read to see the
    # event, write for any mutation.
    resource_access.authorize(
        Tool.calendar,
        event.calendar,
        user,
        access=access,
        guild_role=guild_context.role,
    )
    return event


async def _get_writable_calendar(
    session: RLSSessionDep,
    calendar_id: int,
    user: User,
    guild_context: GuildContext,
) -> Calendar:
    """Load a calendar and require write access — the gate for creating or
    moving events into it."""
    return await resource_access.load_authorized(
        session,
        Tool.calendar,
        calendar_id,
        user,
        guild_context,
        access="write",
    )


async def _refetch_event(session: RLSSessionDep, event_id: int) -> CalendarEvent:
    event = await events_service.get_event(session, event_id, populate_existing=True)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=CalendarEventMessages.NOT_FOUND,
        )
    return event


async def _fetch_users(session: RLSSessionDep, user_ids: list[int]) -> list[User]:
    """Load User rows (for reading notification preferences) by id."""
    if not user_ids:
        return []
    result = await session.exec(select(User).where(User.id.in_(tuple(set(user_ids)))))
    return list(result.all())


# ---------------------------------------------------------------------------
# Cross-guild global view
# ---------------------------------------------------------------------------


async def _exec_events(session, stmt) -> list[CalendarEvent]:
    """Run a CalendarEvent select and return de-duplicated rows as a list."""
    result = await session.exec(stmt)
    return list(result.unique().all())


def _cross_guild_event_dac_clause(guild_id: int, user_id: int) -> ColumnElement[bool]:
    """Sharing gate for the cross-guild ``/me`` calendar views.

    The same clause the per-guild list applies, resolved per guild: the role
    ``gather_across_guilds`` established for that guild is what it reads. PAM
    never applies here — the gather only visits guilds the user is a real member
    of — so the clause resolves to a no-op only for a guild admin.
    """
    return permissions_service.dac_scope_clause(
        Tool.calendar, CalendarEvent.calendar_id, user_id, guild_id=guild_id
    )


async def query_my_calendar_events(
    session: AsyncSession,
    current_user: User,
    *,
    guild_ids: Optional[List[int]] = None,
    start_after: Optional[datetime] = None,
    start_before: Optional[datetime] = None,
) -> list[CalendarEvent]:
    """Shared cross-guild calendar-event query for ``list_my_calendar_events``
    and the ``/me/calendar-entries`` aggregate.

    Schema-per-guild: events live in per-guild schemas, so no single query can
    span guilds. Visit each of the user's
    guild schemas (routed to the user's own RLS context, so guild isolation +
    DAC still hold) and merge, sorted by ``(start_at, guild_id, id)``.
    """

    def _fetch(guild_session, guild_id):  # type: ignore[no-untyped-def]
        # Guild calendars included: this is the user's own calendar view, one of
        # the two places their events show (the app's page is the other).
        conditions = [calendars_service.tool_enabled_clause()]
        if start_after is not None:
            conditions.append(CalendarEvent.start_at >= start_after)
        if start_before is not None:
            conditions.append(CalendarEvent.start_at <= start_before)
        conditions.append(_cross_guild_event_dac_clause(guild_id, current_user.id))
        stmt = (
            select(CalendarEvent)
            .join(Calendar, Calendar.id == CalendarEvent.calendar_id)
            .where(*conditions)
            .options(*_calendar_event_loader_options())
        )
        return _exec_events(guild_session, stmt)

    target_guilds = await member_guild_ids(
        session, current_user.id, restrict_to=guild_ids
    )
    events = await gather_across_guilds(session, current_user.id, target_guilds, _fetch)
    # Merge-sort across guilds (per-schema SQL can't order across schemas).
    events.sort(key=lambda e: (e.start_at, e.guild_id, e.id))
    return events


@me_router.get("/calendar-events", response_model=CalendarEventListResponse)
async def list_my_calendar_events(
    session: AdminSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_ids: Optional[List[int]] = Query(default=None),
    start_after: Optional[datetime] = Query(default=None),
    start_before: Optional[datetime] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=200, ge=1, le=200),
) -> CalendarEventListResponse:
    """List calendar events across all guilds the user belongs to.

    Delegates the cross-guild fetch to ``query_my_calendar_events`` and then
    paginates the merged set in Python (per-schema SQL can't limit across
    schemas).
    """
    events = await query_my_calendar_events(
        session,
        current_user,
        guild_ids=guild_ids,
        start_after=start_after,
        start_before=start_before,
    )
    total_count = len(events)
    start = (page - 1) * page_size
    page_events = events[start : start + page_size]

    items = [
        serialize_calendar_event_summary(e, user_id=current_user.id)
        for e in page_events
    ]
    has_next = page * page_size < total_count
    return CalendarEventListResponse(
        items=items,
        total_count=total_count,
        page=page,
        page_size=page_size,
        has_next=has_next,
    )


# ---------------------------------------------------------------------------
# iCal export / import
# ---------------------------------------------------------------------------


@me_router.get("/calendar-events/export.ics")
async def export_my_calendar_events_ics(
    session: AdminSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_ids: Optional[List[int]] = Query(default=None),
    start_after: Optional[datetime] = Query(default=None),
    start_before: Optional[datetime] = Query(default=None),
) -> Response:
    """Export cross-guild calendar events as an .ics file.

    Schema-per-guild: aggregate per guild schema via ``gather_across_guilds``
    — events live only in the per-guild schemas, so no one query spans them.
    """

    def _fetch(guild_session, guild_id):  # type: ignore[no-untyped-def]
        conditions = [calendars_service.tool_enabled_clause()]
        if start_after is not None:
            conditions.append(CalendarEvent.start_at >= start_after)
        if start_before is not None:
            conditions.append(CalendarEvent.start_at <= start_before)
        conditions.append(_cross_guild_event_dac_clause(guild_id, current_user.id))
        stmt = (
            select(CalendarEvent)
            .join(Calendar, Calendar.id == CalendarEvent.calendar_id)
            .where(*conditions)
            .options(
                selectinload(CalendarEvent.attendees).selectinload(
                    CalendarEventAttendee.user
                ),
                # event_export_dict reads tags, linked-document titles, and
                # custom properties too — async lazy loads would raise, so
                # load them here.
                selectinload(CalendarEvent.tag_links).selectinload(
                    CalendarEventTag.tag
                ),
                selectinload(CalendarEvent.document_links).selectinload(
                    CalendarEventDocument.document
                ),
                selectinload(CalendarEvent.property_values).selectinload(
                    CalendarEventPropertyValue.property_definition
                ),
                selectinload(CalendarEvent.property_values).selectinload(
                    CalendarEventPropertyValue.value_user
                ),
            )
        )
        return _exec_events(guild_session, stmt)

    target_guilds = await member_guild_ids(
        session, current_user.id, restrict_to=guild_ids
    )
    events = await gather_across_guilds(session, current_user.id, target_guilds, _fetch)
    events.sort(key=lambda e: (e.start_at, e.guild_id, e.id))

    ics_bytes = ical_service.events_to_ical(list(events))
    return Response(
        content=ics_bytes,
        media_type="text/calendar",
        headers={"Content-Disposition": "attachment; filename=events.ics"},
    )


@router.post("/import/parse", response_model=ICalParseResult)
async def parse_ical_file(
    current_user: Annotated[User, Depends(get_current_active_user)],
    body: ICalParseRequest,
    _guild_context: GuildContextDep,
) -> ICalParseResult:
    """Parse an .ics file and return a preview of found events."""
    try:
        result = ical_service.parse_ical(body.ics_content)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=CalendarEventMessages.ICAL_PARSE_FAILED,
        )
    if result.event_count == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=CalendarEventMessages.ICAL_NO_EVENTS,
        )
    return result


@router.post("/import", response_model=ICalImportResult)
async def import_ical_events(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    body: ICalImportRequest,
) -> ICalImportResult:
    """Import events from an .ics file into a calendar. Requires write access
    on the target calendar."""
    calendar = await _get_writable_calendar(
        session, body.calendar_id, current_user, guild_context
    )

    try:
        events, errors, skipped = ical_service.build_calendar_events(
            content=body.ics_content,
            calendar_id=calendar.id,
            guild_id=guild_context.guild_id,
            created_by=current_user.id,
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=CalendarEventMessages.ICAL_PARSE_FAILED,
        )

    created = 0
    for event in events:
        try:
            async with session.begin_nested():
                session.add(event)
                await session.flush()
            created += 1
        except Exception as exc:
            errors.append(f"DB error for '{event.title}': {exc}")

    if created > 0:
        await session.commit()

    return ICalImportResult(
        events_created=created,
        events_failed=len(events) - created + skipped,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def _calendar_event_loader_options():
    """Eager-load options shared by the list + aggregate event queries.

    Loads attendees, the parent calendar (grants + initiative memberships —
    what my_permission_level needs), tags, and custom property values so
    serialization never triggers an async lazy-load.
    """
    return (
        selectinload(CalendarEvent.attendees).selectinload(CalendarEventAttendee.user),
        selectinload(CalendarEvent.calendar)
        .selectinload(Calendar.grants)
        .selectinload(ResourceGrant.role),
        selectinload(CalendarEvent.calendar)
        .selectinload(Calendar.initiative)
        .selectinload(Initiative.memberships),
        selectinload(CalendarEvent.tag_links).selectinload(CalendarEventTag.tag),
        selectinload(CalendarEvent.property_values).selectinload(
            CalendarEventPropertyValue.property_definition
        ),
        selectinload(CalendarEvent.property_values).selectinload(
            CalendarEventPropertyValue.value_user
        ),
    )


async def query_guild_calendar_events(
    session: RLSSessionDep,
    current_user: User,
    guild_context: GuildContext,
    *,
    initiative_id: Optional[int] = None,
    guild_scope: bool = False,
    calendar_ids: Optional[List[int]] = None,
    start_after: Optional[datetime] = None,
    start_before: Optional[datetime] = None,
    property_filters: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
) -> tuple[list[CalendarEvent], int]:
    """Shared guild calendar-event query for ``list_calendar_events`` and the
    ``calendar-entries`` aggregate.

    Applies the same guild scope, feature-gate, window, property-filter, and DAC
    conditions to both callers so access is identical. Returns
    ``(events, total_count)``; pass ``limit=None`` (the aggregate's bounded
    window) to fetch every matching row, or ``limit``/``offset`` to paginate.

    ``guild_scope`` narrows to the guild's own calendars — the ones belonging to
    no initiative. It is the calendar app's whole surface, and stating it here
    is what keeps that surface from having to name its calendars one by one: a
    list of ids is a page of them, and events on whatever fell off the end would
    simply not be drawn.
    """
    conditions = [CalendarEvent.guild_id == guild_context.guild_id]

    if guild_scope:
        conditions.append(
            CalendarEvent.calendar_id.in_(
                select(Calendar.id).where(Calendar.initiative_id.is_(None))
            )
        )
    elif initiative_id is not None:
        initiative = await session.get(Initiative, initiative_id)
        if initiative and not initiative.calendars_enabled:
            return [], 0
        conditions.append(
            CalendarEvent.calendar_id.in_(
                select(Calendar.id).where(Calendar.initiative_id == initiative_id)
            )
        )
    else:
        # No initiative asked for: every calendar in scope, guild calendars
        # among them. Narrowed to one initiative (above), they are excluded —
        # a guild calendar belongs to no initiative, so its events never appear
        # in an initiative's view of the calendar.
        conditions.append(
            CalendarEvent.calendar_id.in_(
                select(Calendar.id).where(calendars_service.tool_enabled_clause())
            )
        )

    if calendar_ids:
        conditions.append(CalendarEvent.calendar_id.in_(tuple(set(calendar_ids))))

    if start_after is not None:
        conditions.append(CalendarEvent.start_at >= start_after)
    if start_before is not None:
        conditions.append(CalendarEvent.start_at <= start_before)

    # Property filters: parse, resolve definitions, compile to subquery
    # clauses shared with documents/tasks so event filtering picks up the
    # same typed comparison + is_empty presence semantics for free.
    if property_filters:
        try:
            parsed = properties_service.parse_property_filters(property_filters)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            )
        if parsed:
            defs_map = await properties_service.load_definitions_by_ids(
                session, [c.property_id for c in parsed]
            )
            conditions.extend(
                properties_service.build_property_filter_clauses(
                    "event", parsed, defs_map
                )
            )

    # An event is reached through its calendar, so the sharing gate applies to
    # the calendar the event names.
    conditions.append(
        permissions_service.dac_scope_clause(
            Tool.calendar,
            CalendarEvent.calendar_id,
            current_user.id,
            guild_id=guild_context.guild_id,
        )
    )

    count_subq = select(CalendarEvent.id).where(*conditions).subquery()
    count_stmt = select(func.count()).select_from(count_subq)
    total_count = (await session.exec(count_stmt)).one()

    stmt = (
        select(CalendarEvent)
        .where(*conditions)
        .options(*_calendar_event_loader_options())
        .order_by(CalendarEvent.start_at.asc(), CalendarEvent.id.asc())
        .offset(offset)
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    result = await session.exec(stmt)
    return list(result.unique().all()), total_count


@router.get("/", response_model=CalendarEventListResponse)
async def list_calendar_events(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    initiative_id: Optional[int] = Query(default=None),
    calendar_ids: Optional[List[int]] = Query(default=None),
    start_after: Optional[datetime] = Query(default=None),
    start_before: Optional[datetime] = Query(default=None),
    property_filters: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> CalendarEventListResponse:
    """List calendar events. RLS + calendar DAC handle access."""
    events, total_count = await query_guild_calendar_events(
        session,
        current_user,
        guild_context,
        initiative_id=initiative_id,
        calendar_ids=calendar_ids,
        start_after=start_after,
        start_before=start_before,
        property_filters=property_filters,
        limit=page_size,
        offset=(page - 1) * page_size,
    )

    items = [
        serialize_calendar_event_summary(e, user_id=current_user.id) for e in events
    ]
    has_next = page * page_size < total_count
    return CalendarEventListResponse(
        items=items,
        total_count=total_count,
        page=page,
        page_size=page_size,
        has_next=has_next,
    )


@router.get("/{event_id}", response_model=CalendarEventRead)
async def read_calendar_event(
    event_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    include_deleted: IncludeDeletedDep = False,
) -> CalendarEventRead:
    event = await _get_event_or_404(session, event_id, current_user, guild_context)
    return serialize_calendar_event(event, user_id=current_user.id)


@router.post("/", response_model=CalendarEventRead, status_code=status.HTTP_201_CREATED)
async def create_calendar_event(
    event_in: CalendarEventCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> CalendarEventRead:
    """Create a calendar event. Requires write access on the calendar."""
    await _get_writable_calendar(
        session, event_in.calendar_id, current_user, guild_context
    )

    recurrence_json = None
    if event_in.recurrence:
        recurrence_json = event_in.recurrence.model_dump_json()

    event = CalendarEvent(
        guild_id=guild_context.guild_id,
        calendar_id=event_in.calendar_id,
        created_by=current_user.id,
        title=event_in.title.strip(),
        description=event_in.description,
        location=event_in.location,
        start_at=event_in.start_at,
        end_at=event_in.end_at,
        all_day=event_in.all_day,
        recurrence=recurrence_json,
    )
    session.add(event)
    await session.flush()
    # Attendee validation reads event.calendar.initiative_id.
    await session.refresh(event, attribute_names=["calendar"])

    if event_in.attendee_ids:
        await events_service.set_event_attendees(
            session,
            event,
            event_in.attendee_ids,
            guild_context.guild_id,
        )
    if event_in.tag_ids:
        await tags_service.set_entity_tags(
            session,
            tags_service.EXTRA_TAG_LINKS["calendar_event"],
            guild_id=guild_context.guild_id,
            entity_id=event.id,
            tag_ids=event_in.tag_ids,
        )
    if event_in.document_ids:
        await events_service.set_event_documents(
            session,
            event,
            event_in.document_ids,
            guild_context.guild_id,
            current_user.id,
        )

    invite_ids = [
        uid for uid in (event_in.attendee_ids or []) if uid != current_user.id
    ]
    for attendee in await _fetch_users(session, invite_ids):
        await notifications_service.notify_event_invitation(
            session,
            attendee=attendee,
            organizer=current_user,
            event=event,
            guild_id=guild_context.guild_id,
        )

    await session.commit()
    hydrated = await _refetch_event(session, event.id)
    return serialize_calendar_event(hydrated, user_id=current_user.id)


@router.patch("/{event_id}", response_model=CalendarEventRead)
async def update_calendar_event(
    event_id: int,
    event_in: CalendarEventUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> CalendarEventRead:
    """Update a calendar event. Requires write access on the calendar (and on
    the target calendar when moving the event)."""
    event = await _get_event_or_404(
        session, event_id, current_user, guild_context, access="write"
    )

    # Snapshot fields that drive the "updated"/"rescheduled" notification before
    # the in-place mutation below.
    old_title = event.title
    old_location = event.location
    old_all_day = event.all_day
    old_start = event.start_at
    old_end = event.end_at

    updated = False
    update_data = event_in.model_dump(exclude_unset=True)

    if (
        "calendar_id" in update_data
        and update_data["calendar_id"] is not None
        and update_data["calendar_id"] != event.calendar_id
    ):
        # Moving between calendars needs write on the destination too.
        destination = await _get_writable_calendar(
            session, update_data["calendar_id"], current_user, guild_context
        )
        # And the move may not cross the guild/initiative line in either
        # direction: an event carries its attendees, property values and
        # document links, all of which belong to one side of it.
        if (destination.initiative_id is None) != (
            event.calendar.initiative_id is None
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=CalendarEventMessages.CANNOT_CROSS_SCOPE,
            )
        event.calendar_id = update_data["calendar_id"]
        updated = True

    for field in (
        "title",
        "description",
        "location",
        "start_at",
        "end_at",
        "all_day",
    ):
        if field in update_data:
            value = update_data[field]
            if field == "title" and value is not None:
                value = value.strip()
            setattr(event, field, value)
            updated = True

    if "recurrence" in update_data:
        if update_data["recurrence"] is not None:
            event.recurrence = event_in.recurrence.model_dump_json()
        else:
            event.recurrence = None
        updated = True

    # Validate dates after applying partial updates
    if updated:
        if event.end_at < event.start_at:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="end_at must be after start_at",
            )
        event.updated_at = datetime.now(timezone.utc)
        session.add(event)

        # Notify attendees only on meaningful changes (skip pure color/tag edits).
        time_changed = event.start_at != old_start or event.end_at != old_end
        meaningful_change = (
            time_changed
            or event.title != old_title
            or event.location != old_location
            or event.all_day != old_all_day
        )
        if meaningful_change:
            for attendee in event.attendees:
                # Skip the editor and anyone who declined — a declined attendee
                # isn't coming, so reschedules/edits are noise (mirrors the
                # reminder pass, which also skips declined RSVPs).
                if (
                    attendee.user
                    and attendee.user_id != current_user.id
                    and attendee.rsvp_status != RSVPStatus.declined
                ):
                    await notifications_service.notify_event_updated(
                        session,
                        attendee=attendee.user,
                        editor=current_user,
                        event=event,
                        guild_id=guild_context.guild_id,
                        time_changed=time_changed,
                    )

        await session.commit()

    hydrated = await _refetch_event(session, event.id)
    return serialize_calendar_event(hydrated, user_id=current_user.id)


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_calendar_event(
    event_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    """Soft-delete a calendar event. Requires write access on the calendar."""
    from app.services.platform import guilds as guilds_service
    from app.services.tenant.soft_delete import soft_delete_entity

    event = await _get_event_or_404(
        session, event_id, current_user, guild_context, access="write"
    )
    retention_days = await guilds_service.get_guild_retention_days(
        session, guild_context.guild_id
    )
    for attendee in event.attendees:
        # A declined attendee already isn't attending, so skip the cancellation
        # notice for them (consistent with update/reminder notifications).
        if (
            attendee.user
            and attendee.user_id != current_user.id
            and attendee.rsvp_status != RSVPStatus.declined
        ):
            await notifications_service.notify_event_cancelled(
                session,
                attendee=attendee.user,
                canceller=current_user,
                event=event,
                guild_id=guild_context.guild_id,
            )
    await soft_delete_entity(
        session,
        event,
        deleted_by_user_id=current_user.id,
        retention_days=retention_days,
    )
    await session.commit()


# ---------------------------------------------------------------------------
# Attendees
# ---------------------------------------------------------------------------


@router.put("/{event_id}/attendees", response_model=CalendarEventRead)
async def set_attendees(
    event_id: int,
    attendee_ids: List[int],
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> CalendarEventRead:
    """Set attendees. Requires write access on the calendar."""
    event = await _get_event_or_404(
        session, event_id, current_user, guild_context, access="write"
    )
    old_ids = {a.user_id for a in event.attendees}
    await events_service.set_event_attendees(
        session, event, attendee_ids, guild_context.guild_id
    )

    added_ids = [uid for uid in (set(attendee_ids) - old_ids) if uid != current_user.id]
    for attendee in await _fetch_users(session, added_ids):
        await notifications_service.notify_event_invitation(
            session,
            attendee=attendee,
            organizer=current_user,
            event=event,
            guild_id=guild_context.guild_id,
        )

    await session.commit()
    hydrated = await _refetch_event(session, event.id)
    return serialize_calendar_event(hydrated, user_id=current_user.id)


@router.patch("/{event_id}/rsvp", response_model=CalendarEventRead)
async def update_rsvp(
    event_id: int,
    rsvp_in: CalendarEventRSVPUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> CalendarEventRead:
    """Update the current user's RSVP status. Read access on the calendar
    suffices — RSVPing is answering an invitation, not editing the event."""
    event = await _get_event_or_404(session, event_id, current_user, guild_context)

    stmt = select(CalendarEventAttendee).where(
        CalendarEventAttendee.calendar_event_id == event.id,
        CalendarEventAttendee.user_id == current_user.id,
    )
    result = await session.exec(stmt)
    attendee = result.one_or_none()

    if not attendee:
        attendee = CalendarEventAttendee(
            calendar_event_id=event.id,
            user_id=current_user.id,
            guild_id=guild_context.guild_id,
        )

    attendee.rsvp_status = rsvp_in.rsvp_status
    session.add(attendee)

    if event.created_by != current_user.id:
        organizers = await _fetch_users(session, [event.created_by])
        if organizers:
            await notifications_service.notify_event_rsvp(
                session,
                organizer=organizers[0],
                responder=current_user,
                event=event,
                rsvp_status=rsvp_in.rsvp_status,
                guild_id=guild_context.guild_id,
            )

    await session.commit()
    hydrated = await _refetch_event(session, event.id)
    return serialize_calendar_event(hydrated, user_id=current_user.id)


# ---------------------------------------------------------------------------
# Tags & Documents
# ---------------------------------------------------------------------------


@router.put("/{event_id}/documents", response_model=CalendarEventRead)
async def set_documents(
    event_id: int,
    document_ids: List[int],
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> CalendarEventRead:
    event = await _get_event_or_404(
        session, event_id, current_user, guild_context, access="write"
    )
    await events_service.set_event_documents(
        session,
        event,
        document_ids,
        guild_context.guild_id,
        current_user.id,
    )
    await session.commit()
    hydrated = await _refetch_event(session, event.id)
    return serialize_calendar_event(hydrated, user_id=current_user.id)


@router.put("/{event_id}/tags", response_model=CalendarEventRead)
async def set_event_tags(
    event_id: int,
    tags_in: TagSetRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> CalendarEventRead:
    """Set the tags for an event. Replaces all existing tags with the provided
    list. Events are content-level extras (like tasks), so they keep a
    hand-written tag route instead of the generic ``/tools/{tool}`` one."""
    event = await _get_event_or_404(
        session, event_id, current_user, guild_context, access="write"
    )
    await tags_service.set_entity_tags(
        session,
        tags_service.EXTRA_TAG_LINKS["calendar_event"],
        guild_id=guild_context.guild_id,
        entity_id=event.id,
        tag_ids=tags_in.tag_ids,
    )
    event.updated_at = datetime.now(timezone.utc)
    session.add(event)
    await session.commit()
    hydrated = await _refetch_event(session, event.id)
    return serialize_calendar_event(hydrated, user_id=current_user.id)


# ---------------------------------------------------------------------------
# Custom properties
# ---------------------------------------------------------------------------


@router.put("/{event_id}/properties", response_model=CalendarEventRead)
async def set_event_properties(
    event_id: int,
    payload: PropertyValuesSetRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> CalendarEventRead:
    """Replace-all set of property values on an event.

    Mirrors the tasks/documents shape: anyone with write access on the calendar
    (or guild admin) can attach values; cross-initiative definitions return 404
    DEFINITION_NOT_FOUND via the service layer.

    Property definitions belong to an initiative. A guild calendar belongs to
    none, so there are no definitions its events could carry and the request is
    refused; clearing values stays available.
    """
    event = await _get_event_or_404(
        session, event_id, current_user, guild_context, access="write"
    )
    if payload.values and event.calendar.initiative_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=CalendarEventMessages.GUILD_CALENDAR_NO_PROPERTIES,
        )
    await properties_service.set_event_property_values(
        session, event, payload.values, initiative_id=event.calendar.initiative_id
    )
    await session.commit()
    hydrated = await _refetch_event(session, event.id)
    return serialize_calendar_event(hydrated, user_id=current_user.id)
