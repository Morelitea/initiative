"""Hourly sweep of expired ``billing_jti_blocklist`` rows.

The blocklist exists to make each billing service JWT one-shot; a row is
dead weight once the JWT's own ``exp`` (mirrored into ``expires_at`` at
redemption) has passed, because an expired token is rejected at envelope
verification before the blocklist is ever consulted. Purging therefore
never re-opens a replay window — it only stops unbounded growth.

Runs on the system engine (``app_admin`` holds SELECT/DELETE on this table
per ``app/db/system_grants.py``); the RLS-scoped billing role itself can
only INSERT, so the janitor cannot run — and must not run — as the boundary
role. Registered in ``app.services.background_tasks``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlmodel import delete
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.billing import BillingJti

logger = logging.getLogger(__name__)

BILLING_JTI_PURGE_POLL_SECONDS = 3600


async def purge_expired_billing_jtis(session: AsyncSession) -> int:
    """Delete blocklist rows whose ``expires_at`` has passed; returns the
    number purged. Commits (unlike the billing service module, whose
    operations share the endpoint transaction, the janitor owns its own)."""
    result = await session.exec(
        delete(BillingJti).where(BillingJti.expires_at < datetime.now(timezone.utc))
    )
    await session.commit()
    purged = result.rowcount or 0
    if purged:
        logger.info("billing: purged %s expired jti blocklist rows", purged)
    return purged


async def process_billing_jti_purge() -> None:
    from app.db.session import AdminSessionLocal

    async with AdminSessionLocal() as session:
        await purge_expired_billing_jtis(session)
