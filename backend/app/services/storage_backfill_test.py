"""Tests for the UNLOGGED-table backfill runner (shared cross-worker status).

The ``storage_backfill_state`` UNLOGGED table is created lazily at runtime and is
RLS-forced, reachable only by the ``app_admin`` (BYPASSRLS) engine — these drive
it through ``role_session("app_admin")``, the real production privilege boundary.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text

from app.db.backfill_uploads_to_s3 import BackfillSummary
from app.services import storage_backfill


@pytest.fixture
async def admin_session(role_session):
    return await role_session("app_admin")


@pytest.fixture(autouse=True)
async def _reset_backfill_row(admin_session):
    """Create the table (if needed) and reset the singleton to idle before each
    test — the UNLOGGED table persists across tests within a worker."""
    await storage_backfill.get_status(admin_session)  # ensures table + row
    await admin_session.execute(
        text(
            "UPDATE storage_backfill_state SET status = 'idle', heartbeat = NULL, "
            "started_at = NULL, finished_at = NULL, copied = 0, skipped = 0, "
            "failed = 0, hash_mismatches = 0, error = NULL"
        )
    )
    await admin_session.commit()
    yield


@pytest.mark.integration
async def test_get_status_creates_idle_row(admin_session) -> None:
    row = await storage_backfill.get_status(admin_session)
    assert row["status"] == "idle"
    assert row["copied"] == 0


@pytest.mark.integration
async def test_claim_then_conflict(admin_session) -> None:
    """The first claim wins and flips the row to running; a second concurrent
    claim (any worker) loses — this is the cross-worker start guard."""
    assert await storage_backfill.try_claim(admin_session) is True
    row = await storage_backfill.get_status(admin_session)
    assert row["status"] == "running"
    assert row["started_at"] is not None

    assert await storage_backfill.try_claim(admin_session) is False


@pytest.mark.integration
async def test_stale_running_can_be_reclaimed(admin_session) -> None:
    """A 'running' row whose heartbeat has gone stale (dead worker) is reclaimable
    so a backfill can't be wedged forever by a crash."""
    assert await storage_backfill.try_claim(admin_session) is True
    await admin_session.execute(
        text("UPDATE storage_backfill_state SET heartbeat = :hb"),
        {"hb": storage_backfill._now() - timedelta(hours=2)},
    )
    await admin_session.commit()

    assert await storage_backfill.try_claim(admin_session) is True


@pytest.mark.integration
async def test_start_backfill_conflict_raises(admin_session, monkeypatch) -> None:
    """start_backfill claims synchronously and raises on a lost claim — the start
    path no longer 'returns too early' before the guard is checked."""

    async def _noop() -> None:
        return None

    # Don't run the real copy task (it would open its own admin session); we only
    # assert the synchronous claim/guard behaviour.
    monkeypatch.setattr(storage_backfill, "_run", _noop)

    row = await storage_backfill.start_backfill(admin_session)
    assert row["status"] == "running"

    with pytest.raises(storage_backfill.BackfillAlreadyRunning):
        await storage_backfill.start_backfill(admin_session)


@pytest.mark.integration
async def test_finalize_maps_outcomes(admin_session) -> None:
    await storage_backfill.try_claim(admin_session)
    await storage_backfill._finalize(
        admin_session, summary=BackfillSummary(copied=3, skipped=1)
    )
    row = await storage_backfill.get_status(admin_session)
    assert row["status"] == "complete"
    assert row["copied"] == 3 and row["skipped"] == 1
    assert row["finished_at"] is not None

    await storage_backfill.try_claim(admin_session)
    await storage_backfill._finalize(
        admin_session, summary=BackfillSummary(failed=2, failed_keys=["a", "b"])
    )
    row = await storage_backfill.get_status(admin_session)
    assert row["status"] == "failed"
    assert row["failed"] == 2
    assert list(row["failed_keys"]) == ["a", "b"]

    await storage_backfill.try_claim(admin_session)
    await storage_backfill._finalize(
        admin_session, summary=BackfillSummary(already_running=True)
    )
    row = await storage_backfill.get_status(admin_session)
    assert row["status"] == "failed"
    assert row["error"] and "already running" in row["error"]

    await storage_backfill.try_claim(admin_session)
    await storage_backfill._finalize(admin_session, error="boom")
    row = await storage_backfill.get_status(admin_session)
    assert row["status"] == "failed"
    assert row["error"] == "boom"
