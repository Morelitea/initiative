from __future__ import annotations

import asyncio
import itertools
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.guild_sweeps import Scope, Visit

logger = logging.getLogger(__name__)

#: How often each pass over the communities runs.
MINUTE_PASS_SECONDS = 60
SLOW_PASS_SECONDS = 300
HOURLY_PASS_SECONDS = 3600

#: The minute pass sends overdue digests on every this-many-th pass.
OVERDUE_EVERY = 5

_minute_passes = itertools.count()


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


async def minute_pass() -> None:
    """Event-driven work's backstop and the minute-grained notices, in one
    visit per community.

    Webhook deliveries (retries that have come due, and anything a lost wake
    left), apps' due schedules, data-job claims, both digests, event reminders
    and scheduled posts, and every :data:`OVERDUE_EVERY`-th pass the overdue
    digests. Posts are published in active communities only: a hold must not
    keep announcing new notices to its members.
    """
    from app.services import notifications
    from app.services.guild_sweeps import Scope, each_guild
    from app.services.tenant import app_schedules, outbox_poller, post_publication

    now = datetime.now(timezone.utc)
    scans = [
        notifications.digest_scan(notifications.ASSIGNMENT_DIGEST, now=now),
        notifications.digest_scan(notifications.REACTION_DIGEST, now=now),
    ]
    try:
        reminders = await notifications.reminder_scan(now=now)
    except Exception:
        # The rest of the pass goes ahead without them.
        logger.exception("minute: reading reminder opt-ins failed")
        reminders = None
    if reminders is not None:
        scans.append(reminders)
    if next(_minute_passes) % OVERDUE_EVERY == 0:
        scans.append(notifications.overdue_scan(now=now))
    await each_guild(
        [
            (Scope.ACTIVE, outbox_poller.drain_guild),
            (Scope.ACTIVE, app_schedules.run_due),
            *_claims(),
            (
                Scope.ACTIVE,
                lambda session, _guild_id: post_publication.publish_due_posts(
                    session, now=now
                ),
            ),
        ],
        name="minute",
        scans=scans,
    )


async def slow_pass() -> None:
    """Data jobs whose rows have gone quiet. The stale window is 15 minutes,
    so five is often enough."""
    from app.services.export import worker as export_worker
    from app.services.guild_sweeps import Scope, each_guild
    from app.services.import_engine import worker as import_worker

    await each_guild(
        [
            (Scope.ACTIVE, export_worker.jobs.sweep_stale),
            (Scope.ACTIVE, import_worker.jobs.sweep_stale),
        ],
        name="slow",
    )


async def hourly_pass() -> None:
    """Retention and upkeep: trash, expired exports and imports, delivered
    webhook history, spent digest items, and app auto-updates.

    Trash is purged and apps updated in active communities only: a read-only
    or suspended one is frozen until it returns. Exports and imports expire
    wherever the schema still exists.
    """
    from app.services import notifications
    from app.services.export import worker as export_worker
    from app.services.guild_sweeps import Scope, each_guild
    from app.services.import_engine import worker as import_worker
    from app.services.tenant import app_updates, outbox_poller, trash_purge

    await each_guild(
        [
            (Scope.ACTIVE, trash_purge.purge_guild),
            (Scope.PROVISIONED, export_worker.expire_artifacts),
            (Scope.PROVISIONED, import_worker.expire_payloads),
            (Scope.ACTIVE, outbox_poller.expire_history),
            (Scope.ACTIVE, app_updates.update_guild),
        ],
        name="hourly",
        scans=[notifications.digest_gc_scan(now=datetime.now(timezone.utc))],
    )


def _claims() -> list[tuple[Scope, Visit]]:
    """Each job type's claim of a community's next queued job."""
    from app.services.export import worker as export_worker
    from app.services.guild_sweeps import Scope
    from app.services.import_engine import worker as import_worker

    return [
        (Scope.ACTIVE, export_worker.jobs.claim),
        (Scope.ACTIVE, import_worker.jobs.claim),
    ]


def start_background_tasks() -> list[asyncio.Task]:
    from app.services import data_jobs
    from app.services.guild_sweeps import Scope
    from app.services.notifications import (
        process_hold_summaries,
        HOLD_SUMMARY_POLL_SECONDS,
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
    from app.services.tenant import outbox_poller
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
    from app.services.marketplace.tuf_registry import (
        process_registry_refresh,
        registry_available,
    )

    tasks = [
        # Every sweep that visits the communities, grouped by how often it
        # needs to run.
        asyncio.create_task(_loop_worker(minute_pass, MINUTE_PASS_SECONDS, "minute")),
        asyncio.create_task(_loop_worker(slow_pass, SLOW_PASS_SECONDS, "slow")),
        asyncio.create_task(_loop_worker(hourly_pass, HOURLY_PASS_SECONDS, "hourly")),
        # Communities a wake names, visited as soon as it arrives.
        asyncio.create_task(
            outbox_poller.drain.run([(Scope.ACTIVE, outbox_poller.drain_guild)])
        ),
        asyncio.create_task(data_jobs.drain.run(_claims())),
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
    ]

    # The marketplace registry needs a trusted root. A build without one runs
    # no worker at all. Each pass asks the platform switch first, so turning
    # the registry off stops the fetching without a restart. The loop runs its
    # first pass immediately, so boot is also the first refresh; the catalog
    # this build ships is already seeded by then and the registry adds to it
    # through the same writer.
    if registry_available():
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
