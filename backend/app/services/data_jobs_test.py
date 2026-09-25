"""The shared data-job dispatcher's own bookkeeping: slots by kind, the jobs
it owns, cancellation, the heartbeat throttle, and which communities expiry
visits."""

import asyncio
from contextlib import suppress

import pytest

from app.db import session as db_session
from app.db.session import set_rls_context
from app.models.platform.guild import Guild, GuildStatus
from app.models.tenant.export_job import ExportJob
from app.services import data_jobs
from app.testing.factories import create_guild


def _dispatcher(slots: dict[str, int]) -> data_jobs.Dispatcher[ExportJob]:
    async def sweep(session, *, guild_id, now, own):
        return []

    async def run(session, job, *, guild_id, kind):
        return None

    return data_jobs.Dispatcher(
        name="test",
        model=ExportJob,
        lock_namespace=0x545354,
        queued="queued",
        active=("running",),
        kinds=tuple(slots),
        kind_of=lambda _job: next(iter(slots)),
        start_status=lambda _kind: "running",
        slots=lambda kind: slots[kind],
        sweep=sweep,
        run=run,
    )


async def _idle() -> asyncio.Task[None]:
    return asyncio.create_task(asyncio.sleep(3600))


async def _stop(tasks: list[asyncio.Task[None]]) -> None:
    for task in tasks:
        task.cancel()
    for task in tasks:
        with suppress(asyncio.CancelledError):
            await task


@pytest.mark.unit
async def test_slots_are_counted_by_kind():
    slots = {"fetch": 1, "apply": 2}
    dispatcher = _dispatcher(slots)
    tasks = [await _idle() for _ in range(2)]
    try:
        dispatcher.running[(1, 10)] = ("fetch", tasks[0])
        dispatcher.running[(2, 20)] = ("apply", tasks[1])

        assert dispatcher.free_slot("fetch") is False
        assert dispatcher.free_slot("apply") is True
        # Read on every call, so a changed limit applies to the next claim.
        slots["fetch"] = 2
        assert dispatcher.free_slot("fetch") is True
    finally:
        await _stop(tasks)


@pytest.mark.unit
async def test_own_job_ids_are_the_communitys_alone():
    dispatcher = _dispatcher({"render": 2})
    tasks = [await _idle() for _ in range(3)]
    try:
        dispatcher.running[(1, 10)] = ("render", tasks[0])
        dispatcher.running[(1, 11)] = ("render", tasks[1])
        dispatcher.running[(2, 10)] = ("render", tasks[2])

        assert sorted(dispatcher.own_job_ids(1)) == [10, 11]
        assert dispatcher.own_job_ids(3) == []
    finally:
        await _stop(tasks)


@pytest.mark.unit
async def test_cancel_running_jobs_stops_every_dispatchers_jobs():
    first = _dispatcher({"render": 1})
    second = _dispatcher({"apply": 1})
    one, two = await _idle(), await _idle()
    first.running[(1, 1)] = ("render", one)
    second.running[(2, 2)] = ("apply", two)

    await data_jobs.cancel_running_jobs()

    assert one.cancelled() and two.cancelled()


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
