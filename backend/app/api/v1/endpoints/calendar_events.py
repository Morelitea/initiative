"""Calendar event endpoints — CRUD, attendees, tags, and documents.

Initiative-scoped calendar events. Access is controlled at the initiative
level via events_enabled + create_events permission keys. No per-event DAC.
"""

import logging
from datetime import datetime, timezone
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.api.deps import (
    RLSSessionDep,
    get_current_active_user,
    get_guild_membership,
    GuildContext,
)
from app.db.session import get_admin_session, reapply_rls_context
from app.models.calendar_event import (
    CalendarEvent,
    CalendarEventAttendee,
)
from app.models.guild import GuildMembership
from app.models.initiative import Initiative, PermissionKey
from app.models.user import User
from app.core.messages import CalendarEventMessages, InitiativeMessages
from app.schemas.calendar_event import (
    CalendarEventCreate,
    CalendarEventUpdate,
    CalendarEventRead,
    CalendarEventListResponse,
    CalendarEventRSVPUpdate,
    serialize_calendar_event,
    serialize_calendar_event_summary,
)
from app.schemas.ical import ICalImportRequest, ICalImportResult, ICalParseRequest, ICalParseResult
from app.services import calendar_events as events_service
from app.services import ical_service
from app.services import rls as rls_service

router = APIRouter()
logger = logging.getLogger(__name__)

AdminSessionDep = Annotated[AsyncSession, Depends(get_admin_session)]

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_initiative_for_event(
    session: RLSSessionDep,
    initiative_id: int,
) -> Initiative:
    stmt = (
        select(Initiative)
        .where(Initiative.id == initiative_id)
        .options(
            selectinload(Initiative.memberships),
            selectinload(Initiative.roles),
        )
    )
    result = await session.exec(stmt)
    initiative = result.one_or_none()
    if not initiative:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=InitiativeMessages.NOT_FOUND,
        )
    return initiative


async def _check_initiative_permission(
    session: RLSSessionDep,
    initiative: Initiative,
    user: User,
    guild_context: GuildContext,
    permission_key: PermissionKey,
) -> None:
    if rls_service.is_guild_admin(guild_context.role):
        return
    has_perm = await rls_service.check_initiative_permission(
        session,
        initiative_id=initiative.id,
        user=user,
        permission_key=permission_key,
    )
    if not has_perm:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=CalendarEventMessages.CREATE_PERMISSION_REQUIRED,
        )


async def _get_event_or_404(
    session: RLSSessionDep,
    event_id: int,
) -> CalendarEvent:
    event = await events_service.get_event(session, event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=CalendarEventMessages.NOT_FOUND,
        )
    if event.initiative and not event.initiative.events_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=CalendarEventMessages.FEATURE_DISABLED,
        )
    return event


async def _refetch_event(session: RLSSessionDep, event_id: int) -> CalendarEvent:
    event = await events_service.get_event(session, event_id, populate_existing=True)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=CalendarEventMessages.NOT_FOUND,
        )
    return event


# ---------------------------------------------------------------------------
# Cross-guild global view
# ---------------------------------------------------------------------------


