"""Export worker: claims queued ExportJobs, re-runs their query, renders.

The job row persists only the filter *selector*, so the worker re-executes
the source adapter's query at render time — under a session routed as the
job's CREATOR via ``establish_guild_access`` (the same resolve-and-apply
primitive the WebSocket path uses). That makes the snapshot's RLS query the
single authorization point and honors access revoked between request and
render (the job fails closed).

Jobs are claimed and run by the dispatcher exports share with imports
(``app.services.data_jobs``): a community renders one export at a time, a
process renders at most ``EXPORT_RENDER_SLOTS`` at once, and each render is a
task on its own system session. Bookkeeping (the sweep, the claim, status
flips) runs on the system engine routed into the community with ``guild_id``
alone; the policies' system leg names that login.

A render touches its row as it goes, once per artifact and at most every few
seconds, so a long export is told apart from a dead one. A ``running`` row
untouched for ``STALE_RUNNING`` that no job in this process owns has nobody
behind it, and goes back in the queue: in-flight state is only the row, and a
re-render by job id overwrites the same storage key, so starting again is
safe. A render that finds its row has been queued again, or claimed since,
stops without writing anything, so a job finishes and notifies once.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import AbstractAsyncContextManager
from datetime import datetime, timedelta, timezone

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import ExportMessages
from app.db import cohorts
from app.db import session as db_session
from app.db.session import SYSTEM_SATISFIED, set_rls_context
from app.models.platform.notification import NotificationType
from app.models.platform.user import UserStatus
from app.models.tenant.export_job import ExportJob, ExportJobStatus
from app.services import data_jobs
from app.services.data_jobs import JobOutcome
from app.services.export import engine as export_engine
from app.services.platform import accounts as accounts_service
from app.services.export import limits as export_limits
from app.services.import_engine.atlassian import throttled

logger = logging.getLogger(__name__)

EXPORT_POLL_SECONDS = 10
EXPORT_GC_POLL_SECONDS = 3600

# A ``running`` row untouched this long is a render nobody is doing any more;
# the sweep queues it again. A live render touches its row as it goes.
STALE_RUNNING = timedelta(minutes=15)

_ERROR_MAX_LEN = 500

_RENDER = "render"

#: Advisory-lock namespace for claiming a community's next export.
_CLAIM_LOCK_NS = 0x455851  # "EXQ"


class _Superseded(Exception):
    """The job's row was queued again, or claimed since, while this render
    ran: the render stops and leaves the row to whoever has it now."""


def _open_read_session(guild_id: int) -> AbstractAsyncContextManager[AsyncSession]:
    """A read-only session for rendering in ``guild_id``'s community: on the
    read replica when DATABASE_URL_QUERY names one, from the community's
    cohort. Resolved at call time, so the test harness's pools apply."""
    return cohorts.read_session(guild_id)


async def _sweep(
    session: AsyncSession, *, guild_id: int, now: datetime, own: list[int]
) -> list[JobOutcome]:
    """Queue abandoned renders again. Jobs this process is running (``own``)
    are left alone: they are known to be alive.

    Rows are locked as they are read, so a row a live render touches while
    the sweep waits for it is read again and no longer matches."""
    abandoned = list(
        await session.exec(
            select(ExportJob)
            .where(
                ExportJob.status == ExportJobStatus.running,
                ExportJob.updated_at < now - STALE_RUNNING,
                ExportJob.id.not_in(own),  # type: ignore[union-attr]
            )
            .with_for_update()
        )
    )
    for job in abandoned:
        logger.warning(
            "export render re-queued id=%s guild=%s source=%s",
            job.id,
            guild_id,
            job.source,
        )
        job.status = ExportJobStatus.queued
        job.updated_at = now
        session.add(job)
    if abandoned:
        await session.commit()
    return []


