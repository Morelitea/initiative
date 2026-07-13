"""Export worker: claims queued ExportJobs, re-runs their query, renders.

The job row persists only the filter *selector*, so the worker re-executes
the source adapter's query at render time — under a session routed as the
job's CREATOR via ``establish_guild_access`` (the same resolve-and-apply
primitive the WebSocket path uses). That makes the snapshot's RLS query the
single authorization point, honors access revoked between request and render
(the job fails closed), and makes crash recovery inherent: in-flight state is
only the row, so re-claiming a stale ``running`` row and re-rendering by
job id is safe (idempotent overwrite of the same storage key).

Job *bookkeeping* (scan/claim/status flips) can't run as the creator — the
worker doesn't know who that is until it reads the row — so it runs routed as
a synthetic guild admin (the own-row policies' admin leg), mirroring the
trash-purge maintenance pattern.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.db import session as db_session
from app.db.session import set_rls_context
from app.models.platform.guild import Guild, GuildStatus
from app.models.platform.notification import NotificationType
from app.models.platform.user import User, UserStatus
from app.models.tenant.export_job import ExportJob, ExportJobStatus
from app.services.export import engine as export_engine
from app.services.platform import user_notifications

logger = logging.getLogger(__name__)

EXPORT_POLL_SECONDS = 10
EXPORT_GC_POLL_SECONDS = 3600

# A ``running`` row untouched this long is a crashed render — re-claim it.
STALE_RUNNING = timedelta(minutes=15)

_ERROR_MAX_LEN = 500


def _open_user_session() -> AsyncSession:
    """Late-bound (module attribute lookup at call time) so the test
    harness's sessionmaker patches apply to the worker too."""
    return db_session.AsyncSessionLocal()


async def process_export_jobs() -> None:
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
    jobs = list(
        await session.exec(
            select(ExportJob)
            .where(
                (ExportJob.status == ExportJobStatus.queued)
                | (
                    (ExportJob.status == ExportJobStatus.running)
                    & (ExportJob.updated_at < now - STALE_RUNNING)
                )
            )
            .order_by(ExportJob.created_at.asc())
        )
    )
    outcomes: list[JobOutcome] = []
    for job in jobs:
        job.status = ExportJobStatus.running
        job.updated_at = now
        session.add(job)
        # Commit the claim before the (slow) render, so a crash mid-render
        # leaves a stale ``running`` row for the next pass, not a lost job.
        await session.commit()
        try:
            artifact_ref = await _execute(session, job, guild_id=guild_id)
        except Exception as exc:  # fail closed: no partial artifact is served
            logger.exception(
                "export job failed id=%s guild=%s source=%s",
                job.id,
                guild_id,
                job.source,
            )
            job.status = ExportJobStatus.failed
            job.error = _error_code(exc)
        else:
            job.status = ExportJobStatus.done
            job.artifact_ref = artifact_ref
            job.error = None
            job.expires_at = datetime.now(timezone.utc) + timedelta(
                hours=settings.EXPORT_ARTIFACT_TTL_HOURS
            )
        job.updated_at = datetime.now(timezone.utc)
        session.add(job)
        await session.commit()
        # The creator may have navigated away while the render ran — an inbox
        # entry is how they reach the artifact afterwards. Data mirrors the
        # other notification payloads: ids only plus what the bell displays.
        outcomes.append(
            (
                job.created_by_id,
                NotificationType.export_ready
                if job.status == ExportJobStatus.done
                else NotificationType.export_failed,
                {
                    "guild_id": guild_id,
                    "export_job_id": job.id,
                    "source": job.source,
                    "format": job.format,
                },
            )
        )
    return outcomes


async def _execute(session: AsyncSession, job: ExportJob, *, guild_id: int) -> str:
    """Re-run the adapter query as the job's creator and render to storage."""
    from app.api.deps import establish_guild_access

    adapter = export_engine.get_adapter(job.source, job.format)

    user = (
        await session.exec(select(User).where(User.id == job.created_by_id))
    ).first()
    if user is None or user.status != UserStatus.active:
        raise export_engine.ExportError("EXPORT_CREATOR_INACTIVE")

    async with _open_user_session() as user_session:
        # Resolve membership/PAM and route the session as the creator; raises
        # GuildAccessError (-> failed job) if their access is gone.
        await establish_guild_access(user_session, user, guild_id)
        request = await adapter.build(
            user_session,
            user=user,
            guild_id=guild_id,
            params=job.params or {},
            format=job.format,
        )
        # Load the guild brand while the routed session is still open (it
        # reads the shared guild row); the icon bytes ride on the request.
        from app.services.export.branding import apply_brand

        request = await apply_brand(request, user_session)

    return await export_engine.render_to_storage(request, job_id=job.id)


def _error_code(exc: Exception) -> str:
    """The job row must never accumulate content — store a short code, not an
    exception message that could echo query/user data."""
    if isinstance(exc, export_engine.ExportError):
        return exc.code[:_ERROR_MAX_LEN]
    from app.api.deps import GuildAccessError

    if isinstance(exc, GuildAccessError):
        return "EXPORT_ACCESS_REVOKED"
    return "EXPORT_RENDER_FAILED"


async def process_export_gc() -> None:
    """Delete artifacts past ``expires_at`` (via the storage backend, so local
    FS and S3 behave identically) and mark their jobs expired."""
    from app.services.storage import get_guild_storage

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
                    select(ExportJob).where(
                        ExportJob.status == ExportJobStatus.done,
                        ExportJob.expires_at.is_not(None),
                        ExportJob.expires_at < now,
                    )
                )
            )
            storage = get_guild_storage(guild_id) if jobs else None
            for job in jobs:
                if job.artifact_ref:
                    try:
                        storage.delete(job.artifact_ref)
                    except Exception:
                        # Expire the row anyway: a permanently failing delete
                        # (key already gone, bucket misconfig) must not pin the
                        # job in ``done`` and re-fail every pass — that would
                        # also abort GC for every guild after this one.
                        logger.exception(
                            "export gc: artifact delete failed job=%s ref=%s guild=%s",
                            job.id,
                            job.artifact_ref,
                            guild_id,
                        )
                job.status = ExportJobStatus.expired
                job.artifact_ref = None
                job.updated_at = now
                session.add(job)
            await session.commit()
