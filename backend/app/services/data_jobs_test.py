"""The shared data-job dispatcher's module-level pieces: shutdown stops every
dispatcher's jobs. Claiming, slots and the sweep are tested through imports."""

import asyncio

import pytest

from app.services import data_jobs
from app.services.export import worker as export_worker
from app.services.import_engine import worker as import_worker


@pytest.mark.unit
async def test_cancel_running_jobs_stops_imports_and_exports(monkeypatch):
    render = asyncio.create_task(asyncio.sleep(3600))
    apply = asyncio.create_task(asyncio.sleep(3600))
    monkeypatch.setitem(export_worker.jobs.running, (1, 1), ("render", render))
    monkeypatch.setitem(import_worker.jobs.running, (2, 2), ("apply", apply))

    await data_jobs.cancel_running_jobs()

    assert render.cancelled() and apply.cancelled()
