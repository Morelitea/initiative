"""Pitches, links and copies: opening a link, the pool, expiry and cleanup."""

import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import func
from sqlmodel import select

from app.core.config import settings
from app.core.messages import DemoMessages, GuildMessages
from app.db import cohorts
from app.demo import accounts, copies, pitches
from app.models.platform.auth_session import AuthSession
from app.models.platform.demo import (
    DemoAccount,
    DemoLink,
    DemoSandbox,
    DemoSandboxState,
)
from app.models.platform.guild import CommunityRole, Guild, GuildMembership
from app.models.platform.user import User
from app.models.tenant.export_job import ExportJob, ExportJobStatus
from app.models.tenant.import_job import ImportJob, ImportJobStatus
from app.models.tenant.initiative import Initiative, InitiativeMember
from app.models.tenant.task import Task
from app.services.export import worker as export_worker
from app.services.guild_sweeps import Scope, each_guild
from app.services.import_engine import engine as import_engine
from app.services.import_engine import worker as import_worker
from app.services.platform import users as users_service
from app.testing import (
    create_export_job,
    create_guild,
    create_guild_membership,
    create_initiative_member,
    create_task,
    create_user,
    route_session_to_guild,
)

REDEEM = "/api/v1/demo/redeem"


@pytest.fixture
async def pitch(client, acting_user, session, monkeypatch):
    """A pitch with a task assigned to a persona, published, and a way to make
    links to it."""
    monkeypatch.setattr(settings, "DEMO_MODE", True)
    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )
    bea = await accounts.create(session, handle="bea#0042")
    await create_guild_membership(session, user=bea, guild=a.guild)
    await create_initiative_member(session, a.initiative, bea)
    await create_task(session, a.project, title="Proof the dough", assignees=[bea])
    queued = await client.get(a.g("/exports/community"), headers=a.headers)
    assert queued.status_code == 202, queued.text
    await export_worker.process_export_jobs()

    host = await accounts.demo_host(session)
    a.guild.created_by = host.id
    session.add(a.guild)
    await session.commit()

    async def link(role: CommunityRole = CommunityRole.admin) -> str:
        _link, token = await pitches.make_link(session, pitch_id=a.guild.id, role=role)
        await session.commit()
        return token

    return link, bea.id, a.guild.id


async def _open(client, token: str) -> tuple[dict, dict, dict]:
    """Open the link; the answer, the visitor's headers and their account."""
    response = await client.post(REDEEM, json={"token": token})
    assert response.status_code == 200, response.text
    opened = response.json()
    headers = {"Authorization": f"Bearer {opened['access_token']}"}
    me = await client.get("/api/v1/me", headers=headers)
    return opened, headers, me.json()


async def _roster(session, guild_id: int) -> dict[int, CommunityRole]:
    return {
        m.user_id: m.role
        for m in await session.exec(
            select(GuildMembership).where(GuildMembership.guild_id == guild_id)
        )
    }


async def test_two_openings_make_two_copies_apart(pitch, client, session):
    link, bea, _source = pitch
    token = await link()
    pooled = {await copies.build_copy(), await copies.build_copy()}

    first, first_headers, first_me = await _open(client, token)
    second, second_headers, second_me = await _open(client, token)

    assert {first["community_id"], second["community_id"]} == pooled
    assert first_me["id"] != second_me["id"]
    expires_at = datetime.fromisoformat(first_me["demo_expires_at"])
    signed_in = (
        await session.exec(
            select(AuthSession).where(AuthSession.user_id == first_me["id"])
        )
    ).one()
    assert signed_in.chain_expires_at <= expires_at
    assert first_me["can_create_communities"] is False
    for opened in (first, second):
        assert bea in await _roster(session, opened["community_id"])
    other = await client.get(
        f"/api/v1/c/{second['community_id']}/initiatives/", headers=first_headers
    )
    assert other.status_code == 403
    created = await client.post(
        "/api/v1/communities/", json={"name": "Mine"}, headers=second_headers
    )
    assert created.status_code == 403
    assert created.json()["detail"] == GuildMessages.COMMUNITY_CREATION_DEMO_ACCOUNT


