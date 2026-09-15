"""The owner's intake settings, and who can read what lands through them."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlmodel import select

from app.core.intake import IntakeStream
from app.db.session import set_rls_context
from app.models.platform.app_setting import AppSetting
from app.models.platform.user import User
from app.models.tenant.initiative import Initiative
from app.models.tenant.project import Project
from app.models.tenant.task import Task
from app.services.platform import intake as intake_service
from app.testing import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_project,
    create_user,
    get_auth_headers,
)
from app.models.platform.guild import GuildRole

pytestmark = pytest.mark.integration


@pytest.fixture
async def owner(session, acting_user):
    """A platform owner, and a guild they can point operations at.

    Ids rather than ORM rows: these endpoints run on the system session, which
    in tests IS this session, and routing it into a guild schema expunges the
    identity map. A detached row refreshed afterwards would read against the
    wrong search_path.
    """
    actor = await acting_user("owner")
    guild_owner = await create_user(session)
    guild = await create_guild(session, creator=guild_owner)
    initiative = await create_initiative(session, guild, guild_owner)
    ids = {
        "actor": actor,
        "guild_id": guild.id,
        "initiative_id": initiative.id,
        "guild_owner_id": guild_owner.id,
    }
    await set_rls_context(session)
    return ids


async def test_every_stream_is_listed_before_anything_is_configured(client, owner):
    response = await client.get(
        "/api/v1/settings/intake", headers=owner["actor"].headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["operations_guild_id"] is None
    assert {b["stream"] for b in body["bindings"]} == {s.value for s in IntakeStream}
    assert all(b["enabled"] is False for b in body["bindings"])


async def test_a_member_cannot_read_or_change_the_settings(client, acting_user):
    """Not an owner, so not deployment configuration they may touch."""
    actor = await acting_user("member")
    assert (
        await client.get("/api/v1/settings/intake", headers=actor.headers)
    ).status_code == 403
    assert (
        await client.put(
            "/api/v1/settings/intake/guild",
            json={"guild_id": 1},
            headers=actor.headers,
        )
    ).status_code == 403


async def test_pointing_at_a_guild_that_does_not_exist_is_refused(client, owner):
    response = await client.put(
        "/api/v1/settings/intake/guild",
        json={"guild_id": 99_999},
        headers=owner["actor"].headers,
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "INTAKE_GUILD_NOT_FOUND"


async def test_binding_before_a_guild_is_named_is_refused(client, owner):
    response = await client.put(
        "/api/v1/settings/intake/support",
        json={"project_id": 1},
        headers=owner["actor"].headers,
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "INTAKE_NO_OPERATIONS_GUILD"


async def test_an_unknown_stream_is_not_a_stream(client, owner):
    response = await client.put(
        "/api/v1/settings/intake/rumours",
        json={"project_id": 1},
        headers=owner["actor"].headers,
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "INTAKE_UNKNOWN_STREAM"


async def test_setting_a_stream_up_from_its_blueprint(client, session, owner):
    await client.put(
        "/api/v1/settings/intake/guild",
        json={"guild_id": owner["guild_id"]},
        headers=owner["actor"].headers,
    )
    response = await client.post(
        "/api/v1/settings/intake/security/blueprint",
        json={"initiative_id": owner["initiative_id"]},
        headers=owner["actor"].headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["stream"] == "security"
    assert body["project_name"] == "Security"
    assert body["enabled"] is True
    assert body["initiative_id"] == owner["initiative_id"]

    # A case filed now lands in what the blueprint produced.
    outcome = await intake_service.open_case(
        IntakeStream.security, title="Refused sign-ins", body="Ten in fifteen minutes."
    )
    assert outcome is not None
    await set_rls_context(session, guild_id=owner["guild_id"], guild_role="admin")
    task = (await session.exec(select(Task).where(Task.id == outcome.task_id))).one()
    assert task.project_id == body["project_id"]


async def test_clearing_the_pointer_stops_every_stream(client, session, owner):
    await client.put(
        "/api/v1/settings/intake/guild",
        json={"guild_id": owner["guild_id"]},
        headers=owner["actor"].headers,
    )
    await client.post(
        "/api/v1/settings/intake/support/blueprint",
        json={"initiative_id": owner["initiative_id"]},
        headers=owner["actor"].headers,
    )
    assert (
        await intake_service.open_case(IntakeStream.support, title="Help") is not None
    )

    response = await client.put(
        "/api/v1/settings/intake/guild",
        json={"guild_id": None},
        headers=owner["actor"].headers,
    )
    assert response.status_code == 200
    assert await intake_service.open_case(IntakeStream.support, title="Help") is None

    # The binding is untouched: pointing back restores what was there.
    await client.put(
        "/api/v1/settings/intake/guild",
        json={"guild_id": owner["guild_id"]},
        headers=owner["actor"].headers,
    )
    assert (
        await intake_service.open_case(IntakeStream.support, title="Help") is not None
    )


async def test_unbinding_keeps_the_project(client, session, owner):
    await client.put(
        "/api/v1/settings/intake/guild",
        json={"guild_id": owner["guild_id"]},
        headers=owner["actor"].headers,
    )
    created = await client.post(
        "/api/v1/settings/intake/feedback/blueprint",
        json={"initiative_id": owner["initiative_id"]},
        headers=owner["actor"].headers,
    )
    project_id = created.json()["project_id"]

    response = await client.delete(
        "/api/v1/settings/intake/feedback", headers=owner["actor"].headers
    )
    assert response.status_code == 204
    assert await intake_service.open_case(IntakeStream.feedback, title="Idea") is None

    await set_rls_context(session, guild_id=owner["guild_id"], guild_role="admin")
    assert (
        await session.exec(select(Project).where(Project.id == project_id))
    ).one_or_none() is not None


async def test_a_guild_member_outside_the_initiative_cannot_read_a_case(
    client, session, owner
):
    """Gate 2, unchanged: the bound project's initiative is who reads its cases."""
    await client.put(
        "/api/v1/settings/intake/guild",
        json={"guild_id": owner["guild_id"]},
        headers=owner["actor"].headers,
    )
    await client.post(
        "/api/v1/settings/intake/security/blueprint",
        json={"initiative_id": owner["initiative_id"]},
        headers=owner["actor"].headers,
    )

    outsider = await create_user(session)
    await create_guild_membership(
        session, user=outsider, guild=owner["guild"], role=GuildRole.member
    )
    await set_rls_context(session)

    outcome = await intake_service.open_case(
        IntakeStream.security, title="Refused sign-ins"
    )
    assert outcome is not None

    response = await client.get(
        f"/api/v1/g/{owner['guild_id']}/tasks/{outcome.task_id}",
        headers=get_auth_headers(outsider),
    )
    assert response.status_code == 404


