"""Calendar event service layer — business logic for CRUD and attachments.

Events hold no grants of their own: access derives from the parent calendar's
DAC (``resource_type='calendar'``), the way tasks inherit project access. The
loaders here eager-load the parent calendar with what the permission engine
needs.
"""

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import delete as sa_delete
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.core.messages import CalendarEventMessages
from app.models.tenant.calendar import Calendar
from app.models.tenant.calendar_event import (
    CalendarEvent,
    CalendarEventAttendee,
    CalendarEventDocument,
    CalendarEventTag,
)
from app.models.tenant.document import Document
from app.models.tenant.initiative import Initiative
from app.models.tenant.property import CalendarEventPropertyValue
from app.models.tenant.resource_grant import ResourceGrant


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


async def get_event(
    session: AsyncSession,
    event_id: int,
    *,
    populate_existing: bool = False,
) -> CalendarEvent | None:
    """Fetch a calendar event with all relationships loaded."""
    stmt = (
        select(CalendarEvent)
        .where(CalendarEvent.id == event_id)
        .options(
            selectinload(CalendarEvent.attendees).selectinload(
                CalendarEventAttendee.user
            ),
            selectinload(CalendarEvent.tag_links).selectinload(CalendarEventTag.tag),
            selectinload(CalendarEvent.document_links).selectinload(
                CalendarEventDocument.document
            ),
            selectinload(CalendarEvent.calendar)
            .selectinload(Calendar.grants)
            .selectinload(ResourceGrant.role),
            selectinload(CalendarEvent.calendar)
            .selectinload(Calendar.initiative)
            .selectinload(Initiative.memberships),
            selectinload(CalendarEvent.property_values).selectinload(
                CalendarEventPropertyValue.property_definition
            ),
            selectinload(CalendarEvent.property_values).selectinload(
                CalendarEventPropertyValue.value_user
            ),
        )
    )
    if populate_existing:
        stmt = stmt.execution_options(populate_existing=True)
    result = await session.exec(stmt)
    return result.one_or_none()


# ---------------------------------------------------------------------------
# Attendee helpers
# ---------------------------------------------------------------------------


async def set_event_attendees(
    session: AsyncSession,
    event: CalendarEvent,
    user_ids: list[int],
    guild_id: int,
) -> None:
    """Replace all attendees on a calendar event.

    Validates that all user IDs are members of the calendar's initiative.
    Requires ``event.calendar`` to be eager-loaded.
    """
    if user_ids:
        from app.models.tenant.initiative import InitiativeMember

        stmt = select(InitiativeMember.user_id).where(
            InitiativeMember.initiative_id == event.calendar.initiative_id,
            InitiativeMember.user_id.in_(user_ids),
        )
        result = await session.exec(stmt)
        valid_ids = set(result.all())
        invalid = set(user_ids) - valid_ids
        if invalid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=CalendarEventMessages.INVALID_ATTENDEE_IDS,
            )

    delete_stmt = sa_delete(CalendarEventAttendee).where(
        CalendarEventAttendee.calendar_event_id == event.id,
    )
    await session.exec(delete_stmt)

    for user_id in user_ids:
        attendee = CalendarEventAttendee(
            calendar_event_id=event.id,
            user_id=user_id,
            guild_id=guild_id,
        )
        session.add(attendee)


# ---------------------------------------------------------------------------
# Tag / document attachment helpers
# ---------------------------------------------------------------------------


async def set_event_documents(
    session: AsyncSession,
    event: CalendarEvent,
    document_ids: list[int],
    guild_id: int,
    user_id: int,
) -> None:
    """Replace all document links on a calendar event."""
    if document_ids:
        docs_stmt = select(Document.id).where(
            Document.id.in_(document_ids),
            Document.guild_id == guild_id,
        )
        docs_result = await session.exec(docs_stmt)
        valid_ids = set(docs_result.all())

        missing = set(document_ids) - valid_ids
        if missing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=CalendarEventMessages.NOT_FOUND,
            )

    delete_stmt = sa_delete(CalendarEventDocument).where(
        CalendarEventDocument.calendar_event_id == event.id,
    )
    await session.exec(delete_stmt)

    now = datetime.now(timezone.utc)
    for doc_id in document_ids:
        link = CalendarEventDocument(
            calendar_event_id=event.id,
            document_id=doc_id,
            guild_id=guild_id,
            attached_by_id=user_id,
            attached_at=now,
        )
        session.add(link)
