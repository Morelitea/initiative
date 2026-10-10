"""The demo loader, with a bundle exported from a factory-made community."""

import asyncio
import io
import json
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlmodel import select

from app.core.config import settings
from app.core.moderation import HoldReason, HoldVia
from app.core.security import verify_password
from app.services.import_engine.engine import read_payload
from app.demo import loader, shapes
from app.demo.loader import DemoModeRequired, load
from app.models.platform.guild import CommunityRole, Guild, GuildMembership
from app.models.platform.user import User
from app.models.tenant.content_hold import ContentHold
from app.models.tenant.export_job import ExportJobStatus
from app.models.tenant.initiative import Initiative, InitiativeJoinPolicy
from app.models.tenant.task import Task
from app.services.auth import addresses
from app.services.export import worker as export_worker
from app.services.import_engine import backup as backup_service
from app.services.import_engine import engine as import_engine
from app.services.import_engine import worker as import_worker
from app.services.platform.app_settings import get_app_settings
from app.services.platform.notification_prefs import load_prefs
from app.testing import create_import_job, create_task, route_session_to_guild

DUE_IN = timedelta(days=2)
#: How long before the load the bundle claims it was exported.
EXPORTED_AGO = timedelta(days=30)
PASSWORD = "a long demo password"


@pytest.fixture
async def demo(client, acting_user, session, tmp_path, monkeypatch):
    """A community exported as a bundle dated ``EXPORTED_AGO``, a manifest
    seeding two communities from it, and the secret file beside it."""
    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )
    due = datetime.now(timezone.utc).replace(microsecond=0) + DUE_IN
    await create_task(session, a.project, title="Proof the dough", due_date=due)

    queued = await client.get(a.g("/exports/community"), headers=a.headers)
    assert queued.status_code == 202, queued.text
    await export_worker.process_export_jobs()
    job_id = queued.json()["id"]
    job = await client.get(a.g(f"/exports/jobs/{job_id}"), headers=a.headers)
    assert job.json()["status"] == ExportJobStatus.done.value
    download = await client.get(
        a.g(f"/exports/jobs/{job_id}/download"), headers=a.headers
    )
    _write_backdated(download.content, tmp_path / "bakery.zip")

    row = await get_app_settings(session)
    row.operations_guild_id = a.guild.id
    session.add(row)
    await session.commit()

    manifest = {
        "personas": [
            {"handle": "bea#0042", "display_name": "Bea", "avatar_seed": "bea"},
            {"handle": "ned#0007", "display_name": "Ned"},
            {"handle": "ada#0001", "display_name": "Ada"},
        ],
        "shapes": [{"key": "bakery", "label": "Bakery", "bundle": "bakery.zip"}],
        "communities": [
            {
                "name": "Rosie's Bakery",
                "creator": "bea#0042",
                "members": ["ned#0007"],
                "bundle": "bakery.zip",
                "directory": {"categories": ["business"], "join_policy": "request"},
            }
        ],
        "fixed_communities": {
            "review": {
                "name": "Review Bakery",
                "creator": "ada#0001",
                "bundle": "bakery.zip",
                "keep": True,
            }
        },
        "accounts": [
            {
                "handle": "reviewer#1000",
                "communities": {"review": "admin"},
                "pitch_editor": True,
            }
        ],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "accounts.json").write_text(
        json.dumps(
            {"reviewer#1000": {"address": "review@example.com", "password": PASSWORD}}
        )
    )
    monkeypatch.setattr(settings, "DEMO_MODE", True)
    return a, due, tmp_path


def _write_backdated(data: bytes, path: Path) -> None:
    """The archive with its manifest's export moved back by ``EXPORTED_AGO``."""
    with zipfile.ZipFile(io.BytesIO(data)) as source:
        with zipfile.ZipFile(path, "w") as target:
            for name in source.namelist():
                body = source.read(name)
                if name == "manifest.json":
                    manifest = json.loads(body)
                    exported = datetime.fromisoformat(manifest["exported_at"])
                    manifest["exported_at"] = (exported - EXPORTED_AGO).isoformat()
                    body = json.dumps(manifest).encode()
                target.writestr(name, body)


async def _load(directory: Path, *, rebuild: bool = False) -> None:
    await load(
        directory / "manifest.json", directory / "accounts.json", rebuild=rebuild
    )


async def _user(session, username: str) -> User:
    return (await session.exec(select(User).where(User.username == username))).one()


async def _created_by(session, user_id: int) -> list[Guild]:
    return list(await session.exec(select(Guild).where(Guild.created_by == user_id)))


async def _due_dates(session, guild_id: int) -> list[datetime]:
    await route_session_to_guild(session, guild_id)
    return [
        task.due_date
        for task in await session.exec(
            select(Task).where(Task.title == "Proof the dough")
        )
    ]


async def test_loading_twice_seeds_once(demo, session):
    a, due, directory = demo
    await _load(directory)
    await _load(directory)

    bea, ned = await _user(session, "bea"), await _user(session, "ned")
    for persona in (bea, ned):
        assert persona.hashed_password is None
        assert await addresses.list_for_user(session, user_id=persona.id) == []
        prefs = await load_prefs(session, persona.id)
        assert not any(
            value
            for channels in prefs["categories"].values()
            for value in channels.values()
        )
    assert bea.avatar_url is not None

    (bakery,) = await _created_by(session, bea.id)
    assert bakery.is_community and bakery.categories == ["business"]
    roster = {
        m.user_id: m
        for m in await session.exec(
            select(GuildMembership).where(GuildMembership.guild_id == bakery.id)
        )
    }
    assert roster[bea.id].role is CommunityRole.superadmin
    assert roster[ned.id].display_name == "Ned"
    # Due two days after the export, so two days from now.
    assert [d.date() for d in await _due_dates(session, bakery.id)] == [
        (due + EXPORTED_AGO).date()
    ]

    reviewer = await _user(session, "reviewer")
    assert verify_password(PASSWORD, reviewer.hashed_password)
    (review,) = await _created_by(session, (await _user(session, "ada")).id)
    seat = await session.get(GuildMembership, (review.id, reviewer.id))
    assert seat is not None and seat.role is CommunityRole.admin

    library = shapes.read_library(a.guild.id)
    assert library is not None
    assert [s.key for s in library.shapes] == ["bakery"]
    assert library.editors == ["reviewer#1000"]
    assert import_engine.read_payload(a.guild.id, shapes.bundle_key("bakery"))


