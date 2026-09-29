"""Telling every process that a community has background work waiting.

A write that leaves work for a background drain (a queued data job, a changed
webhook subscription) sends a wake once it commits: ``<kind>:<guild_id>`` on
the ``guild_work`` channel. Every process hears it, the sender included, and
hands the community to that kind's drain, which visits it alone.

A wake is a hint. The bus delivers at most once and may be down, so the
minute pass finds whatever a lost wake left behind.
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.platform import user_stream

logger = logging.getLogger(__name__)

CHANNEL = "guild_work"

#: A data job was queued in the community, or one there ended.
DATA_JOBS = "data_jobs"
#: A webhook subscription in the community was created, enabled or deleted.
WEBHOOKS = "webhooks"


def wake(session: Any, kind: str, guild_id: int) -> None:
    """Send a wake for ``kind`` in ``guild_id`` once ``session`` commits."""
    user_stream.after_commit(
        session, (CHANNEL, kind, guild_id), lambda: send(kind, guild_id)
    )


async def send(kind: str, guild_id: int) -> None:
    """Send a wake now. With the bus down, this process still hears it."""
    from app.services.platform import notify_bus

    try:
        await notify_bus.notify(CHANNEL, f"{kind}:{guild_id}")
    except Exception:
        logger.debug("guild_work: bus unavailable", exc_info=True)
        _hear(kind, guild_id)


async def deliver(payload: str) -> None:
    """Take a wake off the bus."""
    kind, _, raw = payload.partition(":")
    if not raw.isdigit():
        logger.warning("guild_work: unreadable wake on %s", CHANNEL)
        return
    _hear(kind, int(raw))


def _hear(kind: str, guild_id: int) -> None:
    if kind == DATA_JOBS:
        from app.services import data_jobs

        data_jobs.drain.wake(guild_id)
    elif kind == WEBHOOKS:
        from app.services.tenant import outbox_poller

        outbox_poller.subscriptions_changed(guild_id)
    else:
        logger.warning("guild_work: unknown kind %s", kind)