@pytest.mark.parametrize(
    "role", [CommunityRole.member, CommunityRole.admin, CommunityRole.superadmin]
)
async def test_a_link_seats_the_visitor_in_its_role(pitch, client, session, role):
    link, _bea, _source = pitch
    token = await link(role)
    copy_id = await copies.build_copy()
    opened, headers, me = await _open(client, token)
    await import_worker.process_import_jobs()

    host = await accounts.demo_host(session)
    roster = await _roster(session, copy_id)
    assert roster[me["id"]] is role
    if role is CommunityRole.superadmin:
        assert host.id not in roster
    else:
        assert roster[host.id] is CommunityRole.superadmin

    await route_session_to_guild(session, copy_id)
    job = await session.get(ImportJob, opened["import_job_id"])
    assert job is not None and job.status == ImportJobStatus.done, job
    assert (await session.exec(select(Task.title))).all() == ["Proof the dough"]
    initiatives = set((await session.exec(select(Initiative.id))).all())
    joined = set(
        (
            await session.exec(
                select(InitiativeMember.initiative_id).where(
                    InitiativeMember.user_id == me["id"]
                )
            )
        ).all()
    )
    assert initiatives and joined == initiatives
    tasks = await client.get(f"/api/v1/c/{copy_id}/tasks/", headers=headers)
    assert tasks.status_code == 200, tasks.text
    assert [t["title"] for t in tasks.json()["items"]] == ["Proof the dough"]


async def test_an_expired_copy_leaves_no_community_and_no_account(
    pitch, client, session, monkeypatch
):
    """A pass whose account deletion fails leaves the copy recorded, and the
    next pass finishes it, its seat holder included."""
    link, _bea, _source = pitch
    copy_id = await copies.build_copy()
    _opened, _headers, me = await _open(client, await link(CommunityRole.superadmin))
    later = datetime.now(timezone.utc) + copies.COPY_LIFETIME + timedelta(minutes=1)

    async def fails(*_args, **_kwargs) -> None:
        raise RuntimeError("account deletion failed")

    with monkeypatch.context() as patched:
        patched.setattr(users_service, "hard_delete_user", fails)
        await copies.expire_copies(later)
    session.expire_all()
    assert await session.get(DemoSandbox, copy_id) is not None
    assert await session.get(DemoAccount, me["id"]) is not None

    await copies.expire_copies(later)
    session.expire_all()
    assert await session.get(Guild, copy_id) is None
    assert await session.get(User, me["id"]) is None


async def test_a_failed_opening_spends_nothing(pitch, session, monkeypatch):
    """Staging the archive fails: the copy stays pooled, the link unspent and
    no account is left."""
    link, _bea, _source = pitch
    token = await link()
    copy_id = await copies.build_copy()
    users = (await session.exec(select(func.count()).select_from(User))).one()

    def fails(*_args, **_kwargs) -> str:
        raise OSError("storage unavailable")

    monkeypatch.setattr(import_engine, "stage_payload_file", fails)
    async with cohorts.system_session(None) as system:
        with pytest.raises(OSError):
            await copies.redeem(system, token)

    session.expire_all()
    sandbox = await session.get(DemoSandbox, copy_id)
    assert sandbox is not None and sandbox.state == DemoSandboxState.pooled
    assert sandbox.import_job_id is None
    assert (await session.exec(select(DemoLink.redemption_count))).one() == 0
    assert (await session.exec(select(DemoAccount))).all() == []
    assert (await session.exec(select(func.count()).select_from(User))).one() == users


async def test_a_link_that_ends_while_opening_opens_nothing(
    pitch, client, session, monkeypatch
):
    """The link is checked again by the clock as it reads once locked."""
    _link, _bea, source = pitch
    row, token = await pitches.make_link(session, pitch_id=source)
    ends = datetime.now(timezone.utc) + timedelta(hours=1)
    row.expires_at = ends
    session.add(row)
    await session.commit()
    await copies.build_copy()
    readings = iter([ends - timedelta(seconds=1), ends + timedelta(seconds=1)])
    monkeypatch.setattr(
        copies, "datetime", SimpleNamespace(now=lambda tz: next(readings))
    )

    response = await client.post(REDEEM, json={"token": token})
    assert response.status_code == 404
    assert response.json()["detail"] == DemoMessages.DEMO_LINK_NOT_FOUND


