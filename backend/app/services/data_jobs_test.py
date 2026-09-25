"""The shared data-job dispatcher's module-level pieces: shutdown stops every
dispatcher's jobs, and expiry visits every community whose schema exists.
Claiming, slots and the sweep are tested through imports."""

import asyncio

import pytest

from app.db import session as db_session
from app.db.session import set_rls_context
from app.models.platform.guild import Guild, GuildStatus
from app.services import data_jobs
from app.services.export import worker as export_worker
from app.services.import_engine import worker as import_worker
from app.testing.factories import create_guild


@pytest.mark.unit
async def test_cancel_running_jobs_stops_imports_and_exports(monkeypatch):
    render = asyncio.create_task(asyncio.sleep(3600))
    apply = asyncio.create_task(asyncio.sleep(3600))
    monkeypatch.setitem(export_worker._jobs.running, (1, 1), ("render", render))
    monkeypatch.setitem(import_worker._jobs.running, (2, 2), ("apply", apply))

    await data_jobs.cancel_running_jobs()

    assert render.cancelled() and apply.cancelled()


@pytest.mark.integration
async def test_expiry_visits_every_community_with_a_schema(session):
    """Whatever a community's status, it is visited while its schema exists;
    a row whose schema is not there is not."""
    active = await create_guild(session)
    deleted = await create_guild(session)
    deleted.status = GuildStatus.deleted.value
    session.add(deleted)
    unprovisioned = Guild(name="No schema yet")
    session.add(unprovisioned)
    await session.commit()

    async with db_session.SystemSessionLocal() as system:
        await set_rls_context(system)
        guild_ids = await data_jobs.provisioned_guild_ids(system)

    assert active.id in guild_ids
    assert deleted.id in guild_ids
    assert unprovisioned.id not in guild_ids