@router.get("/global", response_model=CalendarEventListResponse)
async def list_global_calendar_events(
    session: AdminSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_ids: Optional[List[int]] = Query(default=None),
    start_after: Optional[datetime] = Query(default=None),
    start_before: Optional[datetime] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=200, ge=1, le=200),
) -> CalendarEventListResponse:
    """List calendar events across all guilds the user belongs to.

    Uses AdminSessionDep (bypasses RLS) because this endpoint manually
    filters by the user's guild memberships — same pattern as global tasks.
    """
    # Base conditions: user must be a guild member and events must be enabled
    conditions = [
        GuildMembership.user_id == current_user.id,
        Initiative.events_enabled == True,  # noqa: E712
    ]

    # If specific guild_ids requested, intersect with user's memberships
    if guild_ids:
        conditions.append(CalendarEvent.guild_id.in_(tuple(guild_ids)))

    if start_after is not None:
        conditions.append(CalendarEvent.start_at >= start_after)
    if start_before is not None:
        conditions.append(CalendarEvent.start_at <= start_before)

    def _base_query(stmt):  # type: ignore[no-untyped-def]
        return (
            stmt
            .join(Initiative, Initiative.id == CalendarEvent.initiative_id)
            .join(
                GuildMembership,
                GuildMembership.guild_id == CalendarEvent.guild_id,
            )
            .where(*conditions)
        )

    # Count
    count_subq = _base_query(select(CalendarEvent.id)).subquery()
    count_stmt = select(func.count()).select_from(count_subq)
    total_count = (await session.execute(count_stmt)).scalar_one()

    # Data
    stmt = _base_query(select(CalendarEvent)).options(
        selectinload(CalendarEvent.attendees).selectinload(
            CalendarEventAttendee.user,
        ),
        selectinload(CalendarEvent.initiative),
    ).order_by(
        CalendarEvent.start_at.asc(),
        CalendarEvent.id.asc(),
    ).offset(
        (page - 1) * page_size,
    ).limit(page_size)

    result = await session.execute(stmt)
    events = result.unique().scalars().all()

    items = [serialize_calendar_event_summary(e) for e in events]
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


@router.get("/export.ics")
async def export_calendar_events_ics(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    initiative_id: Optional[int] = Query(default=None),
    start_after: Optional[datetime] = Query(default=None),
    start_before: Optional[datetime] = Query(default=None),
) -> Response:
    """Export guild-scoped calendar events as an .ics file."""
    conditions = [CalendarEvent.guild_id == guild_context.guild_id]
    if initiative_id is not None:
        conditions.append(CalendarEvent.initiative_id == initiative_id)
    else:
        conditions.append(
            CalendarEvent.initiative_id.in_(
                select(Initiative.id).where(Initiative.events_enabled == True)  # noqa: E712
            )
        )
    if start_after is not None:
        conditions.append(CalendarEvent.start_at >= start_after)
    if start_before is not None:
        conditions.append(CalendarEvent.start_at <= start_before)

    stmt = (
        select(CalendarEvent)
        .where(*conditions)
        .options(
            selectinload(CalendarEvent.attendees).selectinload(CalendarEventAttendee.user),
        )
        .order_by(CalendarEvent.start_at.asc())
    )
    result = await session.exec(stmt)
    events = result.unique().all()

    ics_bytes = ical_service.events_to_ical(list(events))
    return Response(
        content=ics_bytes,
        media_type="text/calendar",
        headers={"Content-Disposition": "attachment; filename=events.ics"},
    )


