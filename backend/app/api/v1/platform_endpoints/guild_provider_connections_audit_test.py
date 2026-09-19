"""What a community's own sign-in configuration writes down.

Two halves of one sentence, and both are recorded against the community they
are about: which provider its people come in through, and where the groups
that provider asserts land. Every record carries ``guild_id``, which is the
column a community's log is read by.
"""

from __future__ import annotations

import json

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.models.platform.guild import Guild, GuildRole
from app.testing.audit import recorded
from app.testing.factories import (
    create_auth_provider,
    create_guild,
    create_guild_membership,
    create_guild_provider_connection,
    create_user,
    get_auth_headers,
)

pytestmark = [pytest.mark.integration, pytest.mark.auth]

TENANT_CLAIM_VALUE = "morels.me"
GROUP_CLAIM_VALUE = "eng-team"


async def _seat(session: AsyncSession) -> tuple[int | None, Guild, dict[str, str]]:
    """A community and the seat that decides who may enter it."""
    admin = await create_user(session)
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.superadmin
    )
    return admin.id, guild, get_auth_headers(admin)


def _connections(guild_id: int) -> str:
    return f"/api/v1/guilds/{guild_id}/auth/connections"


def _rules(guild_id: int) -> str:
    return f"/api/v1/guilds/{guild_id}/auth/rules"


# --- connections -------------------------------------------------------------


async def test_connecting_narrowing_and_disconnecting_are_each_recorded(
    client: AsyncClient, session: AsyncSession
):
    admin_id, guild, headers = await _seat(session)
    guild_id = guild.id
    provider = await create_auth_provider(session, slug="google")
    provider_id = provider.id

    connected = await client.post(
        _connections(guild_id),
        headers=headers,
        json={
            "provider_id": provider_id,
            "claim": "hd",
            "claim_values": [TENANT_CLAIM_VALUE],
        },
    )
    assert connected.status_code == 201, connected.text
    connection_id = connected.json()["id"]

    narrowed = await client.patch(
        f"{_connections(guild_id)}/{connection_id}",
        headers=headers,
        json={"auto_join": True},
    )
    assert narrowed.status_code == 200, narrowed.text
    gone = await client.delete(
        f"{_connections(guild_id)}/{connection_id}", headers=headers
    )
    assert gone.status_code == 204, gone.text

    for event in (
        AuditEventType.GUILD_PROVIDER_CONNECTED,
        AuditEventType.GUILD_PROVIDER_CONNECTION_UPDATED,
        AuditEventType.GUILD_PROVIDER_DISCONNECTED,
    ):
        rows = await recorded(session, event)
        assert [
            (r.actor_user_id, r.guild_id, r.target_type, r.target_id) for r in rows
        ] == [(admin_id, guild_id, "guild_provider_connection", connection_id)], event
        assert rows[0].envelope["detail"]["provider_id"] == provider_id

    born = (await recorded(session, AuditEventType.GUILD_PROVIDER_CONNECTED))[0]
    detail = born.envelope["detail"]
    assert {"provider_id", "claim", "claim_values", "enabled"} <= set(detail["changed"])
    # The claim and the values that count are strings: named, never copied.
    assert "claim" not in detail["values"]
    assert "claim_values" not in detail["values"]
    assert detail["values"]["enabled"] == {"from": None, "to": True}
    assert TENANT_CLAIM_VALUE not in json.dumps(born.envelope)

    updated = AuditEventType.GUILD_PROVIDER_CONNECTION_UPDATED
    moved = (await recorded(session, updated))[0]
    assert moved.envelope["detail"]["changed"] == ["auto_join"]
    assert moved.envelope["detail"]["values"]["auto_join"] == {
        "from": False,
        "to": True,
    }


