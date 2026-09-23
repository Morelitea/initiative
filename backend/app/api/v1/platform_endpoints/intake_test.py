"""The owner's intake settings: which community, and who to contact.

Where each stream lands inside that community is the community's own setting
(``tenant_endpoints/intake_test.py``); nothing here reads it.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlmodel import select

from app.core.intake import IntakeStream
from app.db.session import set_rls_context
from app.models.platform.app_setting import AppSetting
from app.models.tenant.intake import IntakeBinding
from app.services.platform import intake as intake_service
from app.testing import (
    create_guild,
    create_initiative,
    create_project,
    create_user,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def owner(session, acting_user):
    """A platform owner, and a community they can point operations at.

    The owner is not a member of it: naming the community is the platform's,
    and reads nothing inside it.
    """
    actor = await acting_user("owner")
    guild_owner = await create_user(session)
    guild = await create_guild(session, creator=guild_owner, name="Operations")
    initiative = await create_initiative(session, guild, guild_owner)
    project = await create_project(session, initiative, guild_owner)
    ids = {
        "actor": actor,
        "guild_id": guild.id,
        "project_id": project.id,
    }
    await set_rls_context(session)
    return ids


async def _bind(session, *, guild_id: int, project_id: int, stream: IntakeStream):
    """Bind a stream directly, the way the community's own route would."""
    await set_rls_context(session, guild_id=guild_id)
    session.add(IntakeBinding(stream=stream.value, project_id=project_id))
    await session.commit()
    await set_rls_context(session)


async def test_nothing_is_named_before_anything_is_configured(client, owner):
    response = await client.get(
        "/api/v1/settings/intake", headers=owner["actor"].headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["operations_guild_id"] is None
    assert body["operations_guild_name"] is None
    assert body["receiving"] == []
    assert "bindings" not in body


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


async def test_an_operator_cannot_name_the_community(client, acting_user):
    """Managing communities is not configuring the deployment."""
    actor = await acting_user("operator")
    response = await client.put(
        "/api/v1/settings/intake/guild", json={"guild_id": 1}, headers=actor.headers
    )
    assert response.status_code == 403


async def test_pointing_at_a_guild_that_does_not_exist_is_refused(client, owner):
    response = await client.put(
        "/api/v1/settings/intake/guild",
        json={"guild_id": 99_999},
        headers=owner["actor"].headers,
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "GUILD_NOT_FOUND"


async def test_naming_the_community_returns_its_name_and_nothing_inside_it(
    client, session, owner
):
    await _bind(
        session,
        guild_id=owner["guild_id"],
        project_id=owner["project_id"],
        stream=IntakeStream.support,
    )
    response = await client.put(
        "/api/v1/settings/intake/guild",
        json={"guild_id": owner["guild_id"]},
        headers=owner["actor"].headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["operations_guild_id"] == owner["guild_id"]
    assert body["operations_guild_name"] == "Operations"
    # Which streams receive, and nothing about where they land.
    assert body["receiving"] == ["support"]
    assert "bindings" not in body


async def test_clearing_the_pointer_stops_every_stream(client, session, owner):
    await _bind(
        session,
        guild_id=owner["guild_id"],
        project_id=owner["project_id"],
        stream=IntakeStream.support,
    )
    await client.put(
        "/api/v1/settings/intake/guild",
        json={"guild_id": owner["guild_id"]},
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
    assert response.json()["receiving"] == []
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


# ── Who to contact ──────────────────────────────────────────────────────────


async def test_contacts_start_empty(client, owner):
    body = (
        await client.get("/api/v1/settings/intake", headers=owner["actor"].headers)
    ).json()
    assert body["general_contact_email"] is None
    assert body["contact_emails"] == {}


async def test_the_general_and_a_stream_contact_are_set_and_cleared(client, owner):
    headers = owner["actor"].headers
    response = await client.put(
        "/api/v1/settings/intake/contact",
        headers=headers,
        json={"email": "ops@example.com"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["general_contact_email"] == "ops@example.com"

    response = await client.put(
        "/api/v1/settings/intake/moderation/contact",
        headers=headers,
        json={"email": "trust@example.com"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["contact_emails"] == {"moderation": "trust@example.com"}

    response = await client.put(
        "/api/v1/settings/intake/moderation/contact",
        headers=headers,
        json={"email": None},
    )
    assert response.json()["contact_emails"] == {}
    assert response.json()["general_contact_email"] == "ops@example.com"

    response = await client.put(
        "/api/v1/settings/intake/contact", headers=headers, json={"email": None}
    )
    assert response.json()["general_contact_email"] is None


async def test_a_contact_must_be_an_address(client, owner):
    response = await client.put(
        "/api/v1/settings/intake/contact",
        headers=owner["actor"].headers,
        json={"email": "not an address"},
    )
    assert response.status_code == 422


async def test_a_contact_for_an_unknown_stream_is_refused(client, owner):
    response = await client.put(
        "/api/v1/settings/intake/billing/contact",
        headers=owner["actor"].headers,
        json={"email": "ops@example.com"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "INTAKE_UNKNOWN_STREAM"


async def test_a_member_cannot_set_a_contact(client, acting_user):
    member = await acting_user("member")
    response = await client.put(
        "/api/v1/settings/intake/contact",
        headers=member.headers,
        json={"email": "ops@example.com"},
    )
    assert response.status_code == 403


async def test_a_stream_falls_back_to_the_general_contact_and_never_to_another(
    client, session, owner
):
    headers = owner["actor"].headers
    await set_rls_context(session)
    assert await intake_service.contact_for(session, IntakeStream.moderation) is None

    await client.put(
        "/api/v1/settings/intake/support/contact",
        headers=headers,
        json={"email": "help@example.com"},
    )
    await set_rls_context(session)
    session.expire_all()
    assert await intake_service.contact_for(session, IntakeStream.moderation) is None
    assert (
        await intake_service.contact_for(session, IntakeStream.support)
        == "help@example.com"
    )

    await client.put(
        "/api/v1/settings/intake/contact",
        headers=headers,
        json={"email": "ops@example.com"},
    )
    await set_rls_context(session)
    session.expire_all()
    assert (
        await intake_service.contact_for(session, IntakeStream.moderation)
        == "ops@example.com"
    )
    assert (
        await intake_service.contact_for(session, IntakeStream.support)
        == "help@example.com"
    )
