"""Integration tests for the webhook subscription endpoints.

These cover the two security properties the routes enforce on top of
RLS: SSRF rejection on ``target_url`` and the creator-or-admin gate on
mutations. CRUD round-trips themselves are exercised by the dispatcher
tests (which create rows via the same service layer).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from httpx import AsyncClient

from app.models.guild import GuildRole
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_user,
    get_guild_headers,
)


async def _authed_post(
    client: AsyncClient, *, headers: dict[str, str], body: dict
):
    return await client.post("/api/v1/auto/subscriptions", json=body, headers=headers)


@pytest.mark.integration
async def test_create_rejects_loopback_target_url(client: AsyncClient, session):
    """Registering a target that resolves to loopback must 400. Without
    this guard, every guild member could redirect outbound dispatches to
    internal services."""
    user = await create_user(session, email="hook-loopback@example.com")
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)

    response = await _authed_post(
        client,
        headers=get_guild_headers(guild, user),
        body={
            "target_url": "http://127.0.0.1/hook",
            "event_types": ["task.created"],
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "WEBHOOK_PRIVATE_TARGET_URL"


@pytest.mark.integration
async def test_create_rejects_metadata_endpoint(client: AsyncClient, session):
    """The cloud-metadata endpoint is the canonical SSRF target — keep
    it explicitly in the test suite so a regression is loud."""
    user = await create_user(session, email="hook-metadata@example.com")
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)

    response = await _authed_post(
        client,
        headers=get_guild_headers(guild, user),
        body={
            "target_url": "http://169.254.169.254/latest/meta-data/iam/",
            "event_types": ["task.created"],
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "WEBHOOK_PRIVATE_TARGET_URL"


@pytest.mark.integration
async def test_create_accepts_public_target_when_dns_resolves_public(
    client: AsyncClient, session
):
    """Public-resolving hostnames are allowed. We mock DNS so the test
    isn't network-dependent; the value being a public unicast IP is
    what we're asserting on."""
    user = await create_user(session, email="hook-public@example.com")
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)

    fake_infos = [(2, 0, 0, "", ("93.184.216.34", 0))]  # example.com IPv4
    with patch(
        "app.services.webhook_target_url.socket.getaddrinfo",
        return_value=fake_infos,
    ):
        response = await _authed_post(
            client,
            headers=get_guild_headers(guild, user),
            body={
                "target_url": "https://hooks.example.com/in",
                "event_types": ["task.created"],
            },
        )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["target_url"] == "https://hooks.example.com/in"
    assert body["created_by_user_id"] == user.id
    assert "hmac_secret" in body  # one-time payload includes the secret


@pytest.mark.integration
async def test_non_owner_member_cannot_delete(client: AsyncClient, session):
    """A guild member who didn't create the subscription must not be
    able to delete it. RLS keeps the row visible inside the guild but
    that's not the same as authority to mutate it."""
    creator = await create_user(session, email="hook-creator@example.com")
    other = await create_user(session, email="hook-other@example.com")
    guild = await create_guild(session, creator=creator)
    await create_guild_membership(session, user=creator, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=other, guild=guild, role=GuildRole.member)

    fake_infos = [(2, 0, 0, "", ("93.184.216.34", 0))]
    with patch(
        "app.services.webhook_target_url.socket.getaddrinfo",
        return_value=fake_infos,
    ):
        created = await _authed_post(
            client,
            headers=get_guild_headers(guild, creator),
            body={
                "target_url": "https://hooks.example.com/in",
                "event_types": ["task.created"],
            },
        )
    assert created.status_code == 201
    sub_id = created.json()["id"]

    response = await client.delete(
        f"/api/v1/auto/subscriptions/{sub_id}",
        headers=get_guild_headers(guild, other),
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "WEBHOOK_SUBSCRIPTION_NOT_OWNER"


@pytest.mark.integration
async def test_non_owner_member_cannot_update(client: AsyncClient, session):
    """Same authority check on PATCH — flipping ``active`` or rewriting
    ``target_url`` are both mutations."""
    creator = await create_user(session, email="hook-creator2@example.com")
    other = await create_user(session, email="hook-other2@example.com")
    guild = await create_guild(session, creator=creator)
    await create_guild_membership(session, user=creator, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=other, guild=guild, role=GuildRole.member)

    fake_infos = [(2, 0, 0, "", ("93.184.216.34", 0))]
    with patch(
        "app.services.webhook_target_url.socket.getaddrinfo",
        return_value=fake_infos,
    ):
        created = await _authed_post(
            client,
            headers=get_guild_headers(guild, creator),
            body={
                "target_url": "https://hooks.example.com/in",
                "event_types": ["task.created"],
            },
        )
    assert created.status_code == 201
    sub_id = created.json()["id"]

    response = await client.patch(
        f"/api/v1/auto/subscriptions/{sub_id}",
        json={"active": False},
        headers=get_guild_headers(guild, other),
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "WEBHOOK_SUBSCRIPTION_NOT_OWNER"


@pytest.mark.integration
async def test_guild_admin_can_delete_others_subscription(
    client: AsyncClient, session
):
    """Guild admins are the explicit exception to the creator-only rule
    — they can clean up subscriptions left behind by members who left
    or had access revoked."""
    creator = await create_user(session, email="hook-creator3@example.com")
    admin = await create_user(session, email="hook-admin3@example.com")
    guild = await create_guild(session, creator=creator)
    await create_guild_membership(session, user=creator, guild=guild, role=GuildRole.member)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)

    fake_infos = [(2, 0, 0, "", ("93.184.216.34", 0))]
    with patch(
        "app.services.webhook_target_url.socket.getaddrinfo",
        return_value=fake_infos,
    ):
        created = await _authed_post(
            client,
            headers=get_guild_headers(guild, creator),
            body={
                "target_url": "https://hooks.example.com/in",
                "event_types": ["task.created"],
            },
        )
    assert created.status_code == 201
    sub_id = created.json()["id"]

    response = await client.delete(
        f"/api/v1/auto/subscriptions/{sub_id}",
        headers=get_guild_headers(guild, admin),
    )
    assert response.status_code == 204


@pytest.mark.integration
async def test_creator_can_update_own_subscription(client: AsyncClient, session):
    """The happy path: the creator can mutate their own subscription."""
    user = await create_user(session, email="hook-self@example.com")
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.member)

    fake_infos = [(2, 0, 0, "", ("93.184.216.34", 0))]
    with patch(
        "app.services.webhook_target_url.socket.getaddrinfo",
        return_value=fake_infos,
    ):
        created = await _authed_post(
            client,
            headers=get_guild_headers(guild, user),
            body={
                "target_url": "https://hooks.example.com/in",
                "event_types": ["task.created"],
            },
        )
    assert created.status_code == 201
    sub_id = created.json()["id"]

    response = await client.patch(
        f"/api/v1/auto/subscriptions/{sub_id}",
        json={"active": False},
        headers=get_guild_headers(guild, user),
    )
    assert response.status_code == 200
    assert response.json()["active"] is False
