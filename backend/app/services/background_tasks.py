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
        process_assignment_digest_gc,
        process_reaction_digests,
        process_task_assignment_digests,
        process_overdue_notifications,
        process_event_reminders,
        ASSIGNMENT_GC_POLL_SECONDS,
        DIGEST_POLL_SECONDS,
        OVERDUE_POLL_SECONDS,
        EVENT_REMINDER_POLL_SECONDS,
    )
    from app.services.oidc_refresh import (
        process_oidc_refresh_sync,
        OIDC_SYNC_POLL_SECONDS,
    )
    from app.services.platform.announcements import (
        process_announcement_image_purge,
        IMAGE_PURGE_POLL_SECONDS,
    )
    from app.services.tenant.trash_purge import process_trash_purges, PURGE_POLL_SECONDS
    from app.services.tenant.app_updates import (
        AUTO_UPDATE_POLL_SECONDS,
        process_app_auto_updates,
    )
    from app.services.tenant.outbox_poller import (
        OUTBOX_POLL_SECONDS,
        OUTBOX_RETENTION_POLL_SECONDS,
        process_outbox_deliveries,
        process_outbox_retention,
    )
    from app.services.platform.user_tokens import (
        process_expired_token_purge,
        TOKEN_PURGE_POLL_SECONDS,
    )
    from app.services.platform.jti_purge import (
        process_jti_blocklist_purges,
        JTI_PURGE_POLL_SECONDS,
    )
    from app.services.import_engine.worker import (
        IMPORT_GC_POLL_SECONDS,
        IMPORT_POLL_SECONDS,
        process_import_gc,
        process_import_jobs,
    )
    from app.services.export.worker import (
        process_export_jobs,
        process_export_gc,
        EXPORT_POLL_SECONDS,
        EXPORT_GC_POLL_SECONDS,
    )
    from app.services.marketplace.registry import (
        process_registry_refresh,
        registry_configured,
    )
    from app.services.marketplace.reverification import (
        process_app_service_reverification,
        reverification_configured,
        reverification_interval_seconds,
    )

    tasks = [
        asyncio.create_task(
            _loop_worker(
                process_task_assignment_digests, DIGEST_POLL_SECONDS, "task-digest"
            )
        ),
        asyncio.create_task(
            _loop_worker(
                process_reaction_digests, DIGEST_POLL_SECONDS, "reaction-digest"
            )
        ),
        # One GC sweep covers every digest queue.
        asyncio.create_task(
            _loop_worker(
                process_assignment_digest_gc,
                ASSIGNMENT_GC_POLL_SECONDS,
                "digest-gc",
            )
        ),
        asyncio.create_task(
            _loop_worker(
                process_overdue_notifications, OVERDUE_POLL_SECONDS, "overdue-digest"
            )
        ),
        asyncio.create_task(
            _loop_worker(
                process_event_reminders, EVENT_REMINDER_POLL_SECONDS, "event-reminder"
            )
        ),
        asyncio.create_task(
            _loop_worker(
                process_oidc_refresh_sync, OIDC_SYNC_POLL_SECONDS, "oidc-refresh-sync"
            )
        ),
        asyncio.create_task(
            _loop_worker(process_trash_purges, PURGE_POLL_SECONDS, "trash-purge")
        ),
        asyncio.create_task(
            _loop_worker(
                process_announcement_image_purge,
                IMAGE_PURGE_POLL_SECONDS,
                "announcement-image-purge",
            )
        ),
        asyncio.create_task(
            _loop_worker(
                process_app_auto_updates, AUTO_UPDATE_POLL_SECONDS, "app-auto-update"
            )
        ),
        asyncio.create_task(
            _loop_worker(
                process_outbox_deliveries, OUTBOX_POLL_SECONDS, "outbox-deliveries"
            )
        ),
        asyncio.create_task(
            _loop_worker(
                process_outbox_retention,
                OUTBOX_RETENTION_POLL_SECONDS,
                "outbox-retention",
            )
        ),
        asyncio.create_task(
            _loop_worker(
                process_expired_token_purge, TOKEN_PURGE_POLL_SECONDS, "token-purge"
            )
        ),
        asyncio.create_task(
            _loop_worker(
                process_jti_blocklist_purges, JTI_PURGE_POLL_SECONDS, "jti-purge"
            )
        ),
        asyncio.create_task(
            _loop_worker(process_export_jobs, EXPORT_POLL_SECONDS, "export-jobs")
        ),
        asyncio.create_task(
            _loop_worker(process_export_gc, EXPORT_GC_POLL_SECONDS, "export-gc")
        ),
        asyncio.create_task(
            _loop_worker(process_import_jobs, IMPORT_POLL_SECONDS, "import-jobs")
        ),
        asyncio.create_task(
            _loop_worker(process_import_gc, IMPORT_GC_POLL_SECONDS, "import-gc")
        ),
    ]

    # The marketplace registry is optional. With no registry configured there
    # is no worker at all rather than one that wakes up to find nothing to do —
    # an unconfigured install runs no part of this and says nothing about it.
    # The loop runs its first pass immediately, so boot is also the first
    # refresh; the catalog this build ships is already seeded by then and the
    # registry adds to it through the same writer.
    if registry_configured():
        from app.core.config import settings

        tasks.append(
            asyncio.create_task(
                _loop_worker(
                    process_registry_refresh,
                    settings.MARKETPLACE_REGISTRY_TTL_SECONDS,
                    "marketplace-registry",
                )
            )
        )

    # Re-verifying app services is the same shape: a deployment with no app
    # platform configured runs no worker for it. What the sweep changes is the
    # recorded status of a registration, never whether it is enabled — an
    # unreachable app is reported, not switched off.
    if reverification_configured():
        tasks.append(
            asyncio.create_task(
                _loop_worker(
                    process_app_service_reverification,
                    reverification_interval_seconds(),
                    "app-service-verify",
                )
            )
        )

    return tasks