async def test_a_status_from_another_project_is_refused(client, session, owner):
    await client.put(
        "/api/v1/settings/intake/guild",
        json={"guild_id": owner["guild_id"]},
        headers=owner["actor"].headers,
    )
    created = await client.post(
        "/api/v1/settings/intake/support/blueprint",
        json={"initiative_id": owner["initiative_id"]},
        headers=owner["actor"].headers,
    )
    await set_rls_context(session, guild_id=owner["guild_id"], guild_role="admin")
    from app.models.tenant.task import TaskStatus
    from app.services.tenant import task_statuses as task_statuses_service

    initiative = (
        await session.exec(
            select(Initiative).where(Initiative.id == owner["initiative_id"])
        )
    ).one()
    guild_owner = (
        await session.exec(select(User).where(User.id == owner["guild_owner_id"]))
    ).one()
    elsewhere = await create_project(session, initiative, guild_owner)

    await task_statuses_service.ensure_default_statuses(session, elsewhere.id)
    await session.commit()
    foreign = (
        await session.exec(
            select(TaskStatus).where(TaskStatus.project_id == elsewhere.id)
        )
    ).first()
    await set_rls_context(session)

    response = await client.put(
        "/api/v1/settings/intake/support",
        json={
            "project_id": created.json()["project_id"],
            "default_status_id": foreign.id,
        },
        headers=owner["actor"].headers,
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "INTAKE_STATUS_NOT_IN_PROJECT"


async def test_the_pointer_is_cleared_when_the_guild_goes(client, session, owner):
    """``ON DELETE SET NULL``: nothing is left naming a guild that is gone."""
    await client.put(
        "/api/v1/settings/intake/guild",
        json={"guild_id": owner["guild_id"]},
        headers=owner["actor"].headers,
    )
    await set_rls_context(session)
    await session.exec(
        text("DELETE FROM public.guilds WHERE id = :gid").bindparams(
            gid=owner["guild_id"]
        )
    )
    await session.commit()

    row = (await session.exec(select(AppSetting).where(AppSetting.id == 1))).one()
    assert row.operations_guild_id is None


async def test_repointing_a_stream_starts_fresh_in_the_new_project(
    client, session, owner
):
    """Cases are keyed by project, so a repeat follows the binding."""
    await client.put(
        "/api/v1/settings/intake/guild",
        json={"guild_id": owner["guild_id"]},
        headers=owner["actor"].headers,
    )
    first = await client.post(
        "/api/v1/settings/intake/support/blueprint",
        json={"initiative_id": owner["initiative_id"]},
        headers=owner["actor"].headers,
    )
    opened = await intake_service.open_case(
        IntakeStream.support, title="Refused", dedupe_key="refused:42"
    )
    assert opened is not None

    await set_rls_context(session, guild_id=owner["guild_id"], guild_role="admin")
    initiative = (
        await session.exec(
            select(Initiative).where(Initiative.id == owner["initiative_id"])
        )
    ).one()
    guild_owner = (
        await session.exec(select(User).where(User.id == owner["guild_owner_id"]))
    ).one()
    elsewhere = await create_project(session, initiative, guild_owner)
    elsewhere_id = elsewhere.id
    await set_rls_context(session)

    repointed = await client.put(
        "/api/v1/settings/intake/support",
        json={"project_id": elsewhere_id},
        headers=owner["actor"].headers,
    )
    assert repointed.status_code == 200
    assert repointed.json()["project_id"] == elsewhere_id

    again = await intake_service.open_case(
        IntakeStream.support, title="Refused", dedupe_key="refused:42"
    )
    assert again is not None
    assert again.opened is True
    assert again.task_id != opened.task_id

    await set_rls_context(session, guild_id=owner["guild_id"], guild_role="admin")
    landed = (await session.exec(select(Task).where(Task.id == again.task_id))).one()
    assert landed.project_id == elsewhere_id
    assert first.json()["project_id"] != elsewhere_id


async def test_rebinding_the_same_project_finds_the_open_case(client, session, owner):
    """Unbinding keeps the history, so a repeat does not open a second case."""
    await client.put(
        "/api/v1/settings/intake/guild",
        json={"guild_id": owner["guild_id"]},
        headers=owner["actor"].headers,
    )
    created = await client.post(
        "/api/v1/settings/intake/support/blueprint",
        json={"initiative_id": owner["initiative_id"]},
        headers=owner["actor"].headers,
    )
    project_id = created.json()["project_id"]
    opened = await intake_service.open_case(
        IntakeStream.support, title="Refused", dedupe_key="refused:42"
    )
    assert opened is not None

    await client.delete(
        "/api/v1/settings/intake/support", headers=owner["actor"].headers
    )
    rebound = await client.put(
        "/api/v1/settings/intake/support",
        json={"project_id": project_id},
        headers=owner["actor"].headers,
    )
    assert rebound.status_code == 200

    again = await intake_service.open_case(
        IntakeStream.support, title="Refused", dedupe_key="refused:42"
    )
    assert again is not None
    assert again.opened is False
    assert again.task_id == opened.task_id


async def test_the_last_case_time_ignores_ordinary_tasks(client, owner):
    """A blueprint's seed task is not a case, and must not read as one."""
    await client.put(
        "/api/v1/settings/intake/guild",
        json={"guild_id": owner["guild_id"]},
        headers=owner["actor"].headers,
    )
    created = await client.post(
        "/api/v1/settings/intake/feedback/blueprint",
        json={"initiative_id": owner["initiative_id"]},
        headers=owner["actor"].headers,
    )
    assert created.json()["last_case_at"] is None

    await intake_service.open_case(IntakeStream.feedback, title="An idea")
    listed = await client.get("/api/v1/settings/intake", headers=owner["actor"].headers)
    feedback = next(b for b in listed.json()["bindings"] if b["stream"] == "feedback")
    assert feedback["last_case_at"] is not None
