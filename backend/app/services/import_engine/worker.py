"""Import worker: claims queued ImportJobs, re-validates, applies.

Mirrors the export worker's structure — bookkeeping under the system engine
routed as a synthetic guild admin (the own-row policies' admin leg), the
actual apply on a fresh session routed as the job's CREATOR via
``establish_guild_access`` (revoked access between request and apply fails
the job closed, and the target initiative + create permission are re-checked
at apply time for the same reason).

One deliberate divergence from the export worker: a stale ``running`` row is
NEVER re-claimed and re-applied. Exports re-render idempotently (same
artifact key); an interrupted import has already committed rows under the
always-create policy, so a re-run would duplicate them. Stale running rows
are failed closed with ``IMPORT_INTERRUPTED``.

A queued job from a foreign source that has no payload yet is not applied but
**fetched**: the site is read into a backup-shaped bundle and the job parks at
``staged`` for its creator to review, exactly where an uploaded backup waits
(see ``atlassian_job``).

A stale ``fetching`` row is the one exception, and for the reason that makes
the rule above right: a fetch writes no content row at all, only a payload in
storage. There is nothing committed to duplicate, so the partial payload is
thrown away and the job goes back in the queue to start over — keeping its
secret, which is the one thing a restart still needs.

Every other terminal transition here clears the job's secret along with its
payload. Both are things the job was lent rather than things it owns, and a
job that is over needs neither.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import ImportEngineMessages
from app.db import session as db_session
from app.db.session import SYSTEM_SATISFIED, set_rls_context
from app.models.platform.guild import Guild, GuildStatus
from app.models.platform.notification import NotificationType
from app.models.platform.user import UserStatus
from app.models.tenant.import_job import ImportJob, ImportJobStatus
from app.services.import_engine import atlassian_job
from app.services.import_engine import engine as import_engine
from app.services.platform import accounts as accounts_service
from app.services.import_engine.contract import ImportEngineError
from app.services.platform import user_notifications
from app.services.import_engine import limits as import_limits

logger = logging.getLogger(__name__)

IMPORT_POLL_SECONDS = 10
IMPORT_GC_POLL_SECONDS = 3600

# A ``running`` row untouched this long is a crashed apply. Unlike exports it
# is NOT re-claimed (see module docstring) — it is failed closed.
STALE_RUNNING = timedelta(minutes=15)

# A ``fetching`` row untouched this long is a crashed fetch. Longer than the
# apply bound because reading somebody else's API under a rate limit is
# legitimately slow, and re-claiming one that was still working would start a
# second conversation with the same site.
STALE_FETCHING = timedelta(minutes=60)


def _open_user_session() -> AsyncSession:
    """Late-bound (module attribute lookup at call time) so the test
    harness's sessionmaker patches apply to the worker too."""
    return db_session.AsyncSessionLocal()


async def process_import_jobs() -> None:
    now = datetime.now(timezone.utc)
    async with db_session.SystemSessionLocal() as session:
        await set_rls_context(session)
        guild_ids = list(
            await session.exec(
                select(Guild.id)
                .where(Guild.status == GuildStatus.active.value)
                .order_by(Guild.id.asc())
            )
        )
        for guild_id in guild_ids:
            session.expunge_all()
            await set_rls_context(session, guild_id=guild_id)
            outcomes = await _process_guild_jobs(session, guild_id=guild_id, now=now)
            await session.commit()
            # Notify creators from the UNROUTED system context: the guild-admin
            # routing above carries no user GUC, so the shared notifications
            # table's own-row policies would refuse the insert there.
            await set_rls_context(session)
            for user_id, notification_type, data in outcomes:
                await user_notifications.create_notification(
                    session,
                    user_id=user_id,
                    notification_type=notification_type,
                    data=data,
                )
            await session.commit()


JobOutcome = tuple[int, NotificationType, dict]


