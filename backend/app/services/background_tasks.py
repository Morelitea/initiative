from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


async def _loop_worker(task_coro, interval: int, name: str) -> None:
    logger.info("%s worker started (interval=%ss)", name, interval)
    try:
        while True:
            try:
                await task_coro()
            except Exception:  # pragma: no cover
                logger.exception("%s worker encountered an error", name)
            await asyncio.sleep(interval)
    except asyncio.CancelledError:  # pragma: no cover
        logger.info("%s worker cancelled", name)
        raise


def start_background_tasks() -> list[asyncio.Task]:
    from app.services.notifications import (
        process_task_assignment_digests,
        process_overdue_notifications,
        DIGEST_POLL_SECONDS,
        OVERDUE_POLL_SECONDS,
    )
    from app.services.oidc_refresh import process_oidc_refresh_sync, OIDC_SYNC_POLL_SECONDS

    return [
        asyncio.create_task(
            _loop_worker(process_task_assignment_digests, DIGEST_POLL_SECONDS, "task-digest")
        ),
        asyncio.create_task(
            _loop_worker(process_overdue_notifications, OVERDUE_POLL_SECONDS, "overdue-digest")
        ),
        asyncio.create_task(
            _loop_worker(process_oidc_refresh_sync, OIDC_SYNC_POLL_SECONDS, "oidc-refresh-sync")
        ),
    ]