async def test_the_export_gc_keeps_what_a_pitch_publishes(pitch, client, session):
    """Past their expiry, a pitch's newest backup stays and its links still
    open; its older backup and another community's export go."""
    link, _bea, source = pitch
    token = await link()
    host = await accounts.demo_host(session)
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    backup = {
        "source": "community",
        "format": "zip",
        "params": {"mode": "backup"},
        "status": ExportJobStatus.done,
        "expires_at": past,
    }
    other_guild = await create_guild(session)
    other_id = other_guild.id
    superseded = (
        await create_export_job(
            session,
            await session.get(Guild, source),
            host,
            artifact_ref="exports/superseded.zip",
            created_at=past - timedelta(days=8),
            **backup,
        )
    ).id
    other = (
        await create_export_job(
            session, other_guild, host, artifact_ref="exports/other.zip", **backup
        )
    ).id
    await route_session_to_guild(session, source)
    published = (
        await session.exec(select(ExportJob).where(ExportJob.id != superseded))
    ).one()
    published.expires_at = past
    session.add(published)
    await session.commit()
    published_id = published.id

    await each_guild([(Scope.PROVISIONED, export_worker.expire_artifacts)], name="t")

    statuses = {}
    for guild_id, job_id in (
        (source, published_id),
        (source, superseded),
        (other_id, other),
    ):
        session.expunge_all()
        await route_session_to_guild(session, guild_id)
        job = await session.get(ExportJob, job_id)
        assert job is not None
        statuses[job_id] = job.status
    assert statuses == {
        published_id: ExportJobStatus.done,
        superseded: ExportJobStatus.expired,
        other: ExportJobStatus.expired,
    }
    await copies.build_copy()
    await _open(client, token)


async def test_busy_when_the_pool_is_empty(pitch, client):
    link, _bea, _source = pitch
    response = await client.post(REDEEM, json={"token": await link()})
    assert response.status_code == 503
    assert response.json()["detail"] == DemoMessages.DEMO_BUSY


async def test_links_open_nothing_outside_demo_mode(client):
    response = await client.post(REDEEM, json={"token": "anything"})
    assert response.status_code == 404


async def test_making_a_pitch_imports_and_publishes(pitch, session):
    """A pitch made from a bundle: another pitch's published export."""
    _link, bea, source = pitch
    editor = await create_user(session, username="rev", discriminator=1000)
    await session.commit()
    artifact = await pitches.newest_export(source)
    assert artifact is not None
    async with import_engine.open_payload(source, artifact) as bundle:
        assert bundle is not None
        pitch_id = await pitches.make_pitch(
            bundle=bundle, name="Rosie's", editors=["rev#1000"]
        )
    await export_worker.process_export_jobs()

    made = await session.get(Guild, pitch_id)
    assert made is not None and made.name == "Rosie's"
    roster = await _roster(session, pitch_id)
    assert roster[(await accounts.demo_host(session)).id] is CommunityRole.superadmin
    assert roster[editor.id] is CommunityRole.admin
    assert bea in roster
    assert await pitches.newest_export(pitch_id) is not None
    await route_session_to_guild(session, pitch_id)
    assert (await session.exec(select(Task.title))).all() == ["Proof the dough"]


async def test_cleanup_removes_an_idle_pitch_a_stale_link_and_leftovers(session):
    host = await accounts.demo_host(session)
    now = datetime.now(timezone.utc)
    old = now - copies.CLEANUP_AFTER - timedelta(days=10)
    idle = await create_guild(session, creator=host, created_at=old)
    kept = await create_guild(session, creator=host, created_at=old)
    seeded = await create_guild(session, creator=host, created_at=old)
    links = {}
    for name, guild in (("idle", idle), ("live", kept), ("stale", kept)):
        links[name], _token = await pitches.make_link(session, pitch_id=guild.id)
    links["idle"].revoked_at = old
    links["stale"].expires_at = old
    session.add_all(links.values())
    leftover = await create_user(session)
    member = await create_user(session)
    await create_guild_membership(session, user=member, guild=kept)
    persona = await accounts.create(session, handle="ned#0007")
    await session.commit()
    ids = {name: link.id for name, link in links.items()}
    idle_id, kept_id, seeded_id = idle.id, kept.id, seeded.id
    leftover_id, member_id, persona_id = leftover.id, member.id, persona.id
    host_id = host.id

    await copies.clean_up()

    session.expire_all()
    assert await session.get(Guild, idle_id) is None
    assert await session.get(Guild, kept_id) is not None
    assert await session.get(Guild, seeded_id) is not None
    remaining = set((await session.exec(select(DemoLink.id))).all())
    assert remaining == {ids["live"]}
    assert await session.get(User, leftover_id) is None
    for user_id in (member_id, persona_id, host_id):
        assert await session.get(User, user_id) is not None


async def test_the_pool_loop_cleans_up_once_a_day(monkeypatch):
    runs = []

    async def clean_up() -> None:
        runs.append(True)

    monkeypatch.setattr(copies, "clean_up", clean_up)
    monkeypatch.setattr(copies, "POOL_SIZE", 0)
    monkeypatch.setattr(copies, "_cleaned_at", None)

    await copies.pool_pass()
    await copies.pool_pass()
    assert len(runs) == 1

    a_day_ago = time.monotonic() - copies.CLEANUP_EVERY_SECONDS
    monkeypatch.setattr(copies, "_cleaned_at", a_day_ago)
    await copies.pool_pass()
    assert len(runs) == 2
