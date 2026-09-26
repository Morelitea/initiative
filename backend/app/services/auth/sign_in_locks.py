"""Wrong passwords and codes, counted per account.

Five wrong answers within fifteen minutes lock the account's password and codes
for fifteen minutes. Three locks within a day turn into a hold, which stays
until a moderator lifts it. Passkeys and sessions already open are not
affected by either.

Every function here stages its writes on the caller's system-engine session;
the caller commits.
"""

from __future__ import annotations

import enum
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.models.platform.sign_in_lock import SignInLock
from app.services import audit as audit_service
from app.core.clock import utcnow

LOCK_AFTER_FAILURES = 5
FAILURE_WINDOW = timedelta(minutes=15)
LOCK_FOR = timedelta(minutes=15)
HOLD_AFTER_LOCKS = 3
LOCK_WINDOW = timedelta(hours=24)
#: The holder is emailed about a lock at most this often. A hold is always
#: emailed.
NOTIFY_AT_MOST_EVERY = timedelta(hours=1)


class Outcome(enum.Enum):
    counted = "counted"
    locked = "locked"
    held = "held"


@dataclass(frozen=True)
class Failure:
    """What one wrong answer did, and whether to tell the holder."""

    outcome: Outcome
    notify: bool


async def _row_for_update(session: AsyncSession, user_id: int) -> SignInLock:
    """The account's row, created if missing, locked for this transaction."""
    # The re-read below replaces the loaded row, so anything staged on it goes
    # to the database first.
    await session.flush()
    await session.exec(
        pg_insert(SignInLock)
        .values(user_id=user_id, failures=0, locks=0)
        .on_conflict_do_nothing(index_elements=["user_id"])
    )
    result = await session.exec(
        select(SignInLock)
        .where(SignInLock.user_id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return result.one()


def _is_closed(row: SignInLock | None, now: datetime) -> bool:
    if row is None:
        return False
    if row.held_at is not None:
        return True
    return row.locked_until is not None and row.locked_until > now


async def is_locked(session: AsyncSession, user_id: int) -> bool:
    """Whether password and codes are refused for this account right now."""
    return _is_closed(await session.get(SignInLock, user_id), utcnow())


async def record_failure(session: AsyncSession, user_id: int) -> Failure:
    """Count one wrong answer, and place a lock or a hold if it is due."""
    now = utcnow()
    row = await _row_for_update(session, user_id)
    if _is_closed(row, now):
        # Refused before anything was checked; nothing more to count.
        return Failure(Outcome.counted, notify=False)

    if row.first_failure_at is None or now - row.first_failure_at > FAILURE_WINDOW:
        row.failures = 0
        row.first_failure_at = now
    row.failures += 1

    if row.failures < LOCK_AFTER_FAILURES:
        session.add(row)
        return Failure(Outcome.counted, notify=False)

    row.failures = 0
    row.first_failure_at = None
    if row.first_lock_at is None or now - row.first_lock_at > LOCK_WINDOW:
        row.locks = 0
        row.first_lock_at = now
    row.locks += 1

    if row.locks >= HOLD_AFTER_LOCKS:
        row.held_at = now
        row.locked_until = None
        outcome, notify = Outcome.held, True
        event = AuditEventType.AUTH_SIGN_IN_HELD
    else:
        row.locked_until = now + LOCK_FOR
        outcome = Outcome.locked
        notify = row.notified_at is None or now - row.notified_at >= (
            NOTIFY_AT_MOST_EVERY
        )
        event = AuditEventType.AUTH_SIGN_IN_LOCKED
    if notify:
        row.notified_at = now
    session.add(row)

    await audit_service.record(
        session,
        event_type=event,
        actor_user_id=None,
        target_user_id=user_id,
        target_type="user",
        target_id=user_id,
        detail={"locks": row.locks},
    )
    return Failure(outcome, notify=notify)


async def record_success(session: AsyncSession, user_id: int) -> None:
    """Start the count over: the account's holder has just signed in.

    Locks already placed still count toward a hold, and a hold stays.
    """
    row = await session.get(SignInLock, user_id)
    if row is None or row.failures == 0:
        return
    row.failures = 0
    row.first_failure_at = None
    session.add(row)


async def lift(session: AsyncSession, user_id: int) -> bool:
    """Clear everything counted against the account. True if it was locked or
    held."""
    was_closed = _is_closed(await session.get(SignInLock, user_id), utcnow())
    await session.exec(delete(SignInLock).where(SignInLock.user_id == user_id))
    return was_closed


async def closed(
    session: AsyncSession, user_ids: Sequence[int]
) -> dict[int, SignInLock]:
    """The rows of those of these accounts whose password and codes are turned
    off right now."""
    if not user_ids:
        return {}
    result = await session.exec(
        select(SignInLock).where(
            SignInLock.user_id.in_(user_ids)  # type: ignore[attr-defined]
        )
    )
    now = utcnow()
    return {row.user_id: row for row in result.all() if _is_closed(row, now)}
