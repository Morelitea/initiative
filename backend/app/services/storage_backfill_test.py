"""Tests for the in-process backfill runner's status mapping."""

from __future__ import annotations

import pytest

from app.db.backfill_uploads_to_s3 import BackfillSummary
from app.services import storage_backfill


@pytest.mark.unit
async def test_runner_reports_already_running_as_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When another worker holds the cluster-wide advisory lock the job returns a
    no-op summary (already_running). The runner must surface that as a failure with
    an explanatory error, not a misleading "complete, copied=0"."""

    async def _locked_out() -> BackfillSummary:
        return BackfillSummary(already_running=True)

    monkeypatch.setattr(storage_backfill, "backfill_uploads_to_s3", _locked_out)
    monkeypatch.setattr(
        storage_backfill, "_state", storage_backfill.BackfillState(status="running")
    )

    await storage_backfill._run()

    status = storage_backfill.get_status()
    assert status["status"] == "failed"
    assert "already running" in (status["error"] or "")
    assert status["copied"] == 0


@pytest.mark.unit
async def test_runner_reports_clean_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _ok() -> BackfillSummary:
        return BackfillSummary(copied=3, skipped=1)

    monkeypatch.setattr(storage_backfill, "backfill_uploads_to_s3", _ok)
    monkeypatch.setattr(
        storage_backfill, "_state", storage_backfill.BackfillState(status="running")
    )

    await storage_backfill._run()

    status = storage_backfill.get_status()
    assert status["status"] == "complete"
    assert status["copied"] == 3
    assert status["skipped"] == 1
    assert status["error"] is None
