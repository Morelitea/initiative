"""A grant for a community's settings, and nothing inside it."""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.user import UserRole
from app.testing.factories import (
    create_guild,
    create_initiative,
    create_user,
    get_auth_headers,
)

pytestmark = [pytest.mark.integration, pytest.mark.auth]


async def _request_and_approve(client, *, requester, approver, guild, rung):
    asked = await client.post(
        "/api/v1/access-grants/",
        headers=get_auth_headers(requester),
        json={
            "guild_id": guild.id,
            "purpose": "settings",
            "settings_level": rung,
            "reason": "billing question from the community",
        },
    )
    assert asked.status_code == 201, asked.text
    assert asked.json()["purpose"] == "settings"
    assert asked.json()["access_level"] == rung

    decided = await client.post(
        f"/api/v1/access-grants/{asked.json()['id']}/approve",
        headers=get_auth_headers(approver),
        json={},
    )
    assert decided.status_code == 200, decided.text
    return decided.json()


async def test_a_settings_grant_reaches_settings_and_no_content(
    client: AsyncClient, session: AsyncSession
):
    """The whole point of splitting the axes: somebody sent to help with
    billing or moderation settings reaches the configuration and reads
    nobody's work."""
    owner = await create_user(session, role=UserRole.owner)
    support = await create_user(session, role=UserRole.support)
    guild = await create_guild(session, creator=owner)
    await create_initiative(session, guild, owner, name="Private Wing")

    await _request_and_approve(
        client, requester=support, approver=owner, guild=guild, rung="superadmin"
    )
    headers = get_auth_headers(support)

    # The community's own configuration: reachable.
    policy = await client.get(f"/api/v1/guilds/{guild.id}/auth-policy", headers=headers)
    assert policy.status_code == 200, policy.text

    # Its content: not. A settings grant carries no content level at all, so
    # the guild's initiatives are not this grantee's to read.
    content = await client.get(f"/api/v1/g/{guild.id}/initiatives/", headers=headers)
    assert content.status_code in (403, 404), content.text


async def test_the_admin_rung_does_not_reach_the_seat(
    client: AsyncClient, session: AsyncSession
):
    """Two rungs, and the lower one stops short of what the seat holds."""
    owner = await create_user(session, role=UserRole.owner)
    support = await create_user(session, role=UserRole.support)
    guild = await create_guild(session, creator=owner)

    await _request_and_approve(
        client, requester=support, approver=owner, guild=guild, rung="admin"
    )
    headers = get_auth_headers(support)

    refused = await client.put(
        f"/api/v1/guilds/{guild.id}/api-access",
        headers=headers,
        json={"allow_api_keys": False},
    )
    assert refused.status_code == 403, refused.text


async def test_a_settings_request_names_its_rung(
    client: AsyncClient, session: AsyncSession
):
    """There is no sensible default between what an admin runs and what the
    seat holds, so a request that names neither is not a request."""
    support = await create_user(session, role=UserRole.support)
    guild = await create_guild(session)

    response = await client.post(
        "/api/v1/access-grants/",
        headers=get_auth_headers(support),
        json={
            "guild_id": guild.id,
            "purpose": "settings",
            "reason": "no rung named",
        },
    )
    assert response.status_code == 422, response.text
