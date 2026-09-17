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


async def test_a_bare_request_is_a_content_read(
    client: AsyncClient, session: AsyncSession
):
    """Naming neither axis means what it always meant."""
    support = await create_user(session, role=UserRole.support)
    guild = await create_guild(session)

    response = await client.post(
        "/api/v1/access-grants/",
        headers=get_auth_headers(support),
        json={"guild_id": guild.id, "reason": "having a look"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["purpose"] == "content"
    assert response.json()["access_level"] == "read"


async def test_a_lesser_grant_does_not_stand_in_the_way_of_breaking_glass(
    client: AsyncClient, session: AsyncSession
):
    """The moment glass is broken is the moment a standing grant is most likely
    to be open. It is superseded, not an obstacle."""
    owner = await create_user(session, role=UserRole.owner)
    operator = await create_user(session, role=UserRole.operator)
    guild = await create_guild(session, creator=owner)

    lesser = await _request_and_approve(
        client, requester=operator, approver=owner, guild=guild, rung="admin"
    )

    broken = await client.post(
        "/api/v1/access-grants/break-glass",
        headers=get_auth_headers(operator),
        json={"guild_id": guild.id, "reason": "incident, and I already had one"},
    )
    assert broken.status_code == 201, broken.text

    listed = await client.get(
        "/api/v1/access-grants/?mine=true", headers=get_auth_headers(operator)
    )
    grants = {g["id"]: g for g in listed.json()}
    # The pair is live...
    live = {(g["purpose"], g["access_level"]) for g in grants.values() if g["is_live"]}
    assert live == {("content", "read_write"), ("settings", "superadmin")}
    # ...and the one it replaced is revoked rather than gone, so the log keeps
    # both.
    assert grants[lesser["id"]]["status"] == "revoked"


async def test_one_request_can_ask_for_both(client: AsyncClient, session: AsyncSession):
    """Clearing up after an incident takes write access to the content *and*
    the settings that govern it. One ask, two grants — so an approver decides
    about each and the log keeps them apart."""
    support = await create_user(session, role=UserRole.support)
    guild = await create_guild(session)
    headers = get_auth_headers(support)

    response = await client.post(
        "/api/v1/access-grants/",
        headers=headers,
        json={
            "guild_id": guild.id,
            "access_level": "read_write",
            "settings_level": "admin",
            "reason": "clearing up after the incident",
        },
    )
    assert response.status_code == 201, response.text
    # The content one comes back, being what a caller routes in under.
    assert response.json()["purpose"] == "content"

    listed = await client.get("/api/v1/access-grants/?mine=true", headers=headers)
    asked = {(g["purpose"], g["access_level"]) for g in listed.json()}
    assert asked == {("content", "read_write"), ("settings", "admin")}
