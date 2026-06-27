"""DB-backed runner + status for the local->S3 upload backfill.

Wraps :func:`app.db.backfill_uploads_to_s3.backfill_uploads_to_s3` so the Storage
settings tab can kick off the migration and poll its progress. The backfill reads
every guild schema via the provisioning (superuser) engine and writes through a
single S3 client built from the *saved* DB config snapshot, so it works while the
app is still serving on ``local`` (the documented cutover order).

Status lives in the ``storage_backfill_state`` singleton (id=1), not in process
memory, so **every worker reports the same status** — the previous in-memory
version showed running/failed/idle inconsistently across a multi-worker
deployment, and a start request that lost the race could be wrongly accepted.

The start path is an **atomic DB claim**: a single conditional UPDATE flips the
row to ``running`` only if it isn't already running (or its heartbeat has gone
stale, i.e. the worker that claimed it died). Whoever wins the UPDATE owns the
run; everyone else gets a conflict immediately, before any work starts. The copy
loop additionally holds a Postgres advisory lock (in ``backfill_uploads_to_s3``)
as the hard guard against the CLI racing a UI run.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.backfill_uploads_to_s3 import BackfillSummary, backfill_uploads_to_s3
from app.db.session import AdminSessionLocal, reapply_rls_context
from app.models.platform.storage_backfill_state import StorageBackfillState

logger = logging.getLogger(__name__)

GLOBAL_ID = 1
# A 'running' row whose heartbeat is older than this is treated as a dead worker
# and may be reclaimed. The copy loop's advisory lock is the real concurrency
# guard, so a too-eager reclaim still can't cause a double copy.
_STALE_AFTER = timedelta(minutes=15)


class BackfillAlreadyRunning(RuntimeError):
    """Raised when a backfill is already running (the claim was lost)."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _ensure_row(session: AsyncSession) -> StorageBackfillState:
    row = await session.get(StorageBackfillState, GLOBAL_ID)
    if row is None:
        row = StorageBackfillState(id=GLOBAL_ID)
        session.add(row)
        await session.commit()
        await reapply_rls_context(session)
        await session.refresh(row)
    return row


async def get_status(session: AsyncSession) -> StorageBackfillState:
    """Return the shared status row (created idle on first read)."""
    return await _ensure_row(session)


async def try_claim(session: AsyncSession) -> bool:
    """Atomically claim the singleton for a new run. Returns True if claimed.

    The conditional UPDATE is the cross-worker guard: only one worker's UPDATE can
    match (status not running, or running-but-stale) and flip the row to running,
    so concurrent starts on different workers can't both proceed.
    """
    await _ensure_row(session)
    now = _now()
    result = await session.execute(
        update(StorageBackfillState)
        .where(
            StorageBackfillState.id == GLOBAL_ID,
            or_(
                StorageBackfillState.status != "running",
                StorageBackfillState.heartbeat < now - _STALE_AFTER,
                StorageBackfillState.heartbeat.is_(None),
            ),
        )
        .values(
            status="running",
            started_at=now,
            finished_at=None,
            heartbeat=now,
            copied=0,
            skipped=0,
            failed=0,
            hash_mismatches=0,
            failed_keys=[],
            error=None,
        )
    )
    await session.commit()
    await reapply_rls_context(session)
    return (result.rowcount or 0) == 1


async def _persist(
    session: AsyncSession,
    *,
    status: str,
    summary: BackfillSummary | None = None,
    error: str | None = None,
    finished: bool = False,
) -> None:
    values: dict = {"status": status, "heartbeat": _now()}
    if summary is not None:
        values.update(
            copied=summary.copied,
            skipped=summary.skipped,
            failed=summary.failed,
            hash_mismatches=summary.hash_mismatches,
            failed_keys=list(summary.failed_keys),
        )
    if error is not None:
        values["error"] = error
    if finished:
        values["finished_at"] = _now()
    await session.execute(
        update(StorageBackfillState)
        .where(StorageBackfillState.id == GLOBAL_ID)
        .values(**values)
    )
    await session.commit()
    await reapply_rls_context(session)


async def _finalize(
    session: AsyncSession,
    *,
    summary: BackfillSummary | None = None,
    error: str | None = None,
) -> None:
    """Write the terminal status of a run to the shared row."""
    if error is not None:
        await _persist(session, status="failed", error=error, finished=True)
    elif summary is not None and summary.already_running:
        # The copy loop's advisory lock was held elsewhere (e.g. the CLI), so this
        # run copied nothing. Report it rather than a misleading "complete,
        # copied=0".
        await _persist(
            session,
            status="failed",
            summary=summary,
            error="another backfill is already running",
            finished=True,
        )
    else:
        assert summary is not None
        await _persist(
            session,
            status="failed" if summary.failed else "complete",
            summary=summary,
            finished=True,
        )


async def _run() -> None:
    """Detached task: run the backfill with its own admin session and persist
    progress + the final outcome to the shared row."""
    async with AdminSessionLocal() as session:

        async def _on_progress(summary: BackfillSummary) -> None:
            await _persist(session, status="running", summary=summary)

        try:
            summary = await backfill_uploads_to_s3(on_progress=_on_progress)
            await _finalize(session, summary=summary)
        except Exception as exc:  # noqa: BLE001 — surface the failure in status
            logger.exception("storage backfill failed")
            await _finalize(session, error=str(exc))


async def start_backfill(session: AsyncSession) -> StorageBackfillState:
    """Claim and launch a backfill. Raises ``BackfillAlreadyRunning`` if one is
    already in progress (cluster-wide)."""
    if not await try_claim(session):
        raise BackfillAlreadyRunning()
    asyncio.create_task(_run())
    return await _ensure_row(session)
