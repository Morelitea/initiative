"""Reading the audit log back in a test."""

from __future__ import annotations

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.models.platform.audit_event import AuditEvent


async def recorded(
    session: AsyncSession, event_type: AuditEventType
) -> list[AuditEvent]:
    """Every row of ``event_type``, oldest first.

    Read fresh from the database — rows another session committed, the
    request's own in an endpoint test, are loaded rather than remembered —
    without expiring anything else the test holds.
    """
    return list(
        (
            await session.exec(
                select(AuditEvent)
                .where(AuditEvent.event_type == event_type.value)
                .order_by(AuditEvent.id)
                .execution_options(populate_existing=True)
            )
        ).all()
    )
