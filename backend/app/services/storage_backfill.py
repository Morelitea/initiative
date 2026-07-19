"""Runner + shared status for the local->S3 upload backfill.

Wraps :func:`app.db.backfill_uploads_to_s3.backfill_uploads_to_s3` so the Storage
settings tab can kick off the transfer and poll its progress.

Status lives in a Postgres **UNLOGGED** singleton table ``storage_backfill_state``
(id=1) — *not* an Alembic migration. The backfill is a one-off transfer, not part
of the permanent schema, so the table is created lazily at runtime (idempotent
``CREATE UNLOGGED TABLE IF NOT EXISTS``) rather than migrated in. UNLOGGED means
its rows aren't WAL-logged (cheap, and fine to lose on a crash — you'd just re-run
the transfer). It is nonetheless **shared across workers**, so every worker
reports the same status — the earlier in-memory version showed running/failed/idle
inconsistently on a multi-worker deployment and could wrongly accept a losing
start.

The start path is an **atomic DB claim**: a single conditional UPDATE flips the
row to ``running`` only if it isn't already running (or its heartbeat has gone
stale, i.e. the worker that claimed it died). Whoever wins the UPDATE owns the
run; everyone else gets a conflict immediately, before any work starts. The copy
loop additionally holds a Postgres advisory lock (in ``backfill_uploads_to_s3``)
as the hard guard against the CLI racing a UI run.

The table is created by the superuser provisioning engine (DDL) and read/written
only by the ``app_admin`` BYPASSRLS engine; RLS is forced with no policies, so no
scoped request role can reach it.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.backfill_uploads_to_s3 import BackfillSummary, backfill_uploads_to_s3
from app.db import session as db_session
from app.db.session import AdminSessionLocal
from app.db.system_grants import SHARED_TABLE_SYSTEM_GRANTS, grant_sql

logger = logging.getLogger(__name__)

GLOBAL_ID = 1
# A 'running' row whose heartbeat is older than this is treated as a dead worker
# and may be reclaimed. The copy loop's advisory lock is the real concurrency
# guard, so a too-eager reclaim still can't cause a double copy.
_STALE_AFTER = timedelta(minutes=15)

_CREATE_TABLE = """
CREATE UNLOGGED TABLE IF NOT EXISTS storage_backfill_state (
    id integer PRIMARY KEY,
    status varchar(20) NOT NULL DEFAULT 'idle',
    copied integer NOT NULL DEFAULT 0,
    skipped integer NOT NULL DEFAULT 0,
    failed integer NOT NULL DEFAULT 0,
    hash_mismatches integer NOT NULL DEFAULT 0,
    failed_keys jsonb NOT NULL DEFAULT '[]'::jsonb,
    error varchar(2000),
    started_at timestamptz,
    finished_at timestamptz,
    heartbeat timestamptz
)
"""

# The system engine's verbs come from the audited shared-table registry, so the
# lazily-created table follows the same "decide it explicitly" discipline as the
# migrated ones (security_invariants_test compares the live catalog to it).
_ADMIN_GRANT = grant_sql(SHARED_TABLE_SYSTEM_GRANTS["storage_backfill_state"])

_table_lock = asyncio.Lock()
_table_ready = False


class BackfillAlreadyRunning(RuntimeError):
    """Raised when a backfill is already running (the claim was lost)."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _ensure_table() -> None:
    """Create the UNLOGGED status table once per process (idempotent).

    DDL runs on the superuser provisioning engine; RLS is forced with no policies
    so only the BYPASSRLS ``app_admin`` engine (which the reads/writes use) can
    reach it. ``app_admin`` is granted explicitly in case default privileges don't
    cover a runtime-created table.
    """
    global _table_ready
    if _table_ready:
        return
    async with _table_lock:
        if _table_ready:
            return
        async with db_session.provisioning_engine.begin() as conn:
            await conn.execute(text(_CREATE_TABLE))
            await conn.execute(
                text("ALTER TABLE storage_backfill_state ENABLE ROW LEVEL SECURITY")
            )
            await conn.execute(
                text("ALTER TABLE storage_backfill_state FORCE ROW LEVEL SECURITY")
            )
            # Revoke-then-grant so a table created by an earlier build (which
            # granted ALL) converges on the registry's verb set.
            await conn.execute(
                text("REVOKE ALL ON storage_backfill_state FROM app_admin")
            )
            await conn.execute(
                text(f"GRANT {_ADMIN_GRANT} ON storage_backfill_state TO app_admin")
            )
        _table_ready = True