async def _render(
    session: AsyncSession, job: ExportJob, *, guild_id: int, kind: str
) -> JobOutcome | None:
    """Render a claimed job and record how it ended."""
    # The last ``updated_at`` this render wrote, starting with the claim's.
    # A row that says anything else has been queued again or claimed since.
    touched = job.updated_at

    async def still_ours() -> bool:
        await session.refresh(job, with_for_update=True)
        return job.status == ExportJobStatus.running and job.updated_at == touched

    async def touch() -> None:
        nonlocal touched
        if not await still_ours():
            await session.commit()
            raise _Superseded
        touched = datetime.now(timezone.utc)
        job.updated_at = touched
        session.add(job)
        await session.commit()

    try:
        location = await _execute(
            session, job, guild_id=guild_id, heartbeat=throttled(touch)
        )
    except _Superseded:
        logger.info("export render superseded id=%s guild=%s", job.id, guild_id)
        return None
    except Exception as exc:  # fail closed: no partial artifact is served
        logger.exception(
            "export job failed id=%s guild=%s source=%s",
            job.id,
            guild_id,
            job.source,
        )
        # Whatever failed may have been a heartbeat's write; start clean.
        await session.rollback()
        if not await still_ours():
            await session.commit()
            return None
        job.status = ExportJobStatus.failed
        job.error = _error_code(exc)
    else:
        if not await still_ours():
            await session.commit()
            logger.info("export render superseded id=%s guild=%s", job.id, guild_id)
            return None
        job.status = ExportJobStatus.done
        job.artifact_ref = location.artifact_ref
        job.destination_ref = location.destination_ref
        job.error = None
        # Only an artifact the app holds has a GC deadline. A delivered
        # archive sits in the operator's destination under whatever
        # retention they keep there, and is not ours to sweep up.
        job.expires_at = (
            datetime.now(timezone.utc)
            + timedelta(hours=export_limits.EXPORT_ARTIFACT_TTL_HOURS)
            if location.artifact_ref
            else None
        )
    job.updated_at = datetime.now(timezone.utc)
    session.add(job)
    await session.commit()
    # The creator may have navigated away while the render ran — an inbox
    # entry is how they reach the artifact afterwards. Data mirrors the
    # other notification payloads: ids only plus what the bell displays.
    return (
        job.created_by,
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


_jobs: data_jobs.Dispatcher[ExportJob] = data_jobs.Dispatcher(
    name="export",
    model=ExportJob,
    lock_namespace=_CLAIM_LOCK_NS,
    queued=ExportJobStatus.queued,
    active=(ExportJobStatus.running,),
    kinds=(_RENDER,),
    kind_of=lambda _job: _RENDER,
    start_status=lambda _kind: ExportJobStatus.running,
    slots=lambda _kind: export_limits.EXPORT_RENDER_SLOTS,
    sweep=_sweep,
    run=_render,
)


async def process_export_jobs() -> None:
    """Run passes until one starts nothing, waiting for each pass's jobs.

    Everything queued is dealt with by the time this returns. The background
    loop calls :func:`dispatch_export_jobs` instead, which does not wait.
    """
    await _jobs.process()


async def dispatch_export_jobs() -> list[asyncio.Task[None]]:
    """One pass: queue abandoned renders again, then start what the free
    slots can take, at most one export per community. Returns the tasks it
    started; each renders, records its outcome and notifies on its own."""
    return await _jobs.dispatch()


async def _execute(
    session: AsyncSession,
    job: ExportJob,
    *,
    guild_id: int,
    heartbeat: data_jobs.Heartbeat,
) -> export_engine.ArtifactLocation:
    """Re-run the adapter query as the job's creator and render it out."""
    from app.api.deps import establish_guild_access

    adapter = export_engine.get_adapter(job.source, job.format)

    # The session is routed into the guild here, which is not somewhere an
    # account may be read; the creator comes off the system engine instead.
    user = await accounts_service.load_one(job.created_by)
    if user is None or user.status != UserStatus.active:
        raise export_engine.ExportError(ExportMessages.EXPORT_CREATOR_INACTIVE)

    async with _open_read_session(guild_id) as user_session:
        # Resolve membership/PAM and route the session as the creator; raises
        # GuildAccessError (-> failed job) if their access is gone. The job is
        # user-attributed system work — its enqueueing request already passed
        # the guild auth-policy gate, so it carries the system sentinel.
        await establish_guild_access(
            user_session, user, guild_id, satisfied_providers=SYSTEM_SATISFIED
        )
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
        from app.services.export.stamp import stamp_export

        request = await apply_brand(request, user_session)
        request = stamp_export(request, user)

    assert job.id is not None
    return await export_engine.render_to_storage(
        request,
        job_id=job.id,
        source=job.source,
        tz=(job.params or {}).get("tz"),
        heartbeat=heartbeat,
    )


def _error_code(exc: Exception) -> str:
    """The job row must never accumulate content — store a short code, not an
    exception message that could echo query/user data."""
    if isinstance(exc, export_engine.ExportError):
        return exc.code[:_ERROR_MAX_LEN]
    from app.api.deps import GuildAccessError

    if isinstance(exc, GuildAccessError):
        return ExportMessages.EXPORT_ACCESS_REVOKED
    return ExportMessages.EXPORT_RENDER_FAILED


async def process_export_gc() -> None:
    """Delete artifacts past ``expires_at`` (via the storage backend, so local
    FS and S3 behave identically) and mark their jobs expired.

    Covers every community whose schema exists, whatever its status: a
    read-only or suspended community's artifacts expire like anyone's."""
    now = datetime.now(timezone.utc)
    async with db_session.SystemSessionLocal() as session:
        await set_rls_context(session)
        guild_ids = await data_jobs.provisioned_guild_ids(session)
        await session.commit()
        for guild_id in guild_ids:
            session.expunge_all()
            try:
                await set_rls_context(session, guild_id=guild_id)
                await _expire_artifacts(session, guild_id=guild_id, now=now)
            except Exception:
                # One community's failure (its schema dropped part-way
                # through the pass, say) leaves the rest to be collected.
                logger.exception("export gc failed guild=%s", guild_id)
                await session.rollback()


async def _expire_artifacts(
    session: AsyncSession, *, guild_id: int, now: datetime
) -> None:
    from app.services.storage import get_guild_storage

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
        if job.artifact_ref and storage is not None:
            try:
                await asyncio.to_thread(storage.delete, job.artifact_ref)
            except Exception:
                # Expire the row anyway: a permanently failing delete
                # (key already gone, bucket misconfig) must not pin the
                # job in ``done`` and re-fail every pass.
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
