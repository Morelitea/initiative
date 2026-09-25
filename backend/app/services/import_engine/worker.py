"""Import worker: claims queued ImportJobs, re-validates, applies.

Jobs are claimed and run by the dispatcher imports share with exports
(``app.services.data_jobs``): a community runs one import at a time, a process
runs at most ``IMPORT_FETCH_SLOTS`` fetches and ``IMPORT_APPLY_SLOTS`` applies
at once, and each job is a task on its own system session. Bookkeeping (the
sweep, the claim, status flips) runs on the system engine routed into the
community with ``guild_id`` alone; the policies' system leg names that login.
The apply itself runs on a fresh session from the community's cohort, routed
as the job's CREATOR via ``establish_guild_access`` (revoked access between
request and apply fails the job closed, and the target initiative + create
permission are re-checked at apply time for the same reason).

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

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import ImportEngineMessages
from app.db import cohorts
from app.db import session as db_session
from app.db.session import SYSTEM_SATISFIED, set_rls_context
from app.models.platform.notification import NotificationType
from app.models.platform.user import UserStatus
from app.models.tenant.import_job import ImportJob, ImportJobStatus
from app.services import data_jobs
from app.services.data_jobs import JobOutcome
from app.services.import_engine import atlassian_job
from app.services.import_engine.atlassian import throttled
from app.services.import_engine import engine as import_engine
from app.services.platform import accounts as accounts_service
from app.services.import_engine.contract import ImportEngineError
from app.services.import_engine import limits as import_limits

logger = logging.getLogger(__name__)

IMPORT_POLL_SECONDS = 10
IMPORT_GC_POLL_SECONDS = 3600

# A ``running`` row untouched this long is a crashed apply. Unlike exports it
# is NOT re-claimed (see module docstring); the sweep marks it failed. A live
# apply touches its row as it goes.
STALE_RUNNING = timedelta(minutes=15)

# A ``fetching`` row untouched this long is a crashed fetch. A live one
# touches its row every few seconds between calls to the site, and no single
# call outlasts this (see ``atlassian.RetryPolicy``), so a row this quiet has
# nobody behind it.
STALE_FETCHING = timedelta(minutes=15)


def _open_user_session(guild_id: int) -> AsyncSession:
    """A request-path session from ``guild_id``'s cohort. Resolved at call
    time, so the test harness's pools apply to the worker too."""
    return cohorts.request_sessionmaker(guild_id)()


_FETCH = "fetch"
_APPLY = "apply"

#: Advisory-lock namespace for claiming a community's next import.
_CLAIM_LOCK_NS = 0x494D51  # "IMQ"


def _slots(kind: str) -> int:
    return (
        import_limits.IMPORT_FETCH_SLOTS
        if kind == _FETCH
        else import_limits.IMPORT_APPLY_SLOTS
    )


def _kind_of(job: ImportJob) -> str:
    return _FETCH if atlassian_job.awaits_fetch(job) else _APPLY


def _start_status(kind: str) -> str:
    return ImportJobStatus.fetching if kind == _FETCH else ImportJobStatus.running


