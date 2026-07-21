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
from app.models.platform.user import User, UserStatus
from app.models.tenant.import_job import ImportJob, ImportJobStatus
from app.services.import_engine import engine as import_engine
from app.services.import_engine.contract import ImportEngineError
from app.services.platform import user_notifications

logger = logging.getLogger(__name__)

IMPORT_POLL_SECONDS = 10
IMPORT_GC_POLL_SECONDS = 3600

# A ``running`` row untouched this long is a crashed apply. Unlike exports it
# is NOT re-claimed (see module docstring) — it is failed closed.
STALE_RUNNING = timedelta(minutes=15)


def _open_user_session() -> AsyncSession:
    """Late-bound (module attribute lookup at call time) so the test
    harness's sessionmaker patches apply to the worker too."""
    return db_session.AsyncSessionLocal()


async def process_import_jobs() -> None:
    now = datetime.now(timezone.utc)
    async with db_session.AdminSessionLocal() as session:
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
            await set_rls_context(session, guild_id=guild_id, guild_role="admin")
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
        session.add(job)
        outcomes.append(_outcome(job, guild_id))
    if stale:
        await session.commit()

    jobs = list(
        await session.exec(
            select(ImportJob)
            .where(ImportJob.status == ImportJobStatus.queued)
            .order_by(ImportJob.created_at.asc())
        )
    )
    for job in jobs:
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
        job.payload_ref = None
        session.add(job)
        await session.commit()
        outcomes.append(_outcome(job, guild_id))
    return outcomes


def _outcome(job: ImportJob, guild_id: int) -> JobOutcome:
    return (
        job.created_by_id,
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

    user = (
        await session.exec(select(User).where(User.id == job.created_by_id))
    ).first()
    if user is None or user.status != UserStatus.active:
        raise ImportEngineError(ImportEngineMessages.IMPORT_CREATOR_INACTIVE)

    if not job.payload_ref:
        raise ImportEngineError(ImportEngineMessages.IMPORT_INVALID_PARAMS)
    payload = import_engine.read_payload(guild_id, job.payload_ref)
    if payload is None:
        raise ImportEngineError(ImportEngineMessages.IMPORT_INVALID_PARAMS)

    if job.source == "backup":
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
        result = await importer.apply(
            user_session,
            envelope=envelope,
            target_initiative=initiative,
            importer=user,
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
    async with db_session.AdminSessionLocal() as session:
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
            await set_rls_context(session, guild_id=guild_id, guild_role="admin")
            jobs = list(
                await session.exec(
                    select(ImportJob).where(
                        ImportJob.status.in_(
                            (ImportJobStatus.staged, ImportJobStatus.queued)
                        ),
                        ImportJob.expires_at.is_not(None),
                        ImportJob.expires_at < now,
                    )
                )
            )
            for job in jobs:
                import_engine.delete_payload(guild_id, job.payload_ref)
                job.status = ImportJobStatus.expired
                job.payload_ref = None
                job.updated_at = now
                session.add(job)
            await session.commit()
