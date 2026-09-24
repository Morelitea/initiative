"""Managing the deployment's app publishers.

A publisher is the ``<prefix>`` half of every ``<prefix>.<slug>`` app id this
deployment registers (:mod:`app.models.platform.publisher`). Three ways a row
arrives:

* **Boot seeds this project's own publisher** (:func:`seed_publishers`), once;
  a restart never changes a row that exists, so an operator's switch stays
  where they left it.
* **An operator adds one** through the ``apps.manage`` endpoints, for a
  private app's prefix.
* **A registration names a prefix no row has yet**, and one is added for it,
  unverified and enabled (:func:`ensure_publisher`). Whoever registered the
  app chose its prefix, so the row records that choice rather than refusing it.

Every write drops the registration snapshot, because a publisher's switch is
part of whether each of its registrations is live.

Everything here runs on the system engine: ``publishers`` has no request-path
write grant.
"""

from __future__ import annotations

import logging
from typing import Optional, Sequence

from fastapi import HTTPException, status as http_status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.messages import AppServiceMessages
from app.models.platform.publisher import (
    FIRST_PARTY_PUBLISHER_NAME,
    FIRST_PARTY_PUBLISHER_PREFIX,
    PUBLISHER_PREFIX_MAX_LENGTH,
    Publisher,
)
from app.services import audit as audit_service
from app.services.marketplace.registration_lookup import invalidate_registrations

logger = logging.getLogger(__name__)

__all__ = [
    "AUDITED_FIELDS",
    "create_publisher",
    "ensure_publisher",
    "get_publisher",
    "list_publishers",
    "normalize_display_name",
    "normalize_prefix",
    "seed_publishers",
    "update_publisher",
]

#: What a publisher record says, for the audit log.
AUDITED_FIELDS: tuple[str, ...] = ("prefix", "display_name", "verified", "enabled")

#: Characters a prefix may use: the ``public_id`` alphabet without the dot
#: that separates the prefix from the slug.
_PREFIX_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-_")
_MAX_DISPLAY_NAME = 200


def _bad_request(code: str) -> HTTPException:
    return HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=code)


def normalize_prefix(value: str) -> str:
    cleaned = (value or "").strip().lower()
    if not cleaned or len(cleaned) > PUBLISHER_PREFIX_MAX_LENGTH:
        raise _bad_request(AppServiceMessages.INVALID_PUBLISHER_PREFIX)
    if any(char not in _PREFIX_CHARS for char in cleaned):
        raise _bad_request(AppServiceMessages.INVALID_PUBLISHER_PREFIX)
    return cleaned


def normalize_display_name(value: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned or len(cleaned) > _MAX_DISPLAY_NAME:
        raise _bad_request(AppServiceMessages.INVALID_PUBLISHER_NAME)
    return cleaned


async def list_publishers(session: AsyncSession) -> Sequence[Publisher]:
    result = await session.exec(select(Publisher).order_by(Publisher.prefix.asc()))
    return result.all()


async def get_publisher(session: AsyncSession, publisher_id: int) -> Publisher:
    row = await session.get(Publisher, publisher_id)
    if row is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=AppServiceMessages.PUBLISHER_NOT_FOUND,
        )
    return row


async def _by_prefix(session: AsyncSession, prefix: str) -> Optional[Publisher]:
    return (
        await session.exec(select(Publisher).where(Publisher.prefix == prefix))
    ).first()


async def create_publisher(
    session: AsyncSession,
    *,
    prefix: str,
    display_name: str,
    enabled: bool = True,
    actor_user_id: int | None = None,
) -> Publisher:
    """Add a publisher for a prefix. Unverified: the operator is recording a
    local publisher, not confirming who one is."""
    cleaned = normalize_prefix(prefix)
    name = normalize_display_name(display_name)
    if await _by_prefix(session, cleaned) is not None:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=AppServiceMessages.DUPLICATE_PUBLISHER,
        )
    row = Publisher(prefix=cleaned, display_name=name, verified=False, enabled=enabled)
    session.add(row)
    await session.flush()
    await audit_service.record(
        session,
        event_type=AuditEventType.APP_PUBLISHER_CREATED,
        actor_user_id=actor_user_id,
        target_type="app_publisher",
        target_id=row.id,
        detail=audit_service.changed_fields(
            {}, audit_service.snapshot(row, AUDITED_FIELDS)
        ),
    )
    await session.commit()
    await session.refresh(row)
    invalidate_registrations()
    return row


async def update_publisher(
    session: AsyncSession,
    publisher_id: int,
    *,
    display_name: Optional[str] = None,
    enabled: Optional[bool] = None,
    actor_user_id: int | None = None,
) -> Publisher:
    """Rename a publisher, or switch it on or off. Off makes every
    registration under its prefix not live."""
    row = await get_publisher(session, publisher_id)
    before = audit_service.snapshot(row, AUDITED_FIELDS)
    if display_name is not None:
        row.display_name = normalize_display_name(display_name)
    if enabled is not None:
        row.enabled = enabled
    session.add(row)
    changed = audit_service.changed_fields(
        before, audit_service.snapshot(row, AUDITED_FIELDS)
    )
    if changed["changed"]:
        await audit_service.record(
            session,
            event_type=AuditEventType.APP_PUBLISHER_UPDATED,
            actor_user_id=actor_user_id,
            target_type="app_publisher",
            target_id=row.id,
            detail=changed,
        )
    await session.commit()
    await session.refresh(row)
    invalidate_registrations()
    return row


async def ensure_publisher(session: AsyncSession, prefix: str) -> Publisher:
    """The publisher for ``prefix``, added unverified and enabled when there is
    none. An existing row is returned as it is, whatever its switch says.

    Flushed, not committed: the caller's registration write commits both.
    """
    cleaned = normalize_prefix(prefix)
    row = await _by_prefix(session, cleaned)
    if row is not None:
        return row
    row = Publisher(prefix=cleaned, display_name=cleaned, verified=False, enabled=True)
    session.add(row)
    await session.flush()
    await audit_service.record(
        session,
        event_type=AuditEventType.APP_PUBLISHER_CREATED,
        actor_user_id=None,
        target_type="app_publisher",
        target_id=row.id,
        detail={
            "via": "registration",
            **audit_service.changed_fields(
                {}, audit_service.snapshot(row, AUDITED_FIELDS)
            ),
        },
    )
    return row


async def seed_publishers(session: AsyncSession) -> bool:
    """Add this project's own publisher when the deployment has none for its
    prefix. Returns whether a row was added; an existing row is left alone."""
    if await _by_prefix(session, FIRST_PARTY_PUBLISHER_PREFIX) is not None:
        return False
    row = Publisher(
        prefix=FIRST_PARTY_PUBLISHER_PREFIX,
        display_name=FIRST_PARTY_PUBLISHER_NAME,
        verified=True,
        enabled=True,
    )
    session.add(row)
    await session.flush()
    await audit_service.record(
        session,
        event_type=AuditEventType.APP_PUBLISHER_CREATED,
        actor_user_id=None,
        target_type="app_publisher",
        target_id=row.id,
        detail={
            "via": "seed",
            **audit_service.changed_fields(
                {}, audit_service.snapshot(row, AUDITED_FIELDS)
            ),
        },
    )
    await session.commit()
    invalidate_registrations()
    return True