async def _sweep(
    session: AsyncSession, *, guild_id: int, now: datetime, own: list[int]
) -> list[JobOutcome]:
    """Fail interrupted applies and queue abandoned fetches again. Jobs this
    process is running (``own``) are left alone: their rows are fresh, and
    they are known to be alive.

    Rows are locked as they are read, so a row a live job touches while the
    sweep waits for it is read again and no longer matches."""
    outcomes: list[JobOutcome] = []

    # Fail interrupted applies closed — never re-run them (duplicates).
    stale = list(
        await session.exec(
            select(ImportJob)
            .where(
                ImportJob.status == ImportJobStatus.running,
                ImportJob.updated_at < now - STALE_RUNNING,
                ImportJob.id.not_in(own),  # type: ignore[union-attr]
            )
            .with_for_update()
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
        await asyncio.to_thread(import_engine.delete_payload, guild_id, job.payload_ref)
        job.payload_ref = None
        job.secret_encrypted = None
        session.add(job)
        outcomes.append(_outcome(job, guild_id))
    if stale:
        await session.commit()

    # Re-claim abandoned fetches. Nothing content-side was written, so the
    # partial payload is discarded and the job queues again from the start.
    abandoned = list(
        await session.exec(
            select(ImportJob)
            .where(
                ImportJob.status == ImportJobStatus.fetching,
                ImportJob.updated_at < now - STALE_FETCHING,
                ImportJob.id.not_in(own),  # type: ignore[union-attr]
            )
            .with_for_update()
        )
    )
    for job in abandoned:
        logger.warning(
            "import fetch re-claimed id=%s guild=%s source=%s",
            job.id,
            guild_id,
            job.source,
        )
        await asyncio.to_thread(import_engine.delete_payload, guild_id, job.payload_ref)
        job.payload_ref = None
        job.status = ImportJobStatus.queued
        job.updated_at = now
        session.add(job)
    if abandoned:
        await session.commit()
    return outcomes


async def _run(
    session: AsyncSession, job: ImportJob, *, guild_id: int, kind: str
) -> JobOutcome | None:
    """One claimed job: a fetch or an apply, by the slot it holds."""
    if kind == _FETCH:
        return await _fetch(session, job, guild_id=guild_id)
    return await _apply(session, job, guild_id=guild_id)


_jobs: data_jobs.Dispatcher[ImportJob] = data_jobs.Dispatcher(
    name="import",
    model=ImportJob,
    lock_namespace=_CLAIM_LOCK_NS,
    queued=ImportJobStatus.queued,
    active=(ImportJobStatus.fetching, ImportJobStatus.running),
    kinds=(_FETCH, _APPLY),
    kind_of=_kind_of,
    start_status=_start_status,
    slots=_slots,
    sweep=_sweep,
    run=_run,
)

#: The jobs this process is running, by ``(guild_id, job_id)``, with which
#: kind of slot each holds.
_running = _jobs.running


async def process_import_jobs() -> None:
    """Run passes until one starts nothing, waiting for each pass's jobs.

    Everything queued is dealt with by the time this returns. The background
    loop calls :func:`dispatch_import_jobs` instead, which does not wait.
    """
    await _jobs.process()


async def dispatch_import_jobs() -> list[asyncio.Task[None]]:
    """One pass: sweep every community's stale rows, then start what the free
    slots can take, at most one job per community. Returns the tasks it
    started; each runs, records its outcome and notifies on its own."""
    return await _jobs.dispatch()


async def cancel_running_jobs() -> None:
    """Stop every import this process is running, for shutdown. A stopped
    fetch is queued again by the sweep; a stopped apply is marked
    interrupted."""
    await _jobs.cancel_running()


async def _apply(session: AsyncSession, job: ImportJob, *, guild_id: int) -> JobOutcome:
    """Apply a claimed job and record how it ended."""
    try:
        result = await _execute(session, job, guild_id=guild_id)
    except Exception as exc:  # the row records a code, never content
        logger.exception(
            "import job failed id=%s guild=%s source=%s",
            job.id,
            guild_id,
            job.source,
        )
        # Whatever failed may have been a heartbeat's write; start clean.
        await session.rollback()
        await session.refresh(job)
        job.status = ImportJobStatus.failed
        job.error = _error_code(exc)
    else:
        job.status = ImportJobStatus.done
        job.result = result
        job.error = None
    job.updated_at = datetime.now(timezone.utc)
    await asyncio.to_thread(import_engine.delete_payload, guild_id, job.payload_ref)
    job.secret_encrypted = None
    job.payload_ref = None
    session.add(job)
    await session.commit()
    return _outcome(job, guild_id)


async def _fetch(
    session: AsyncSession, job: ImportJob, *, guild_id: int
) -> JobOutcome | None:
    """Read a foreign source into a bundle and park the job for review. The
    job was claimed as ``fetching`` by :func:`_claim`.

    Ends in one of three places. **Staged**, with the bundle and its plan,
    which is the wizard's review step and needs no notification — the person
    is either watching the job or will find it waiting. **Failed**, with a
    code, which does notify. Or **nowhere**, when the job was cancelled while
    the site was being read: the bundle, if one got written, is thrown away
    and the row is left as the cancel put it.

    The secret goes in every case. A staged bundle holds everything the
    apply needs, and a job that failed or was cancelled needs nothing.
    """

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
            open_user_session=lambda: _open_user_session(guild_id),
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
        await asyncio.to_thread(
            import_engine.delete_payload, guild_id, staged.payload_ref
        )
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

    if job.source in ("backup", atlassian_job.SOURCE):
        # A fetched bundle is a backup-shaped zip filing into an initiative
        # that exists, so it takes the backup path — which gates it by the
        # create permission there rather than by the community's seat.
        from app.services.import_engine import backup as backup_service

        async def touch() -> None:
            # Keeps the row's ``updated_at`` fresh, so the stale sweep knows
            # this apply is still running.
            await session.refresh(job, with_for_update=True)
            job.updated_at = datetime.now(timezone.utc)
            session.add(job)
            await session.commit()

        async with import_engine.open_payload(guild_id, job.payload_ref) as bundle:
            if bundle is None:
                raise ImportEngineError(ImportEngineMessages.IMPORT_INVALID_PARAMS)
            async with _open_user_session(guild_id) as user_session:
                # Route as the creator; apply_backup re-verifies REAL guild
                # adminship and owns its own per-chunk commits + refreshes. As
                # user-attributed system work whose enqueueing request already
                # passed the guild auth-policy gate, it carries the system
                # sentinel.
                await establish_guild_access(
                    user_session, user, guild_id, satisfied_providers=SYSTEM_SATISFIED
                )
                backup_result = await backup_service.apply_backup(
                    user_session,
                    user=user,
                    guild_id=guild_id,
                    payload=bundle,
                    include=(job.params or {}).get("include"),
                    people_map=(job.params or {}).get("people_map"),
                    exclude_properties=(job.params or {}).get("exclude_properties"),
                    heartbeat=throttled(touch),
                    # A fetched bundle is one this app wrote, and is held to
                    # the fetch's bounds rather than an upload's.
                    fetched=job.source == atlassian_job.SOURCE,
                )
        return backup_result.model_dump(mode="json")

    payload = await asyncio.to_thread(
        import_engine.read_payload, guild_id, job.payload_ref
    )
    if payload is None:
        raise ImportEngineError(ImportEngineMessages.IMPORT_INVALID_PARAMS)
    importer = import_engine.get_importer(job.source)
    envelope = importer.validate(await asyncio.to_thread(json.loads, payload))

    async with _open_user_session(guild_id) as user_session:
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
    (small) result reports — only payloads are GC'd — and any secret one
    still holds is cleared.

    Covers every community whose schema exists, whatever its status: a
    read-only or suspended community's payloads expire like anyone's."""
    now = datetime.now(timezone.utc)
    async with db_session.SystemSessionLocal() as session:
        await set_rls_context(session)
        guild_ids = await data_jobs.provisioned_guild_ids(session)
        await session.commit()
        for guild_id in guild_ids:
            session.expunge_all()
            try:
                await set_rls_context(session, guild_id=guild_id)
                await _expire_payloads(session, guild_id=guild_id, now=now)
            except Exception:
                # One community's failure (its schema dropped part-way
                # through the pass, say) leaves the rest to be collected.
                logger.exception("import gc failed guild=%s", guild_id)
                await session.rollback()


async def _expire_payloads(
    session: AsyncSession, *, guild_id: int, now: datetime
) -> None:
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
        await asyncio.to_thread(import_engine.delete_payload, guild_id, job.payload_ref)
        job.secret_encrypted = None
        job.status = ImportJobStatus.expired
        job.payload_ref = None
        job.updated_at = now
        session.add(job)
    # A job that is over needs no secret, however it ended.
    lent = list(
        await session.exec(
            select(ImportJob).where(
                ImportJob.status.in_(
                    (
                        ImportJobStatus.done,
                        ImportJobStatus.failed,
                        ImportJobStatus.cancelled,
                        ImportJobStatus.expired,
                    )
                ),
                ImportJob.secret_encrypted.is_not(None),
            )
        )
    )
    for job in lent:
        job.secret_encrypted = None
        session.add(job)
    await session.commit()
