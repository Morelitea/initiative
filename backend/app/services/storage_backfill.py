"""In-process runner + status for the local->S3 upload backfill.

Wraps :func:`app.db.backfill_uploads_to_s3.backfill_uploads_to_s3` so the Storage
settings tab can kick off the migration and poll its progress. The backfill reads
every guild schema via the provisioning (superuser) engine and writes through
``s3_guild_storage`` — which now resolves the *saved* DB credentials — so it works
while the app is still serving on ``local`` (the documented cutover order).

Status is held in this module (per process). A multi-worker deploy would track a
run only in the worker that started it; for the self-host single-process default
that's exactly right, and a re-poll simply reports ``idle`` elsewhere.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from app.db.backfill_uploads_to_s3 import BackfillSummary, backfill_uploads_to_s3

logger = logging.getLogger(__name__)


@dataclass
class BackfillState:
    status: str = "idle"  # idle | running | complete | failed
    copied: int = 0
    skipped: int = 0
    failed: int = 0
    hash_mismatches: int = 0
    failed_keys: list[str] = field(default_factory=list)
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None


_state = BackfillState()
_task: asyncio.Task | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _apply_summary(summary: BackfillSummary) -> None:
    _state.copied = summary.copied
    _state.skipped = summary.skipped
    _state.failed = summary.failed
    _state.hash_mismatches = summary.hash_mismatches
    _state.failed_keys = list(summary.failed_keys)


async def _run() -> None:
    try:
        summary = await backfill_uploads_to_s3()
        _apply_summary(summary)
        _state.status = "failed" if summary.failed else "complete"
    except Exception as exc:  # noqa: BLE001 — surface the failure in status
        logger.exception("storage backfill failed")
        _state.status = "failed"
        _state.error = str(exc)
    finally:
        _state.finished_at = _now_iso()


def is_running() -> bool:
    return _state.status == "running"


def start_backfill() -> None:
    """Launch the backfill as a detached task. Caller guards configuration."""
    global _task, _state
    if is_running():
        raise RuntimeError("backfill already running")
    _state = BackfillState(status="running", started_at=_now_iso())
    _task = asyncio.create_task(_run())


def get_status() -> dict:
    return asdict(_state)