async def test_rebuild_remakes_what_is_not_kept(demo, session):
    _a, _due, directory = demo
    await _load(directory)
    bea, ada = (await _user(session, "bea")).id, (await _user(session, "ada")).id
    (bakery,) = await _created_by(session, bea)
    (review,) = await _created_by(session, ada)
    bakery_id, review_id = bakery.id, review.id

    await _load(directory, rebuild=True)

    session.expire_all()
    (remade,) = await _created_by(session, bea)
    assert remade.id != bakery_id
    assert await session.get(Guild, bakery_id) is None
    (kept,) = await _created_by(session, ada)
    assert kept.id == review_id


async def test_a_rebuild_leaves_a_held_community_alone(demo, session):
    _a, _due, directory = demo
    await _load(directory)
    bea = (await _user(session, "bea")).id
    (bakery,) = await _created_by(session, bea)
    bakery_id = bakery.id
    await route_session_to_guild(session, bakery_id)
    session.add(
        ContentHold(
            target_type="task",
            target_id=1,
            placed_via=HoldVia.community.value,
            reason=HoldReason.legal_request.value,
        )
    )
    await session.commit()

    await _load(directory, rebuild=True)

    session.expire_all()
    (kept,) = await _created_by(session, bea)
    assert kept.id == bakery_id


async def test_a_seed_that_left_entries_out_fails_and_is_made_again(
    demo, session, monkeypatch
):
    _a, due, directory = demo

    def refuse(*_args):
        raise ValueError("refused")

    with monkeypatch.context() as patch:
        patch.setattr(backup_service, "shift_dates", refuse)
        with pytest.raises(RuntimeError, match="left out"):
            await _load(directory)
    bea = (await _user(session, "bea")).id
    (partial,) = await _created_by(session, bea)
    partial_id = partial.id

    await _load(directory)

    session.expire_all()
    (bakery,) = await _created_by(session, bea)
    assert bakery.id != partial_id
    assert [d.date() for d in await _due_dates(session, bakery.id)] == [
        (due + EXPORTED_AGO).date()
    ]


async def test_an_import_another_worker_claims_is_waited_for(
    demo, session, monkeypatch
):
    _a, due, directory = demo
    claim = import_worker.jobs.claim
    elsewhere: dict[int, asyncio.Task | None] = {}

    async def claimed_elsewhere(session, guild_id):
        if guild_id not in elsewhere:
            elsewhere[guild_id] = await claim(session, guild_id)
        return None

    monkeypatch.setattr(import_worker.jobs, "claim", claimed_elsewhere)
    monkeypatch.setattr(loader, "IMPORT_POLL_SECONDS", 0.05)
    await _load(directory)

    assert len(elsewhere) == 2
    (bakery,) = await _created_by(session, (await _user(session, "bea")).id)
    assert [d.date() for d in await _due_dates(session, bakery.id)] == [
        (due + EXPORTED_AGO).date()
    ]


async def test_changes_to_the_manifest_apply_on_reload(demo, session):
    a, _due, directory = demo
    operations = a.guild.id
    await _load(directory)
    (bakery,) = await _created_by(session, (await _user(session, "bea")).id)
    bakery_id = bakery.id

    async def join_policies() -> set[str]:
        await route_session_to_guild(session, bakery_id)
        return {i.join_policy for i in await session.exec(select(Initiative))}

    assert await join_policies() == {InitiativeJoinPolicy.request}

    path = directory / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["communities"][0]["directory"]["join_policy"] = "open"
    manifest["shapes"] = []
    path.write_text(json.dumps(manifest))
    (directory / "accounts.json").write_text(
        json.dumps(
            {"reviewer#1000": {"address": "moved@example.com", "password": PASSWORD}}
        )
    )
    await _load(directory)

    session.expire_all()
    assert await join_policies() == {InitiativeJoinPolicy.open}
    reviewer = (await _user(session, "reviewer")).id
    assert await addresses.holds_address(
        session, user_id=reviewer, email="moved@example.com"
    )
    assert not await addresses.holds_address(
        session, user_id=reviewer, email="review@example.com"
    )
    library = shapes.read_library(operations)
    assert library is not None and library.shapes == []
    assert read_payload(operations, shapes.bundle_key("bakery")) is None

    manifest["communities"][0]["directory"] = None
    path.write_text(json.dumps(manifest))
    await _load(directory)

    session.expire_all()
    guild = await session.get(Guild, bakery_id)
    assert guild is not None and not guild.is_community


async def test_the_loader_refuses_outside_demo_mode(tmp_path):
    with pytest.raises(DemoModeRequired):
        await _load(tmp_path)


async def test_an_import_with_no_anchor_keeps_its_dates(demo, session):
    a, due, directory = demo
    payload_ref = import_engine.stage_payload_file(
        a.guild.id, directory / "bakery.zip", suffix="zip"
    )
    await create_import_job(session, a.guild, a.user, payload_ref=payload_ref)
    await import_worker.process_import_jobs()

    assert await _due_dates(session, a.guild.id) == [due, due]
