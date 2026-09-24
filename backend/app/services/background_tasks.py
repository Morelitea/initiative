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
        process_hold_summaries,
        process_event_reminders,
        ASSIGNMENT_GC_POLL_SECONDS,
        DIGEST_POLL_SECONDS,
        OVERDUE_POLL_SECONDS,
        HOLD_SUMMARY_POLL_SECONDS,
        EVENT_REMINDER_POLL_SECONDS,
    )
    from app.services.platform.email_outbox import (
        EMAIL_OUTBOX_POLL_SECONDS,
        process_email_outbox,
    )
    from app.services.platform.presence import (
        ACTIVITY_FLUSH_SECONDS,
        process_activity_flush,
    )
    from app.services.oidc_refresh import (
        process_oidc_refresh_sync,
        OIDC_SYNC_POLL_SECONDS,
    )
    from app.services.platform.announcements import (
        process_announcement_image_purge,
        IMAGE_PURGE_POLL_SECONDS,
    )
    from app.services.tenant.post_publication import (
        POST_PUBLISH_POLL_SECONDS,
        process_post_publications,
    )
    from app.services.tenant.trash_purge import process_trash_purges, PURGE_POLL_SECONDS
    from app.services.platform.guild_purge import (
        GUILD_PURGE_POLL_SECONDS,
        process_guild_purges,
    )
    from app.services.platform.account_purge import (
        ACCOUNT_PURGE_POLL_SECONDS,
        process_account_purges,
    )
    from app.services.platform.identity_refs import (
        IDENTITY_REF_SWEEP_POLL_SECONDS,
        process_identity_ref_sweep,
    )
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
    from app.services.tenant.room_sink import ROOM_SWEEP_SECONDS, process_room_sweep
    from app.services.platform.user_tokens import (
        process_expired_token_purge,
        TOKEN_PURGE_POLL_SECONDS,
    )
    from app.services.auth.sessions import (
        SESSION_PURGE_POLL_SECONDS,
        process_dead_session_purge,
    )
    from app.services.platform.jti_purge import (
        process_jti_blocklist_purges,
        JTI_PURGE_POLL_SECONDS,
    )
    from app.services.import_engine.worker import (
        IMPORT_GC_POLL_SECONDS,
        IMPORT_POLL_SECONDS,
        dispatch_import_jobs,
        process_import_gc,
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
                process_hold_summaries,
                HOLD_SUMMARY_POLL_SECONDS,
                "hold-summary",
            )
        ),
        # The one way notification email leaves the building.
        asyncio.create_task(
            _loop_worker(
                process_email_outbox,
                EMAIL_OUTBOX_POLL_SECONDS,
                "email-outbox",
            )
        ),
        # What the presence roll has seen, written where another process can
        # read it. The roll is this worker's own memory; delivery decides
        # elsewhere.
        asyncio.create_task(
            _loop_worker(
                process_activity_flush,
                ACTIVITY_FLUSH_SECONDS,
                "activity-flush",
            )
        ),
        asyncio.create_task(
            _loop_worker(
                process_oidc_refresh_sync, OIDC_SYNC_POLL_SECONDS, "oidc-refresh-sync"
            )
        ),
        asyncio.create_task(
            _loop_worker(
                process_post_publications,
                POST_PUBLISH_POLL_SECONDS,
                "post-publication",
            )
        ),
        asyncio.create_task(
            _loop_worker(process_trash_purges, PURGE_POLL_SECONDS, "trash-purge")
        ),
        asyncio.create_task(
            _loop_worker(process_guild_purges, GUILD_PURGE_POLL_SECONDS, "guild-purge")
        ),
        asyncio.create_task(
            _loop_worker(
                process_account_purges, ACCOUNT_PURGE_POLL_SECONDS, "account-purge"
            )
        ),
        asyncio.create_task(
            _loop_worker(
                process_identity_ref_sweep,
                IDENTITY_REF_SWEEP_POLL_SECONDS,
                "identity-ref-sweep",
            )
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
        # The room sink's backstop. The prompt path is the capture's own
        # pg_notify; this covers the hints raised while a worker's bus
        # connection was rebuilding, and reads nothing for a guild this
        # process holds no socket for.
        asyncio.create_task(
            _loop_worker(process_room_sweep, ROOM_SWEEP_SECONDS, "room-sweep")
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
            _loop_worker(
                process_dead_session_purge,
                SESSION_PURGE_POLL_SECONDS,
                "session-purge",
            )
        ),
        asyncio.create_task(
            _loop_worker(process_export_jobs, EXPORT_POLL_SECONDS, "export-jobs")
        ),
        asyncio.create_task(
            _loop_worker(process_export_gc, EXPORT_GC_POLL_SECONDS, "export-gc")
        ),
        asyncio.create_task(
            _loop_worker(dispatch_import_jobs, IMPORT_POLL_SECONDS, "import-jobs")
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

    return tasks
