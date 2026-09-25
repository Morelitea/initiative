"""The import worker's own housekeeping: expiry in every community whose
schema exists, secrets cleared from jobs that are over, and the apply's
session drawn from the community's cohort."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.db import cohorts
from app.db.session import set_rls_context
from app.models.platform.guild import Guild, GuildRole, GuildStatus
from app.models.tenant.import_job import ImportJob, ImportJobStatus
from app.services.import_engine import worker as import_worker
from app.services.storage import get_guild_storage
from app.testing import route_session_to_guild
from app.testing.factories import create_guild

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _tmp_uploads(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "UPLOADS_DIR", str(tmp_path))


async def _job(session, a, **fields) -> int:
    await route_session_to_guild(session, a.guild.id)
    job = ImportJob(
        created_by=a.user.id,
        source="backup",
        params={"initiative_id": a.initiative.id},
        **fields,
    )
    session.add(job)
    await session.commit()
    assert job.id is not None
    return job.id


async def _reload(session, guild_id: int, job_id: int) -> ImportJob:
    session.expunge_all()
    await route_session_to_guild(session, guild_id)
    job = await session.get(ImportJob, job_id)
    assert job is not None
    return job


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
    """A staged payload past its deadline goes, with the job's secret, from
    every community whose schema exists, not only the active ones."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    storage = get_guild_storage(a.guild.id)
    key = "imports/gc-elsewhere.zip"
    storage.write(key, b"PK-fake", content_type="application/zip")
    job_id = await _job(
        session,
        a,
        status=ImportJobStatus.staged,
        payload_ref=key,
        secret_encrypted="sealed",
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    guild = await session.get(Guild, a.guild.id)
    assert guild is not None
    guild.status = status.value
    guild.status_changed_at = datetime.now(timezone.utc)
    session.add(guild)
    await session.commit()

    await import_worker.process_import_gc()

    assert storage.open_readable(key) is None
    job = await _reload(session, a.guild.id, job_id)
    assert job.status == ImportJobStatus.expired.value
    assert job.payload_ref is None
    assert job.secret_encrypted is None


@pytest.mark.parametrize(
    "status",
    [
        ImportJobStatus.done,
        ImportJobStatus.failed,
        ImportJobStatus.cancelled,
        ImportJobStatus.expired,
    ],
)
async def test_gc_clears_a_secret_left_on_a_job_that_is_over(
    acting_user, session, status
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    job_id = await _job(session, a, status=status, secret_encrypted="sealed")

    await import_worker.process_import_gc()

    job = await _reload(session, a.guild.id, job_id)
    assert job.status == status.value
    assert job.secret_encrypted is None


async def test_gc_leaves_a_live_jobs_secret(acting_user, session):
    """A queued job that has not reached its deadline still needs its
    secret to start."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    job_id = await _job(
        session,
        a,
        status=ImportJobStatus.queued,
        secret_encrypted="sealed",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )

    await import_worker.process_import_gc()

    job = await _reload(session, a.guild.id, job_id)
    assert job.status == ImportJobStatus.queued.value
    assert job.secret_encrypted == "sealed"


async def test_the_apply_session_comes_from_the_communitys_cohort(session):
    """Each community's apply runs on a session from its own cohort's pool,
    which routes into it."""
    guilds = [await create_guild(session) for _ in range(3)]
    covered = {cohorts.cohort_of(g.id) for g in guilds}
    assert len(covered) > 1

    for guild in guilds:
        assert guild.id is not None
        maker = cohorts.request_sessionmaker(guild.id)
        async with import_worker._open_user_session(guild.id) as user_session:
            assert user_session.bind is maker.kw["bind"]
            await set_rls_context(user_session, guild_id=guild.id)
            assert (await user_session.exec(text("SELECT 1"))).scalar_one() == 1
