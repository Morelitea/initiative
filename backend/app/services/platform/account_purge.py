"""Erase accounts whose retention window has run out.

Asking for an account to go no longer erases it: it moves to
``UserStatus.deleted`` and keeps everything — the row, its personal data, its
memberships, its initiative roles, the documents it owns — so the person can
come back. Signing in is what brings them back; this worker is what happens if
they do not.

What it runs at the end is :func:`~app.services.platform.users.soft_delete_user`,
unchanged: the erasure that used to happen the moment somebody pressed the
button. Not ``hard_delete_user`` — anonymizing keeps the row, so the work the
account touched still tells one departed author from another.

Polled by ``background_tasks._loop_worker`` once an hour on
``SystemSessionLocal`` (the ``app_admin`` login). ``soft_delete_user`` routes
into each guild schema itself to scrub mention markup, so there is nothing to
route here.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import SystemSessionLocal, set_rls_context
from app.models.platform.user import User, UserStatus


logger = logging.getLogger(__name__)


ACCOUNT_PURGE_POLL_SECONDS = 3600


def erase_at(requested_at: datetime, retention_days: int) -> datetime:
    """When an account asked for at ``requested_at`` is erased."""
    return requested_at + timedelta(days=retention_days)


async def retention_days(session: AsyncSession) -> int | None:
    """This deployment's window, or None where it keeps deleted accounts.

    Read per sweep rather than cached: an operator who has just turned the
    window off is asking for the next sweep to erase nobody, and a figure read
    at import would erase somebody first.
    """
    from app.services.platform import app_settings as app_settings_service

    row = await app_settings_service.get_app_settings(session)
    return row.deleted_account_retention_days


async def _due_user_ids(
    session: AsyncSession, *, now: datetime, retention: int
) -> list[int]:
    """Accounts whose window has run out, oldest request first.

    A ``deleted`` row with no ``status_changed_at`` cannot happen — the request
    stamps it in the same write — and is skipped rather than treated as
    infinitely old, because "no request time" must never read as "erase now".
    """
    cutoff = now - timedelta(days=retention)
    rows = await session.exec(
        select(User.id)
        .where(
            User.status == UserStatus.deleted,
            User.status_changed_at.is_not(None),
            User.status_changed_at <= cutoff,
        )
        .order_by(User.status_changed_at.asc())
    )
    return list(rows.all())


async def _claim(session: AsyncSession, user_id: int) -> bool:
    """Take one account for this sweep, or learn it is not ours to erase.

    A row lock on the account, held by the erasure's own transaction until it
    commits, and re-asking that it is still waiting: another process sweeping
    at the same moment skips it, and one that arrives after the commit finds it
    already erased. Each account is erased — and its receipt sent — once.
    """
    claimed = (
        await session.exec(
            select(User.id)
            .where(User.id == user_id, User.status == UserStatus.deleted)
            .with_for_update(skip_locked=True)
        )
    ).first()
    return claimed is not None


async def purge_due_accounts(session: AsyncSession, *, now: datetime) -> int:
    """One pass. Returns how many accounts were erased.

    Split out from the loop entry point so tests can drive it with the test
    session and a chosen ``now``.

    Each account is erased on its own, and a failure on one is logged and
    stepped over: an account whose erasure faults must not stop the queue
    behind it, and the next sweep tries it again.
    """
    await set_rls_context(session)
    retention = await retention_days(session)
    if retention is None:
        # This deployment keeps deleted accounts. Nothing is erased on a timer.
        return 0
    user_ids = await _due_user_ids(session, now=now, retention=retention)
    erased = 0
    for user_id in user_ids:
        # ids collide across guild schemas, and soft_delete_user visits all of
        # them, so the identity map is cleared between accounts.
        session.expunge_all()
        try:
            # Imported here rather than at module scope: ``users`` reaches back
            # into this package, and the two would import each other.
            from app.services.platform import users as users_service

            if not await _claim(session, user_id):
                continue
            await users_service.soft_delete_user(session, user_id, actor_user_id=None)
        except Exception:
            await session.rollback()
            logger.exception(
                "account purge: erasing account %s failed; left for the next sweep",
                user_id,
            )
            continue
        erased += 1
    if erased:
        logger.info("account purge: erased %d account(s)", erased)
    return erased


async def process_account_purges() -> None:
    """One pass of the account-purge loop. Idempotent and safe to run on a
    schedule even when nothing is due."""
    now = datetime.now(timezone.utc)
    async with SystemSessionLocal() as session:
        await purge_due_accounts(session, now=now)