def reset_for_tests() -> None:
    """Force the next access to re-create the table (test isolation helper)."""
    global _table_ready
    _table_ready = False


async def _fetch(session: AsyncSession) -> dict | None:
    result = await session.exec(
        text("SELECT * FROM storage_backfill_state WHERE id = :id"),
        params={"id": GLOBAL_ID},
    )
    row = result.mappings().first()
    return dict(row) if row is not None else None


async def _ensure_row(session: AsyncSession) -> None:
    await session.exec(
        text(
            "INSERT INTO storage_backfill_state (id, status) VALUES (:id, 'idle') "
            "ON CONFLICT (id) DO NOTHING"
        ),
        params={"id": GLOBAL_ID},
    )
    await session.commit()


async def get_status(session: AsyncSession) -> dict:
    """Return the shared status row (created idle on first read)."""
    await _ensure_table()
    row = await _fetch(session)
    if row is None:
        await _ensure_row(session)
        row = await _fetch(session)
    if row is None:
        raise RuntimeError("storage backfill state row missing after creation")
    return row


async def try_claim(session: AsyncSession) -> bool:
    """Atomically claim the singleton for a new run. Returns True if claimed.

    The conditional UPDATE is the cross-worker guard: only one worker's UPDATE can
    match (status not running, or running-but-stale) and flip the row to running,
    so concurrent starts on different workers can't both proceed.
    """
    await _ensure_table()
    await _ensure_row(session)
    now = _now()
    result = await session.exec(
        text(
            "UPDATE storage_backfill_state SET "
            "status = 'running', started_at = :now, finished_at = NULL, "
            "heartbeat = :now, copied = 0, skipped = 0, failed = 0, "
            "hash_mismatches = 0, failed_keys = '[]'::jsonb, error = NULL "
            "WHERE id = :id AND "
            "(status <> 'running' OR heartbeat IS NULL OR heartbeat < :stale)"
        ),
        params={"id": GLOBAL_ID, "now": now, "stale": now - _STALE_AFTER},
    )
    await session.commit()
    return (result.rowcount or 0) == 1


async def _persist(
    session: AsyncSession,
    *,
    status: str,
    summary: BackfillSummary | None = None,
    error: str | None = None,
    finished: bool = False,
) -> None:
    sets = ["status = :status", "heartbeat = :hb"]
    params: dict = {"id": GLOBAL_ID, "status": status, "hb": _now()}
    if summary is not None:
        sets += [
            "copied = :copied",
            "skipped = :skipped",
            "failed = :failed",
            "hash_mismatches = :hm",
            "failed_keys = CAST(:fk AS jsonb)",
        ]
        params.update(
            copied=summary.copied,
            skipped=summary.skipped,
            failed=summary.failed,
            hm=summary.hash_mismatches,
            fk=json.dumps(list(summary.failed_keys)),
        )
    if error is not None:
        sets.append("error = :error")
        params["error"] = error
    if finished:
        sets.append("finished_at = :fin")
        params["fin"] = _now()
    await session.exec(
        text(f"UPDATE storage_backfill_state SET {', '.join(sets)} WHERE id = :id"),
        params=params,
    )
    await session.commit()


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
        if summary is None:
            raise RuntimeError("finalize requires a summary when no error is given")
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


async def start_backfill(session: AsyncSession) -> dict:
    """Claim and launch a backfill. Raises ``BackfillAlreadyRunning`` if one is
    already in progress (cluster-wide)."""
    if not await try_claim(session):
        raise BackfillAlreadyRunning()
    asyncio.create_task(_run())
    row = await _fetch(session)
    if row is None:
        raise RuntimeError("storage backfill state row missing after claim")
    return row
