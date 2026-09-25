"""The export worker's own rules on the shared dispatcher: an abandoned render
is queued again and finishes once, and a render that lost its row writes
nothing. Claiming and slots are tested once, through imports; expiry in
``exports_test``."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select

from app.core.config import settings
from app.models.platform.guild import GuildRole
from app.models.platform.notification import Notification, NotificationType
from app.models.tenant.export_job import ExportJob, ExportJobStatus
from app.services.export import engine as export_engine
from app.services.export import worker as export_worker
from app.testing import create_export_job, create_task, route_session_to_guild

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _tmp_uploads(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "UPLOADS_DIR", str(tmp_path))


async def _actor(acting_user, session):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    await create_task(session, a.project, title="Task")
    return a


async def _reload(session, guild_id: int, job_id: int) -> ExportJob:
    session.expunge_all()
    await route_session_to_guild(session, guild_id)
    job = await session.get(ExportJob, job_id)
    assert job is not None
    return job


async def _ready_notices(session, user_id: int, job_id: int) -> int:
    rows = await session.exec(
        select(Notification).where(Notification.user_id == user_id)
    )
    return sum(
        1
        for n in rows
        if n.type == NotificationType.export_ready
        and n.data.get("export_job_id") == job_id
    )


async def test_an_abandoned_render_is_queued_again_and_finishes_once(
    acting_user, session
):
    """A ``running`` row nobody has touched for the stale window is rendered
    again from the start, and its creator hears about it once."""
    a = await _actor(acting_user, session)
    job = await create_export_job(
        session,
        a.guild,
        a.user,
        status=ExportJobStatus.running,
        updated_at=datetime.now(timezone.utc) - timedelta(minutes=30),
    )

    await export_worker.process_export_jobs()

    assert (await _reload(session, a.guild.id, job.id)).status == "done"
    assert await _ready_notices(session, a.user.id, job.id) == 1


async def test_a_render_that_lost_its_row_writes_nothing(
    acting_user, session, monkeypatch
):
    """A render whose row was queued again while it ran stops without
    recording an outcome; the next claim renders it, and the creator is told
    once."""
    a = await _actor(acting_user, session)
    job = await create_export_job(session, a.guild, a.user)
    real_execute = export_worker._execute
    calls = 0

    async def execute(bookkeeping, running, *, guild_id, heartbeat):
        nonlocal calls
        calls += 1
        if calls == 1:
            row = await _reload(session, guild_id, running.id)
            row.status = ExportJobStatus.queued
            row.updated_at = datetime.now(timezone.utc)
            session.add(row)
            await session.commit()
            return export_engine.ArtifactLocation(artifact_ref="exports/lost.pdf")
        return await real_execute(
            bookkeeping, running, guild_id=guild_id, heartbeat=heartbeat
        )

    monkeypatch.setattr(export_worker, "_execute", execute)

    await export_worker.process_export_jobs()

    assert calls == 2
    done = await _reload(session, a.guild.id, job.id)
    assert done.status == "done"
    assert done.artifact_ref != "exports/lost.pdf"
    assert await _ready_notices(session, a.user.id, job.id) == 1
