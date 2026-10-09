from __future__ import annotations

import asyncio
import itertools
import logging
from collections.abc import Awaitable, Callable
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


class Loop:
    """One background worker's loop.

    Runs its work every ``interval`` seconds, and soon after :meth:`wake` is
    called. A woken pass waits ``settle`` seconds first, so wakes arriving
    together are served by one pass. Without an ``interval`` it runs only when
    woken. A pass that fails is logged, and the loop carries on.
    """

    def __init__(
        self, name: str, *, interval: float | None = None, settle: float = 0.0
    ) -> None:
        self.name = name
        self.interval = interval
        self.settle = settle
        self._woken = asyncio.Event()

    def wake(self) -> None:
        """Ask for a pass. Returns at once."""
        self._woken.set()

    async def run(self, work: Callable[[], Awaitable[object]]) -> None:
        logger.info("%s worker started (interval=%ss)", self.name, self.interval)
        try:
            # A timed loop starts with a pass; one that is only woken waits.
            if self.interval is None:
                await self._wait()
            while True:
                self._woken.clear()
                try:
                    await work()
                except Exception:  # pragma: no cover
                    logger.exception("%s worker encountered an error", self.name)
                await self._wait()
        except asyncio.CancelledError:  # pragma: no cover
            logger.info("%s worker cancelled", self.name)
            raise

    async def _wait(self) -> None:
        try:
            await asyncio.wait_for(self._woken.wait(), timeout=self.interval)
        except TimeoutError:
            return
        await asyncio.sleep(self.settle)


async def minute_pass() -> None:
    """Event-driven work's backstop and the minute-grained notices, in one
    visit per community.

    Webhook deliveries (retries that have come due, and anything a lost wake
    left), plug-ins' due schedules, data-job claims, both digests, event reminders
    and scheduled posts, and every :data:`OVERDUE_EVERY`-th pass the overdue
    digests. Posts are published in active communities only: a hold must not
    keep announcing new notices to its members.
    """
    from app.services import notifications
    from app.services.guild_sweeps import Scope, each_guild
    from app.services.tenant import plugin_schedules, outbox_poller, post_publication

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
            (Scope.ACTIVE, plugin_schedules.run_due),
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
    webhook history, spent digest items, evidence past its keeping, and
    plug-in auto-updates.

    Trash is purged and plug-ins updated in active communities only: a read-only
    or suspended one is frozen until it returns. Exports and imports expire
    wherever the schema still exists.
    """
    from app.services import notifications
    from app.services.export import worker as export_worker
    from app.services.guild_sweeps import Scope, each_guild
    from app.services.import_engine import worker as import_worker
    from app.services.platform import evidence
    from app.services.tenant import plugin_updates, outbox_poller, trash_purge

    await each_guild(
        [
            (Scope.ACTIVE, trash_purge.purge_guild),
            (Scope.PROVISIONED, export_worker.expire_artifacts),
            (Scope.PROVISIONED, import_worker.expire_payloads),
            (Scope.ACTIVE, outbox_poller.expire_history),
            (Scope.ACTIVE, evidence.purge_due),
            (Scope.ACTIVE, plugin_updates.update_guild),
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
    from app.services.platform import notice_outbox
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
    from app.services.platform.access_grants import (
        GRANT_EXPIRY_POLL_SECONDS,
        process_grant_expiry,
    )
    from app.services.auth.held_changes import (
        HOLD_SWEEP_POLL_SECONDS,
        process_due_holds,
    )
    from app.services.platform.ticket_notices import (
        TICKET_NOTICE_POLL_SECONDS,
        process_ticket_notices,
    )
    from app.services.marketplace.tuf_registry import (
        process_registry_refresh,
        registry_available,
    )

    tasks = [
        # Every sweep that visits the communities, grouped by how often it
        # needs to run.
        asyncio.create_task(
            Loop("minute", interval=MINUTE_PASS_SECONDS).run(minute_pass)
        ),
        asyncio.create_task(Loop("slow", interval=SLOW_PASS_SECONDS).run(slow_pass)),
        asyncio.create_task(
            Loop("hourly", interval=HOURLY_PASS_SECONDS).run(hourly_pass)
        ),
        # Communities a wake names, visited as soon as it arrives.
        asyncio.create_task(
            outbox_poller.drain.run([(Scope.ACTIVE, outbox_poller.drain_guild)])
        ),
        asyncio.create_task(data_jobs.drain.run(_claims())),
        asyncio.create_task(
            Loop("hold-summary", interval=HOLD_SUMMARY_POLL_SECONDS).run(
                process_hold_summaries
            )
        ),
        # Notices, delivered as they are written.
        asyncio.create_task(
            notice_outbox.loop.run(notice_outbox.process_notice_outbox)
        ),
        # The one way notification email leaves the building.
        asyncio.create_task(
            Loop("email-outbox", interval=EMAIL_OUTBOX_POLL_SECONDS).run(
                process_email_outbox
            )
        ),
        # What the presence roll has seen, written where another process can
        # read it. The roll is this worker's own memory; delivery decides
        # elsewhere.
        asyncio.create_task(
            Loop("activity-flush", interval=ACTIVITY_FLUSH_SECONDS).run(
                process_activity_flush
            )
        ),
        asyncio.create_task(
            Loop("oidc-refresh-sync", interval=OIDC_SYNC_POLL_SECONDS).run(
                process_oidc_refresh_sync
            )
        ),
        asyncio.create_task(
            Loop("guild-purge", interval=GUILD_PURGE_POLL_SECONDS).run(
                process_guild_purges
            )
        ),
        asyncio.create_task(
            Loop("account-purge", interval=ACCOUNT_PURGE_POLL_SECONDS).run(
                process_account_purges
            )
        ),
        asyncio.create_task(
            Loop("identity-ref-sweep", interval=IDENTITY_REF_SWEEP_POLL_SECONDS).run(
                process_identity_ref_sweep
            )
        ),
        asyncio.create_task(
            Loop("announcement-image-purge", interval=IMAGE_PURGE_POLL_SECONDS).run(
                process_announcement_image_purge
            )
        ),
        # The room sink's backstop. The prompt path is the capture's own
        # pg_notify; this covers the hints raised while a worker's bus
        # connection was rebuilding, and reads nothing for a guild this
        # process holds no socket for.
        asyncio.create_task(
            Loop("room-sweep", interval=ROOM_SWEEP_SECONDS).run(process_room_sweep)
        ),
        asyncio.create_task(
            Loop("token-purge", interval=TOKEN_PURGE_POLL_SECONDS).run(
                process_expired_token_purge
            )
        ),
        asyncio.create_task(
            Loop("jti-purge", interval=JTI_PURGE_POLL_SECONDS).run(
                process_jti_blocklist_purges
            )
        ),
        asyncio.create_task(
            Loop("session-purge", interval=SESSION_PURGE_POLL_SECONDS).run(
                process_dead_session_purge
            )
        ),
        asyncio.create_task(
            Loop("grant-expiry", interval=GRANT_EXPIRY_POLL_SECONDS).run(
                process_grant_expiry
            )
        ),
        asyncio.create_task(
            Loop("held-changes", interval=HOLD_SWEEP_POLL_SECONDS).run(
                process_due_holds
            )
        ),
        asyncio.create_task(
            Loop("ticket-notices", interval=TICKET_NOTICE_POLL_SECONDS).run(
                process_ticket_notices
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
                Loop(
                    "marketplace-registry",
                    interval=settings.MARKETPLACE_REGISTRY_TTL_SECONDS,
                ).run(process_registry_refresh)
            )
        )

    return tasks
