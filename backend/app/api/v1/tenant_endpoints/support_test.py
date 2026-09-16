"""Asking for help: who may, where it lands, and what happens when nobody is
set up to receive it."""

from __future__ import annotations

import pytest
from sqlmodel import select

from app.core.intake import IntakeStream
from app.core.messages import SupportMessages
from app.db.session import set_rls_context
from app.models.platform.app_setting import AppSetting
from app.models.platform.guild import Guild, GuildRole
from app.models.tenant.intake import IntakeBinding, IntakeCase
from app.models.tenant.task import Task
from app.testing import (
    create_guild,
    create_initiative,
    create_project,
    create_user,
)

pytestmark = pytest.mark.integration


async def _ask(client, actor, guild_id, **body):
    payload = {"subject": "Cannot open a project", "body": "It spins forever."}
    payload.update(body)
    return await client.post(
        f"/api/v1/g/{guild_id}/support", json=payload, headers=actor.headers
    )


async def _set_support(session, guild_id: int, enabled: bool) -> None:
    await set_rls_context(session)
    guild = (await session.exec(select(Guild).where(Guild.id == guild_id))).one()
    guild.support_enabled = enabled
    session.add(guild)
    await session.commit()


@pytest.fixture
async def operations(session):
    """A deployment with somewhere for support cases to go."""
    staff = await create_user(session)
    ops_guild = await create_guild(session, creator=staff)
    ops_initiative = await create_initiative(session, ops_guild, staff)
    ops_project = await create_project(session, ops_initiative, staff)

    await set_rls_context(session)
    row = (await session.exec(select(AppSetting).where(AppSetting.id == 1))).first()
    if row is None:
        row = AppSetting(id=1)
    row.operations_guild_id = ops_guild.id
    session.add(row)
    await session.commit()

    await set_rls_context(session, guild_id=ops_guild.id, guild_role="admin")
    session.add(IntakeBinding(stream=IntakeStream.support, project_id=ops_project.id))
    await session.commit()
    await set_rls_context(session)
    return {"guild": ops_guild, "project": ops_project}


async def test_support_is_off_until_a_community_turns_it_on(client, acting_user):
    """The default. Nothing has to be configured for this to be the answer."""
    member = await acting_user(guild_role=GuildRole.member)
    response = await _ask(client, member, member.guild.id)
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == SupportMessages.NOT_AVAILABLE


async def test_a_member_can_ask_for_help(client, session, acting_user, operations):
    """Every member, not only an admin: the person who needs help is rarely
    the person who administers anything."""
    member = await acting_user(guild_role=GuildRole.member)
    await _set_support(session, member.guild.id, True)

    response = await _ask(
        client, member, member.guild.id, subject="Cannot sign in on my phone"
    )
    assert response.status_code == 202, response.text
    assert response.json()["accepted"] is True

    await set_rls_context(session, guild_id=operations["guild"].id, guild_role="admin")
    case = (await session.exec(select(IntakeCase))).one()
    assert case.stream == IntakeStream.support.value
    task = (await session.exec(select(Task).where(Task.id == case.task_id))).one()
    assert task.title == "Cannot sign in on my phone"
    assert task.project_id == operations["project"].id


async def test_the_case_names_who_asked_and_where_from(
    client, session, acting_user, operations
):
    """So whoever picks it up can reach them without the endpoint resolving
    anybody."""
    member = await acting_user(guild_role=GuildRole.member)
    await _set_support(session, member.guild.id, True)
    assert (await _ask(client, member, member.guild.id)).status_code == 202

    await set_rls_context(session, guild_id=operations["guild"].id, guild_role="admin")
    case = (await session.exec(select(IntakeCase))).one()
    from app.models.tenant.property import TaskPropertyValue

    values = (
        await session.exec(
            select(TaskPropertyValue).where(TaskPropertyValue.task_id == case.task_id)
        )
    ).all()
    held = {int(v.value_number) for v in values if v.value_number is not None}
    assert member.user.id in held
    assert member.guild.id in held


async def test_asking_where_nothing_is_bound_says_so(client, session, acting_user):
    """Support is on, but the deployment routes nothing. The asker is told,
    rather than being thanked for a request that reached nobody."""
    member = await acting_user(guild_role=GuildRole.member)
    await _set_support(session, member.guild.id, True)

    response = await _ask(client, member, member.guild.id)
    assert response.status_code == 503, response.text
    assert response.json()["detail"] == SupportMessages.NOWHERE_TO_SEND


async def test_a_stranger_cannot_ask_on_a_community_they_are_not_in(
    client, session, acting_user, operations
):
    """The guild gate, which is not this endpoint's to re-decide."""
    host = await acting_user(guild_role=GuildRole.admin)
    await _set_support(session, host.guild.id, True)
    outsider = await acting_user(guild_role=GuildRole.member)

    response = await _ask(client, outsider, host.guild.id)
    assert response.status_code == 403, response.text


async def test_every_support_error_code_is_localized():
    """A refusal reaches the reader as its own sentence."""
    import json
    from pathlib import Path

    codes = {
        value
        for name, value in vars(SupportMessages).items()
        if not name.startswith("_") and isinstance(value, str)
    }
    locales = Path(__file__).resolve().parents[4].parent / "frontend/public/locales"
    for locale in ("de", "en", "es", "fr"):
        catalogue = json.loads((locales / locale / "errors.json").read_text())
        missing = sorted(codes - set(catalogue))
        assert not missing, f"{locale}/errors.json is missing {missing}"
