"""The community's change log: ``event_outbox``, which the capture trigger
writes, and ``plugin_event_outbox``, which installed plug-ins write.

Webhook delivery and the realtime sink read it. It is kept for
:data:`RETENTION` whoever has or hasn't read it: a subscriber further behind
than that has stopped consuming and resumes from the current head.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from sqlmodel import delete
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.tenant.event_outbox import EventOutbox
from app.models.tenant.plugin_event_outbox import PluginEventOutbox

if TYPE_CHECKING:
    from app.services.tenant.expiry import Expiring

#: How long a change is kept.
RETENTION = timedelta(days=7)


async def expire(session: AsyncSession, expiring: Expiring) -> None:
    """Drop changes past :data:`RETENTION`, noting their transactions for the
    records that go with them.

    Age-based on purpose: a subscription weeks behind is broken, and holding
    the log open for it would grow the table without bound on every instance
    that never configures a target at all.
    """
    cutoff = expiring.now - RETENTION
    for log in (EventOutbox, PluginEventOutbox):
        removed = await session.exec(
            delete(log).where(log.occurred_at < cutoff).returning(log.txn_id)  # type: ignore[arg-type]
        )
        expiring.expired_txns.update(txn_id for (txn_id,) in removed.all())