async def _process_guild_jobs(
    session: AsyncSession, *, guild_id: int, now: datetime
) -> list[JobOutcome]:
    outcomes: list[JobOutcome] = []

    # Fail interrupted applies closed — never re-run them (duplicates).
    stale = list(
        await session.exec(
            select(ImportJob).where(
                ImportJob.status == ImportJobStatus.running,
                ImportJob.updated_at < now - STALE_RUNNING,
            )
        )
    )
    for job in stale:
        logger.warning(
            "import job interrupted id=%s guild=%s source=%s",
            job.id,
            guild_id,
            job.source,
        )
        job.status = ImportJobStatus.failed
        job.error = ImportEngineMessages.IMPORT_INTERRUPTED
        job.updated_at = now
        import_engine.delete_payload(guild_id, job.payload_ref)
        job.secret_encrypted = None
        session.add(job)
        outcomes.append(_outcome(job, guild_id))
    if stale:
        await session.commit()

    # Re-claim abandoned fetches. Nothing content-side was written, so the
    # partial payload is discarded and the job queues again from the start.
    abandoned = list(
        await session.exec(
            select(ImportJob).where(
                ImportJob.status == ImportJobStatus.fetching,
                ImportJob.updated_at < now - STALE_FETCHING,
            )
        )
    )
    for job in abandoned:
        logger.warning(
            "import fetch re-claimed id=%s guild=%s source=%s",
            job.id,
            guild_id,
            job.source,
        )
        import_engine.delete_payload(guild_id, job.payload_ref)
        job.payload_ref = None
        job.status = ImportJobStatus.queued
        job.updated_at = now
        session.add(job)
    if abandoned:
        await session.commit()

    jobs = list(
        await session.exec(
            select(ImportJob)
            .where(ImportJob.status == ImportJobStatus.queued)
            .order_by(ImportJob.created_at.asc())
        )
    )
    for job in jobs:
        # Re-read under a lock before claiming: the list was taken before the
        # jobs ahead of this one ran, and one cancelled since stays cancelled.
        await session.refresh(job, with_for_update=True)
        if job.status != ImportJobStatus.queued:
            await session.commit()
            continue
        if atlassian_job.awaits_fetch(job):
            outcome = await _fetch(session, job, guild_id=guild_id)
            if outcome is not None:
                outcomes.append(outcome)
            continue
        job.status = ImportJobStatus.running
        job.updated_at = now
        session.add(job)
        # Commit the claim before the (slow) apply, so a crash mid-apply
        # leaves a stale ``running`` row that the next pass FAILS (not
        # re-runs), and the creator learns instead of waiting forever.
        await session.commit()
        try:
            result = await _execute(session, job, guild_id=guild_id)
        except Exception as exc:  # fail closed: record a code, never content
            logger.exception(
                "import job failed id=%s guild=%s source=%s",
                job.id,
                guild_id,
                job.source,
            )
            job.status = ImportJobStatus.failed
            job.error = _error_code(exc)
        else:
            job.status = ImportJobStatus.done
            job.result = result
            job.error = None
        job.updated_at = datetime.now(timezone.utc)
        import_engine.delete_payload(guild_id, job.payload_ref)
        job.secret_encrypted = None
        job.payload_ref = None
        session.add(job)
        await session.commit()
        outcomes.append(_outcome(job, guild_id))
    return outcomes


async def _fetch(
    session: AsyncSession, job: ImportJob, *, guild_id: int
) -> JobOutcome | None:
    """Read a foreign source into a bundle and park the job for review.

    Ends in one of three places. **Staged**, with the bundle and its plan,
    which is the wizard's review step and needs no notification — the person
    is either watching the job or will find it waiting. **Failed**, with a
    code, which does notify. Or **nowhere**, when the job was cancelled while
    the site was being read: the bundle, if one got written, is thrown away
    and the row is left as the cancel put it.

    The secret goes in every case. A staged bundle holds everything the
    apply needs, and a job that failed or was cancelled needs nothing.
    """
    job.status = ImportJobStatus.fetching
    job.updated_at = datetime.now(timezone.utc)
    session.add(job)
    # Committed before the (slow) read, so a crash mid-fetch leaves a stale
    # ``fetching`` row for the re-claim rule rather than a queued one that
    # looks untouched.
    await session.commit()

    async def still_fetching() -> bool:
        await session.refresh(job, with_for_update=True)
        return job.status == ImportJobStatus.fetching

    async def heartbeat(summary) -> None:
        if not await still_fetching():
            await session.commit()
            raise atlassian_job.FetchCancelled
        job.plan = {"atlassian": summary.model_dump(mode="json")}
        job.updated_at = datetime.now(timezone.utc)
        session.add(job)
        await session.commit()

    try:
        staged = await atlassian_job.fetch(
            job,
            guild_id=guild_id,
            open_user_session=_open_user_session,
            progress=heartbeat,
        )
    except atlassian_job.FetchCancelled:
        logger.info("import fetch stopped by cancel id=%s guild=%s", job.id, guild_id)
        job.secret_encrypted = None
        session.add(job)
        await session.commit()
        return None
    except Exception as exc:  # fail closed: record a code, never content
        logger.exception(
            "import fetch failed id=%s guild=%s source=%s",
            job.id,
            guild_id,
            job.source,
        )
        # Whatever failed may have been a heartbeat's write; start clean.
        await session.rollback()
        # A cancel that landed mid-read stays a cancel, not a failure.
        if not await still_fetching():
            job.secret_encrypted = None
            session.add(job)
            await session.commit()
            return None
        job.status = ImportJobStatus.failed
        job.error = _error_code(exc)
        job.secret_encrypted = None
        job.updated_at = datetime.now(timezone.utc)
        session.add(job)
        await session.commit()
        return _outcome(job, guild_id)

    if not await still_fetching():
        import_engine.delete_payload(guild_id, staged.payload_ref)
        job.secret_encrypted = None
        session.add(job)
        await session.commit()
        return None
    now = datetime.now(timezone.utc)
    job.secret_encrypted = None
    job.status = ImportJobStatus.staged
    job.payload_ref = staged.payload_ref
    job.plan = staged.plan
    job.updated_at = now
    # The review gets a whole window of its own, however long the read took.
    job.expires_at = now + timedelta(hours=import_limits.IMPORT_STAGED_TTL_HOURS)
    session.add(job)
    await session.commit()
    return None