async def test_a_connection_edit_that_changes_nothing_records_nothing(
    client: AsyncClient, session: AsyncSession
):
    _, guild, headers = await _seat(session)
    provider = await create_auth_provider(session, slug="google")
    connection = await create_guild_provider_connection(
        session, guild=guild, provider=provider
    )

    same = await client.patch(
        f"{_connections(guild.id)}/{connection.id}",
        headers=headers,
        json={"enabled": True, "auto_join": False},
    )
    assert same.status_code == 200, same.text

    assert (
        await recorded(session, AuditEventType.GUILD_PROVIDER_CONNECTION_UPDATED) == []
    )


async def test_a_refused_connection_write_records_nothing(
    client: AsyncClient, session: AsyncSession
):
    """Running a community is not the seat that decides who may enter it."""
    _, guild, _ = await _seat(session)
    ordinary = await create_user(session)
    await create_guild_membership(
        session, user=ordinary, guild=guild, role=GuildRole.admin
    )
    provider = await create_auth_provider(session, slug="google")

    refused = await client.post(
        _connections(guild.id),
        headers=get_auth_headers(ordinary),
        json={"provider_id": provider.id},
    )
    assert refused.status_code == 403, refused.text

    assert await recorded(session, AuditEventType.GUILD_PROVIDER_CONNECTED) == []


# --- the rules riding a connection -------------------------------------------


async def test_a_communitys_own_rule_is_recorded_through_its_life(
    client: AsyncClient, session: AsyncSession
):
    admin_id, guild, headers = await _seat(session)
    guild_id = guild.id
    provider = await create_auth_provider(
        session, slug="entra", role_claim_path="groups"
    )
    provider_id = provider.id
    await create_guild_provider_connection(session, guild=guild, provider=provider)

    created = await client.post(
        _rules(guild_id),
        headers=headers,
        json={
            "provider_id": provider_id,
            "claim_value": GROUP_CLAIM_VALUE,
            "guild_role": "member",
        },
    )
    assert created.status_code == 201, created.text
    rule_id = created.json()["id"]

    raised = await client.patch(
        f"{_rules(guild_id)}/{rule_id}", headers=headers, json={"guild_role": "admin"}
    )
    assert raised.status_code == 200, raised.text
    gone = await client.delete(f"{_rules(guild_id)}/{rule_id}", headers=headers)
    assert gone.status_code == 204, gone.text

    for event in (
        AuditEventType.CLAIM_RULE_CREATED,
        AuditEventType.CLAIM_RULE_UPDATED,
        AuditEventType.CLAIM_RULE_DELETED,
    ):
        rows = await recorded(session, event)
        assert [
            (r.actor_user_id, r.guild_id, r.target_type, r.target_id) for r in rows
        ] == [(admin_id, guild_id, "claim_rule", rule_id)], event
        # The same rows an operator writes, told apart by who wrote them.
        assert rows[0].envelope["detail"]["via"] == "guild"

    born = (await recorded(session, AuditEventType.CLAIM_RULE_CREATED))[0]
    assert GROUP_CLAIM_VALUE not in json.dumps(born.envelope)
    assert born.envelope["detail"]["values"]["provider_id"] == {
        "from": None,
        "to": provider_id,
    }

    moved = (await recorded(session, AuditEventType.CLAIM_RULE_UPDATED))[0]
    assert moved.envelope["detail"]["changed"] == ["guild_role"]


async def test_a_rule_edit_that_changes_nothing_records_nothing(
    client: AsyncClient, session: AsyncSession
):
    _, guild, headers = await _seat(session)
    provider = await create_auth_provider(session, slug="entra")
    await create_guild_provider_connection(session, guild=guild, provider=provider)
    created = await client.post(
        _rules(guild.id),
        headers=headers,
        json={
            "provider_id": provider.id,
            "claim_value": GROUP_CLAIM_VALUE,
            "guild_role": "member",
        },
    )
    assert created.status_code == 201, created.text

    same = await client.patch(
        f"{_rules(guild.id)}/{created.json()['id']}",
        headers=headers,
        json={"guild_role": "member"},
    )
    assert same.status_code == 200, same.text

    assert await recorded(session, AuditEventType.CLAIM_RULE_UPDATED) == []