@router.get("/global/export.ics")
async def export_global_calendar_events_ics(
    session: AdminSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_ids: Optional[List[int]] = Query(default=None),
    start_after: Optional[datetime] = Query(default=None),
    start_before: Optional[datetime] = Query(default=None),
) -> Response:
    """Export cross-guild calendar events as an .ics file."""
    conditions = [
        GuildMembership.user_id == current_user.id,
        Initiative.events_enabled == True,  # noqa: E712
    ]
    if guild_ids:
        conditions.append(CalendarEvent.guild_id.in_(tuple(guild_ids)))
    if start_after is not None:
        conditions.append(CalendarEvent.start_at >= start_after)
    if start_before is not None:
        conditions.append(CalendarEvent.start_at <= start_before)

    stmt = (
        select(CalendarEvent)
        .join(Initiative, Initiative.id == CalendarEvent.initiative_id)
        .join(GuildMembership, GuildMembership.guild_id == CalendarEvent.guild_id)
        .where(*conditions)
        .options(
            selectinload(CalendarEvent.attendees).selectinload(CalendarEventAttendee.user),
        )
        .order_by(CalendarEvent.start_at.asc())
    )
    result = await session.execute(stmt)
    events = result.unique().scalars().all()

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
    """Import events from an .ics file into an initiative."""
    initiative = await _get_initiative_for_event(session, body.initiative_id)
    await _check_initiative_permission(
        session, initiative, current_user, guild_context, PermissionKey.create_events,
    )

    try:
        events, errors = ical_service.build_calendar_events(
            content=body.ics_content,
            initiative_id=body.initiative_id,
            guild_id=guild_context.guild_id,
            created_by_id=current_user.id,
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
        await reapply_rls_context(session)

    return ICalImportResult(
        events_created=created,
        events_failed=len(events) - created,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.get("/", response_model=CalendarEventListResponse)
async def list_calendar_events(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    initiative_id: Optional[int] = Query(default=None),
    start_after: Optional[datetime] = Query(default=None),
    start_before: Optional[datetime] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> CalendarEventListResponse:
    """List calendar events. RLS + initiative membership handle access."""
    conditions = [CalendarEvent.guild_id == guild_context.guild_id]

    if initiative_id is not None:
        initiative = await session.get(Initiative, initiative_id)
        if initiative and not initiative.events_enabled:
            return CalendarEventListResponse(
                items=[], total_count=0, page=page, page_size=page_size, has_next=False,
            )
        conditions.append(CalendarEvent.initiative_id == initiative_id)
    else:
        conditions.append(
            CalendarEvent.initiative_id.in_(
                select(Initiative.id).where(Initiative.events_enabled == True)  # noqa: E712
            )
        )

    if start_after is not None:
        conditions.append(CalendarEvent.start_at >= start_after)
    if start_before is not None:
        conditions.append(CalendarEvent.start_at <= start_before)

    count_subq = select(CalendarEvent.id).where(*conditions).subquery()
    count_stmt = select(func.count()).select_from(count_subq)
    total_count = (await session.exec(count_stmt)).one()

    stmt = (
        select(CalendarEvent)
        .where(*conditions)
        .options(
            selectinload(CalendarEvent.attendees).selectinload(CalendarEventAttendee.user),
            selectinload(CalendarEvent.initiative).selectinload(Initiative.memberships),
        )
        .order_by(CalendarEvent.start_at.asc(), CalendarEvent.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await session.exec(stmt)
    events = result.unique().all()

    items = [serialize_calendar_event_summary(e) for e in events]
    has_next = page * page_size < total_count
    return CalendarEventListResponse(
        items=items, total_count=total_count, page=page, page_size=page_size, has_next=has_next,
    )


@router.get("/{event_id}", response_model=CalendarEventRead)
async def read_calendar_event(
    event_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> CalendarEventRead:
    event = await _get_event_or_404(session, event_id)
    return serialize_calendar_event(event)


@router.post("/", response_model=CalendarEventRead, status_code=status.HTTP_201_CREATED)
async def create_calendar_event(
    event_in: CalendarEventCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> CalendarEventRead:
    """Create a calendar event. Requires create_events permission."""
    initiative = await _get_initiative_for_event(session, event_in.initiative_id)
    if not initiative.events_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=CalendarEventMessages.FEATURE_DISABLED,
        )
    await _check_initiative_permission(
        session, initiative, current_user, guild_context, PermissionKey.create_events,
    )

    recurrence_json = None
    if event_in.recurrence:
        recurrence_json = event_in.recurrence.model_dump_json()

    event = CalendarEvent(
        guild_id=guild_context.guild_id,
        initiative_id=initiative.id,
        created_by_id=current_user.id,
        title=event_in.title.strip(),
        description=event_in.description,
        location=event_in.location,
        start_at=event_in.start_at,
        end_at=event_in.end_at,
        all_day=event_in.all_day,
        color=event_in.color,
        recurrence=recurrence_json,
    )
    session.add(event)
    await session.flush()

    if event_in.attendee_ids:
        await events_service.set_event_attendees(
            session, event, event_in.attendee_ids, guild_context.guild_id,
        )
    if event_in.tag_ids:
        await events_service.set_event_tags(
            session, event, event_in.tag_ids, guild_context.guild_id,
        )
    if event_in.document_ids:
        await events_service.set_event_documents(
            session, event, event_in.document_ids, guild_context.guild_id, current_user.id,
        )

    await session.commit()
    await reapply_rls_context(session)
    hydrated = await _refetch_event(session, event.id)
    return serialize_calendar_event(hydrated)


@router.patch("/{event_id}", response_model=CalendarEventRead)
async def update_calendar_event(
    event_id: int,
    event_in: CalendarEventUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> CalendarEventRead:
    """Update a calendar event. Requires create_events permission on the initiative."""
    event = await _get_event_or_404(session, event_id)
    await _check_initiative_permission(
        session,
        await _get_initiative_for_event(session, event.initiative_id),
        current_user,
        guild_context,
        PermissionKey.create_events,
    )

    updated = False
    update_data = event_in.model_dump(exclude_unset=True)

    for field in ("title", "description", "location", "start_at", "end_at", "all_day", "color"):
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
        if not event.all_day:
            from datetime import timedelta
            if (event.end_at - event.start_at) > timedelta(hours=24):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Non-all-day events cannot span more than 24 hours",
                )
        event.updated_at = datetime.now(timezone.utc)
        session.add(event)
        await session.commit()
        await reapply_rls_context(session)

    hydrated = await _refetch_event(session, event.id)
    return serialize_calendar_event(hydrated)


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_calendar_event(
    event_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    """Delete a calendar event. Requires create_events permission or guild admin."""
    event = await _get_event_or_404(session, event_id)
    await _check_initiative_permission(
        session,
        await _get_initiative_for_event(session, event.initiative_id),
        current_user,
        guild_context,
        PermissionKey.create_events,
    )
    await session.delete(event)
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
    """Set attendees. Requires create_events permission."""
    event = await _get_event_or_404(session, event_id)
    await _check_initiative_permission(
        session,
        await _get_initiative_for_event(session, event.initiative_id),
        current_user,
        guild_context,
        PermissionKey.create_events,
    )
    await events_service.set_event_attendees(session, event, attendee_ids, guild_context.guild_id)
    await session.commit()
    await reapply_rls_context(session)
    hydrated = await _refetch_event(session, event.id)
    return serialize_calendar_event(hydrated)


@router.patch("/{event_id}/rsvp", response_model=CalendarEventRead)
async def update_rsvp(
    event_id: int,
    rsvp_in: CalendarEventRSVPUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> CalendarEventRead:
    """Update the current user's RSVP status. Any initiative member can RSVP."""
    event = await _get_event_or_404(session, event_id)

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
    await session.commit()
    await reapply_rls_context(session)
    hydrated = await _refetch_event(session, event.id)
    return serialize_calendar_event(hydrated)


# ---------------------------------------------------------------------------
# Tags & Documents
# ---------------------------------------------------------------------------


@router.put("/{event_id}/tags", response_model=CalendarEventRead)
async def set_tags(
    event_id: int,
    tag_ids: List[int],
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> CalendarEventRead:
    event = await _get_event_or_404(session, event_id)
    await _check_initiative_permission(
        session,
        await _get_initiative_for_event(session, event.initiative_id),
        current_user,
        guild_context,
        PermissionKey.create_events,
    )
    await events_service.set_event_tags(session, event, tag_ids, guild_context.guild_id)
    await session.commit()
    await reapply_rls_context(session)
    hydrated = await _refetch_event(session, event.id)
    return serialize_calendar_event(hydrated)


@router.put("/{event_id}/documents", response_model=CalendarEventRead)
async def set_documents(
    event_id: int,
    document_ids: List[int],
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> CalendarEventRead:
    event = await _get_event_or_404(session, event_id)
    await _check_initiative_permission(
        session,
        await _get_initiative_for_event(session, event.initiative_id),
        current_user,
        guild_context,
        PermissionKey.create_events,
    )
    await events_service.set_event_documents(
        session, event, document_ids, guild_context.guild_id, current_user.id,
    )
    await session.commit()
    await reapply_rls_context(session)
    hydrated = await _refetch_event(session, event.id)
    return serialize_calendar_event(hydrated)