def _outcome(job: ImportJob, guild_id: int) -> JobOutcome:
    return (
        job.created_by,
        NotificationType.import_ready
        if job.status == ImportJobStatus.done
        else NotificationType.import_failed,
        {
            "guild_id": guild_id,
            "import_job_id": job.id,
            "source": job.source,
        },
    )


async def _execute(session: AsyncSession, job: ImportJob, *, guild_id: int) -> dict:
    """Re-validate the staged payload and apply it as the job's creator."""
    from app.api.deps import establish_guild_access

    # The session is routed into the guild here, which is not somewhere an
    # account may be read; the creator comes off the system engine instead.
    user = await accounts_service.load_one(job.created_by)
    if user is None or user.status != UserStatus.active:
        raise ImportEngineError(ImportEngineMessages.IMPORT_CREATOR_INACTIVE)

    if not job.payload_ref:
        raise ImportEngineError(ImportEngineMessages.IMPORT_INVALID_PARAMS)
    payload = import_engine.read_payload(guild_id, job.payload_ref)
    if payload is None:
        raise ImportEngineError(ImportEngineMessages.IMPORT_INVALID_PARAMS)

    if job.source in ("backup", atlassian_job.SOURCE):
        # A fetched bundle is a backup-shaped zip filing into an initiative
        # that exists, so it takes the backup path — which gates it by the
        # create permission there rather than by the community's seat.
        from app.services.import_engine import backup as backup_service

        async with _open_user_session() as user_session:
            # Route as the creator; apply_backup re-verifies REAL guild
            # adminship and owns its own per-chunk commits + refreshes. As
            # user-attributed system work whose enqueueing request already
            # passed the guild auth-policy gate, it carries the system sentinel.
            await establish_guild_access(
                user_session, user, guild_id, satisfied_providers=SYSTEM_SATISFIED
            )
            backup_result = await backup_service.apply_backup(
                user_session,
                user=user,
                guild_id=guild_id,
                payload=payload,
                include=(job.params or {}).get("include"),
                people_map=(job.params or {}).get("people_map"),
                exclude_properties=(job.params or {}).get("exclude_properties"),
            )
        return backup_result.model_dump(mode="json")

    importer = import_engine.get_importer(job.source)
    envelope = importer.validate(json.loads(payload))

    async with _open_user_session() as user_session:
        # Resolve membership/PAM and route the session as the creator; raises
        # GuildAccessError (-> failed job) if their access is gone. The target
        # and create permission are re-checked too — authorization is a
        # property of apply time, not enqueue time. (System sentinel: the
        # enqueueing request already passed the guild auth-policy gate.)
        await establish_guild_access(
            user_session, user, guild_id, satisfied_providers=SYSTEM_SATISFIED
        )
        initiative = await import_engine.load_target_initiative(
            user_session,
            guild_id=guild_id,
            initiative_id=(job.params or {}).get("initiative_id"),
            importer=importer,
            user=user,
        )
        result = await import_engine.apply_one_envelope(
            user_session,
            importer=importer,
            envelope=envelope,
            target_initiative=initiative,
            user=user,
            people_map=(job.params or {}).get("people_map"),
            exclude_properties=(job.params or {}).get("exclude_properties"),
        )
        await user_session.commit()
    return result.model_dump(mode="json")


def _error_code(exc: Exception) -> str:
    """The job row must never accumulate content — store a short code, not an
    exception message that could echo envelope/user data."""
    if isinstance(exc, ImportEngineError):
        return exc.code
    from app.api.deps import GuildAccessError

    if isinstance(exc, GuildAccessError):
        return ImportEngineMessages.IMPORT_ACCESS_REVOKED
    return ImportEngineMessages.IMPORT_APPLY_FAILED


async def process_import_gc() -> None:
    """Expire unconfirmed/undelivered staged payloads past ``expires_at``:
    delete the payload and mark the job expired. Terminal rows keep their
    (small) result reports — only payloads are GC'd."""
    now = datetime.now(timezone.utc)
    async with db_session.SystemSessionLocal() as session:
        await set_rls_context(session)
        guild_ids = list(
            await session.exec(
                select(Guild.id)
                .where(Guild.status == GuildStatus.active.value)
                .order_by(Guild.id.asc())
            )
        )
        for guild_id in guild_ids:
            session.expunge_all()
            await set_rls_context(session, guild_id=guild_id)
            jobs = list(
                await session.exec(
                    select(ImportJob).where(
                        ImportJob.status.in_(
                            (
                                ImportJobStatus.staged,
                                ImportJobStatus.fetching,
                                ImportJobStatus.queued,
                            )
                        ),
                        ImportJob.expires_at.is_not(None),
                        ImportJob.expires_at < now,
                    )
                )
            )
            for job in jobs:
                import_engine.delete_payload(guild_id, job.payload_ref)
                job.secret_encrypted = None
                job.status = ImportJobStatus.expired
                job.payload_ref = None
                job.updated_at = now
                session.add(job)
            await session.commit()
