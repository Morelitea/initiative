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

from app.models.platform.guild import GuildRole
from app.testing import Actor


@pytest.fixture(autouse=True)
def _force_prod_flag(monkeypatch):
    """Pin the SSRF dev flag to False so tests assert on production
    semantics regardless of local ``.env``."""
    from app.core import config as config_module

    monkeypatch.setattr(config_module.settings, "WEBHOOK_ALLOW_PRIVATE_TARGETS", False)


async def _authed_post(client: AsyncClient, actor: Actor, body: dict):
    return await client.post(
        actor.g("/auto/subscriptions"), json=body, headers=actor.headers
    )


@pytest.mark.integration
async def test_create_rejects_loopback_target_url(client: AsyncClient, acting_user):
    """Registering a target that resolves to loopback must 400. Without
    this guard, every guild member could redirect outbound dispatches to
    internal services."""
    a = await acting_user(guild_role=GuildRole.admin)

    response = await _authed_post(
        client,
        a,
        body={
            "target_url": "https://127.0.0.1/hook",
            "event_types": ["task.created"],
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "WEBHOOK_PRIVATE_TARGET_URL"


@pytest.mark.integration
async def test_create_rejects_metadata_endpoint(client: AsyncClient, acting_user):
    """The cloud-metadata endpoint is the canonical SSRF target — keep
    it explicitly in the test suite so a regression is loud."""
    a = await acting_user(guild_role=GuildRole.admin)

    response = await _authed_post(
        client,
        a,
        body={
            "target_url": "https://169.254.169.254/latest/meta-data/iam/",
            "event_types": ["task.created"],
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "WEBHOOK_PRIVATE_TARGET_URL"


@pytest.mark.integration
async def test_create_rejects_plain_http(client: AsyncClient, acting_user):
    """Plain http:// is rejected with the structural-invalid code so
    the operator sees a different error than for a private-IP target."""
    a = await acting_user(guild_role=GuildRole.admin)

    response = await _authed_post(
        client,
        a,
        body={
            "target_url": "http://hooks.example.com/in",
            "event_types": ["task.created"],
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "WEBHOOK_INVALID_TARGET_URL"


@pytest.mark.integration
async def test_create_accepts_public_target_when_dns_resolves_public(
    client: AsyncClient, acting_user
):
    """Public-resolving hostnames are allowed. We mock DNS so the test
    isn't network-dependent; the value being a public unicast IP is
    what we're asserting on."""
    a = await acting_user(guild_role=GuildRole.admin)

    fake_infos = [(2, 0, 0, "", ("93.184.216.34", 0))]  # example.com IPv4
    with patch(
        "app.services.webhook_target_url.socket.getaddrinfo",
        return_value=fake_infos,
    ):
        response = await _authed_post(
            client,
            a,
            body={
                "target_url": "https://hooks.example.com/in",
                "event_types": ["task.created"],
            },
        )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["target_url"] == "https://hooks.example.com/in"
    assert body["created_by_user_id"] == a.user.id
    assert "hmac_secret" in body  # one-time payload includes the secret


@pytest.mark.integration
async def test_non_owner_member_cannot_delete(client: AsyncClient, acting_user):
    """A guild member who didn't create the subscription must not be
    able to delete it. RLS keeps the row visible inside the guild but
    that's not the same as authority to mutate it."""
    creator = await acting_user(guild_role=GuildRole.admin)
    other = await acting_user(guild_role=GuildRole.member, guild=creator.guild)

    fake_infos = [(2, 0, 0, "", ("93.184.216.34", 0))]
    with patch(
        "app.services.webhook_target_url.socket.getaddrinfo",
        return_value=fake_infos,
    ):
        created = await _authed_post(
            client,
            creator,
            body={
                "target_url": "https://hooks.example.com/in",
                "event_types": ["task.created"],
            },
        )
    assert created.status_code == 201
    sub_id = created.json()["id"]

    response = await client.delete(
        other.g(f"/auto/subscriptions/{sub_id}"),
        headers=other.headers,
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "WEBHOOK_SUBSCRIPTION_NOT_OWNER"


@pytest.mark.integration
async def test_non_owner_member_cannot_update(client: AsyncClient, acting_user):
    """Same authority check on PATCH — flipping ``active`` or rewriting
    ``target_url`` are both mutations."""
    creator = await acting_user(guild_role=GuildRole.admin)
    other = await acting_user(guild_role=GuildRole.member, guild=creator.guild)

    fake_infos = [(2, 0, 0, "", ("93.184.216.34", 0))]
    with patch(
        "app.services.webhook_target_url.socket.getaddrinfo",
        return_value=fake_infos,
    ):
        created = await _authed_post(
            client,
            creator,
            body={
                "target_url": "https://hooks.example.com/in",
                "event_types": ["task.created"],
            },
        )
    assert created.status_code == 201
    sub_id = created.json()["id"]

    response = await client.patch(
        other.g(f"/auto/subscriptions/{sub_id}"),
        json={"active": False},
        headers=other.headers,
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "WEBHOOK_SUBSCRIPTION_NOT_OWNER"


@pytest.mark.integration
async def test_guild_admin_can_delete_others_subscription(
    client: AsyncClient, acting_user
):
    """Guild admins are the explicit exception to the creator-only rule
    — they can clean up subscriptions left behind by members who left
    or had access revoked."""
    creator = await acting_user(guild_role=GuildRole.member)
    admin = await acting_user(guild_role=GuildRole.admin, guild=creator.guild)

    fake_infos = [(2, 0, 0, "", ("93.184.216.34", 0))]
    with patch(
        "app.services.webhook_target_url.socket.getaddrinfo",
        return_value=fake_infos,
    ):
        created = await _authed_post(
            client,
            creator,
            body={
                "target_url": "https://hooks.example.com/in",
                "event_types": ["task.created"],
            },
        )
    assert created.status_code == 201
    sub_id = created.json()["id"]

    response = await client.delete(
        admin.g(f"/auto/subscriptions/{sub_id}"),
        headers=admin.headers,
    )
    assert response.status_code == 204


@pytest.mark.integration
async def test_creator_can_update_own_subscription(client: AsyncClient, acting_user):
    """The happy path: the creator can mutate their own subscription."""
    a = await acting_user(guild_role=GuildRole.member)

    fake_infos = [(2, 0, 0, "", ("93.184.216.34", 0))]
    with patch(
        "app.services.webhook_target_url.socket.getaddrinfo",
        return_value=fake_infos,
    ):
        created = await _authed_post(
            client,
            a,
            body={
                "target_url": "https://hooks.example.com/in",
                "event_types": ["task.created"],
            },
        )
    assert created.status_code == 201
    sub_id = created.json()["id"]

    response = await client.patch(
        a.g(f"/auto/subscriptions/{sub_id}"),
        json={"active": False},
        headers=a.headers,
    )
    assert response.status_code == 200
    assert response.json()["active"] is False
