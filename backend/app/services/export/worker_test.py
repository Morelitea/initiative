"""The export worker on the shared dispatcher: one render per community at a
time, a bounded number per process, abandoned renders queued again, a render
that lost its row writing nothing, and expiry in every community whose schema
exists."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlmodel import select

from app.core.config import settings
from app.models.platform.guild import Guild, GuildRole, GuildStatus
from app.models.platform.notification import Notification, NotificationType
from app.models.tenant.export_job import ExportJob, ExportJobStatus
from app.services.export import engine as export_engine
from app.services.export import limits as export_limits
from app.services.export import worker as export_worker
from app.services.storage import get_guild_storage
from app.testing import route_session_to_guild
from app.testing.factories import create_task

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _tmp_uploads(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "UPLOADS_DIR", str(tmp_path))


@pytest.fixture(autouse=True)
def _every_export_is_a_job(monkeypatch):
    monkeypatch.setattr(export_limits, "EXPORT_INLINE_MAX_ROWS", 0)


async def _actor(acting_user, session):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    await create_task(session, a.project, title="Task")
    return a


async def _queued(client: AsyncClient, a) -> int:
    response = await client.get(a.g("/exports/tasks"), headers=a.headers)
    assert response.status_code == 202, response.text
    return response.json()["id"]


async def _status(client: AsyncClient, a, job_id: int) -> str:
    response = await client.get(a.g(f"/exports/{job_id}"), headers=a.headers)
    return response.json()["status"]


async def _ready_notices(session, a, job_id: int) -> int:
    rows = await session.exec(
        select(Notification).where(Notification.user_id == a.user.id)
    )
    return sum(
        1
        for n in rows
        if n.type == NotificationType.export_ready
        and n.data.get("export_job_id") == job_id
    )


async def _set_row(session, guild_id: int, job_id: int, **fields) -> None:
    session.expunge_all()
    await route_session_to_guild(session, guild_id)
    job = await session.get(ExportJob, job_id)
    for name, value in fields.items():
        setattr(job, name, value)
    session.add(job)
    await session.commit()


async def test_a_community_renders_one_export_at_a_time(
    client: AsyncClient, acting_user, session
):
    a = await _actor(acting_user, session)
    first, second = await _queued(client, a), await _queued(client, a)

    started = await export_worker.dispatch_export_jobs()

    assert len(started) == 1
    await asyncio.gather(*started)
    assert await _status(client, a, first) == ExportJobStatus.done.value
    assert await _status(client, a, second) == ExportJobStatus.queued.value

    await export_worker.process_export_jobs()
    assert await _status(client, a, second) == ExportJobStatus.done.value


async def test_two_communities_render_side_by_side(
    client: AsyncClient, acting_user, session
):
    a = await _actor(acting_user, session)
    b = await _actor(acting_user, session)
    first, second = await _queued(client, a), await _queued(client, b)

    started = await export_worker.dispatch_export_jobs()

    assert len(started) == 2
    await asyncio.gather(*started)
    assert await _status(client, a, first) == ExportJobStatus.done.value
    assert await _status(client, b, second) == ExportJobStatus.done.value


async def test_a_process_renders_no_more_than_its_slots(
    client: AsyncClient, acting_user, session, monkeypatch
):
    monkeypatch.setattr(export_limits, "EXPORT_RENDER_SLOTS", 1)
    a = await _actor(acting_user, session)
    b = await _actor(acting_user, session)
    await _queued(client, a)
    await _queued(client, b)

    started = await export_worker.dispatch_export_jobs()

    assert len(started) == 1
    await asyncio.gather(*started)
    await export_worker.process_export_jobs()


async def test_an_abandoned_render_is_queued_again_and_finishes_once(
    client: AsyncClient, acting_user, session
):
    """A ``running`` row nobody has touched for the stale window is rendered
    again from the start, and its creator hears about it once."""
    a = await _actor(acting_user, session)
    job_id = await _queued(client, a)
    stale = datetime.now(timezone.utc) - timedelta(minutes=30)
    await _set_row(
        session, a.guild.id, job_id, status=ExportJobStatus.running, updated_at=stale
    )

    await export_worker.process_export_jobs()

    assert await _status(client, a, job_id) == ExportJobStatus.done.value
    assert await _ready_notices(session, a, job_id) == 1


async def test_the_sweep_leaves_a_render_this_process_is_running(
    client: AsyncClient, acting_user, session, monkeypatch
):
    a = await _actor(acting_user, session)
    job_id = await _queued(client, a)
    stale = datetime.now(timezone.utc) - timedelta(minutes=30)
    await _set_row(
        session, a.guild.id, job_id, status=ExportJobStatus.running, updated_at=stale
    )

    alive = asyncio.create_task(asyncio.sleep(3600))
    monkeypatch.setitem(export_worker._running, (a.guild.id, job_id), ("render", alive))
    try:
        started = await export_worker.dispatch_export_jobs()
    finally:
        alive.cancel()

    assert started == []
    assert await _status(client, a, job_id) == ExportJobStatus.running.value


async def test_a_render_that_lost_its_row_writes_nothing(
    client: AsyncClient, acting_user, session, monkeypatch
):
    """A render whose row was queued again while it ran stops without
    recording an outcome; the next claim renders it, and the creator is told
    once."""
    a = await _actor(acting_user, session)
    job_id = await _queued(client, a)
    real_execute = export_worker._execute
    calls = {"n": 0}

    async def execute(bookkeeping, job, *, guild_id, heartbeat):
        calls["n"] += 1
        if calls["n"] == 1:
            await _set_row(
                session,
                guild_id,
                job.id,
                status=ExportJobStatus.queued,
                updated_at=datetime.now(timezone.utc),
            )
            return export_engine.ArtifactLocation(artifact_ref="exports/lost.pdf")
        return await real_execute(
            bookkeeping, job, guild_id=guild_id, heartbeat=heartbeat
        )

    monkeypatch.setattr(export_worker, "_execute", execute)

    await export_worker.process_export_jobs()

    assert calls["n"] == 2
    session.expunge_all()
    await route_session_to_guild(session, a.guild.id)
    job = await session.get(ExportJob, job_id)
    assert job.status == ExportJobStatus.done.value
    assert job.artifact_ref != "exports/lost.pdf"
    assert await _ready_notices(session, a, job_id) == 1


@pytest.mark.parametrize(
    "status",
    [
        GuildStatus.read_only,
        GuildStatus.suspended,
        GuildStatus.on_hold,
        GuildStatus.deleted,
    ],
)
async def test_gc_reaches_a_community_that_is_not_active(acting_user, session, status):
    """Expired artifacts go from every community whose schema exists, not
    only the active ones."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    storage = get_guild_storage(a.guild.id)
    key = "exports/515151.pdf"
    storage.write(key, b"%PDF-fake", content_type="application/pdf")
    await route_session_to_guild(session, a.guild.id)
    job = ExportJob(
        created_by=a.user.id,
        source="tasks",
        template_id="task-table",
        format="pdf",
        status=ExportJobStatus.done,
        artifact_ref=key,
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    session.add(job)
    await session.commit()
    job_id = job.id
    guild = await session.get(Guild, a.guild.id)
    guild.status = status.value
    guild.status_changed_at = datetime.now(timezone.utc)
    session.add(guild)
    await session.commit()

    await export_worker.process_export_gc()

    assert storage.open_readable(key) is None
    session.expunge_all()
    await route_session_to_guild(session, a.guild.id)
    refreshed = await session.get(ExportJob, job_id)
    assert refreshed.status == ExportJobStatus.expired.value
    assert refreshed.artifact_ref is None
