"""Persistence layer for the delegation-token jti blocklist.

Two operations:

* :func:`record_jti` — insert a fresh row. Surfaces the unique-violation
  on the primary key as :class:`DelegationReplayError` so the caller can
  return 401 cleanly.
* :func:`is_jti_redeemed` — check before doing the work. Used as a fast
  pre-flight so we don't waste cycles loading the user record on a
  token we're about to reject.

Both are idempotent under retry: if a connection drops mid-insert we
either succeed or hit the unique violation, never silently allow a
second redemption.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.auto_delegation_jti import AutoDelegationJti


class DelegationReplayError(Exception):
    """Raised when a delegation jti has already been redeemed."""


async def is_jti_redeemed(session: AsyncSession, jti: str) -> bool:
    """Return ``True`` if ``jti`` is already in the blocklist."""
    existing = (
        await session.exec(
            select(AutoDelegationJti).where(AutoDelegationJti.jti == jti)
        )
    ).one_or_none()
    return existing is not None


async def record_jti(
    session: AsyncSession,
    *,
    jti: str,
    expires_at: datetime,
) -> None:
    """Persist ``jti`` so a second presentation can be rejected.

    Raises :class:`DelegationReplayError` on a unique-violation, which
    can fire if two requests carrying the same token race past the
    pre-flight ``is_jti_redeemed`` check. Either is the correct refuse
    signal — the second presentation should never succeed regardless of
    which branch wins the race.
    """
    session.add(
        AutoDelegationJti(
            jti=jti,
            redeemed_at=datetime.now(timezone.utc),
            expires_at=expires_at,
        )
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise DelegationReplayError(f"jti {jti} already redeemed") from exc
