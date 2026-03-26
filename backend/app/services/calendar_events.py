"""Calendar event service layer — business logic for CRUD and attachments.

Access control is at the initiative level (events_enabled + create_events
permission keys). No per-event DAC — any initiative member with the right
role permission can view/create/edit events.
"""

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.core.messages import CalendarEventMessages
from app.models.calendar_event import (
    CalendarEvent,
    CalendarEventAttendee,
    CalendarEventDocument,
    CalendarEventTag,
)
from app.models.document import Document
from app.models.initiative import Initiative
from app.models.tag import Tag


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
            selectinload(CalendarEvent.attendees)
            .selectinload(CalendarEventAttendee.user),
            selectinload(CalendarEvent.tag_links)
            .selectinload(CalendarEventTag.tag),
            selectinload(CalendarEvent.document_links)
            .selectinload(CalendarEventDocument.document),
            selectinload(CalendarEvent.initiative)
            .selectinload(Initiative.memberships),
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

    Validates that all user IDs are members of the event's initiative.
    """
    if user_ids:
        from app.models.initiative import InitiativeMember
        stmt = select(InitiativeMember.user_id).where(
            InitiativeMember.initiative_id == event.initiative_id,
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

async def set_event_tags(
    session: AsyncSession,
    event: CalendarEvent,
    tag_ids: list[int],
    guild_id: int,
) -> None:
    """Replace all tags on a calendar event. Validates tag_ids belong to guild."""
    if tag_ids:
        tags_stmt = select(Tag).where(Tag.id.in_(tag_ids), Tag.guild_id == guild_id)
        tags_result = await session.exec(tags_stmt)
        valid_tags = tags_result.all()
        valid_tag_ids = {t.id for t in valid_tags}

        invalid_ids = set(tag_ids) - valid_tag_ids
        if invalid_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=CalendarEventMessages.INVALID_TAG_IDS,
            )

    delete_stmt = sa_delete(CalendarEventTag).where(
        CalendarEventTag.calendar_event_id == event.id,
    )
    await session.exec(delete_stmt)

    for tag_id in tag_ids:
        link = CalendarEventTag(calendar_event_id=event.id, tag_id=tag_id)
        session.add(link)


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
