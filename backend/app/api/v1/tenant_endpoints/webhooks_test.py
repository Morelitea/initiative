"""Webhook subscription endpoints.

These cover the three things registration decides, now that the delegate gate is
gone:

* **Who may register one** — any guild member, because registering grants no
  access: delivery reads the change log as the creator, so a subscription's
  reach is its owner's reach.
* **Who may rewrite one** — its creator or a guild admin, the ordinary
  ownership rule.
* **What a subscription may name** — event types and field names are checked
  against the capture vocabulary, so a typo is a 400 here rather than a
  subscription that looks healthy and never fires.
"""

from __future__ import annotations

import socket
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from app.models.platform.guild import GuildRole

pytestmark = pytest.mark.integration


_WEBHOOK_HOST = "hooks.example.com"
# A public unicast IPv4 (example.com) with a real stream socket type/proto, so
# constructing a socket from the tuple is valid.
_FAKE_INFOS = [
    (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 0))
]


@contextmanager
def _mock_public_dns():
    """Resolve the webhook host to a fixed public IP without hitting the network.

    The patch target is the shared ``socket`` module, so a blanket
    ``return_value`` would also answer asyncpg's own ``getaddrinfo`` for the DB
    host mid-request — feeding it a bogus address (and a ``type=0`` tuple that
    ``socket.socket`` rejects). Scope the fake to the webhook host and pass every
    other lookup through to the real resolver.
    """
    real_getaddrinfo = socket.getaddrinfo

    def fake(host, *args, **kwargs):
        if host == _WEBHOOK_HOST:
            return _FAKE_INFOS
        return real_getaddrinfo(host, *args, **kwargs)

    with patch("app.services.webhook_target_url.socket.getaddrinfo", side_effect=fake):
        yield


def _url(guild_id: int, suffix: str = "") -> str:
    return f"/api/v1/g/{guild_id}/webhooks/subscriptions{suffix}"


def _body(**overrides) -> dict:
    payload = {
        "target_url": f"https://{_WEBHOOK_HOST}/in",
        "event_types": ["tasks.created"],
    }
    payload.update(overrides)
    return payload


async def test_a_guild_member_may_register_a_subscription(client, acting_user):
    """No special permission: what the target receives is capped by the
    creator's own access at delivery time, so registering grants nothing."""
    a = await acting_user(guild_role=GuildRole.member)

    with _mock_public_dns():
        response = await client.post(_url(a.guild.id), json=_body(), headers=a.headers)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["event_types"] == ["tasks.created"]
    # The secret is returned exactly once, here.
    assert body["hmac_secret"]


async def test_the_secret_is_never_returned_again(client, acting_user):
    a = await acting_user(guild_role=GuildRole.member)
    with _mock_public_dns():
        await client.post(_url(a.guild.id), json=_body(), headers=a.headers)

    listing = await client.get(_url(a.guild.id), headers=a.headers)

    assert listing.status_code == 200
    assert listing.json()
    assert all("hmac_secret" not in row for row in listing.json())


async def test_an_unknown_event_type_is_refused(client, acting_user):
    """The failure this whole mechanism exists to remove: a subscription that
    registers cleanly and can never fire."""
    a = await acting_user(guild_role=GuildRole.member)

    with _mock_public_dns():
        response = await client.post(
            _url(a.guild.id),
            json=_body(event_types=["taks.updated"]),
            headers=a.headers,
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "WEBHOOK_UNKNOWN_EVENT_TYPE"


async def test_an_unknown_field_is_refused(client, acting_user):
    a = await acting_user(guild_role=GuildRole.member)

    with _mock_public_dns():
        response = await client.post(
            _url(a.guild.id),
            json=_body(event_types=["tasks.updated"], fields=["not_a_column"]),
            headers=a.headers,
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "WEBHOOK_UNKNOWN_FIELD"


async def test_a_junction_facet_is_a_nameable_field(client, acting_user):
    """``tags`` is not a column on tasks — a row in ``task_tags`` reports as
    ``tasks.updated`` with ``changed: ['tags']``, so it has to be nameable."""
    a = await acting_user(guild_role=GuildRole.member)

    with _mock_public_dns():
        response = await client.post(
            _url(a.guild.id),
            json=_body(
                event_types=["tasks.updated"], fields=["tags", "task_status_id"]
            ),
            headers=a.headers,
        )

    assert response.status_code == 201, response.text
    assert sorted(response.json()["fields"]) == ["tags", "task_status_id"]


async def test_a_non_owner_member_gets_a_404_not_a_403(client, acting_user):
    """Own-row RLS hides the row rather than refusing the write, so the reply
    does not confirm that someone else's subscription exists."""
    a = await acting_user(guild_role=GuildRole.admin)
    with _mock_public_dns():
        created = await client.post(_url(a.guild.id), json=_body(), headers=a.headers)
    subscription_id = created.json()["id"]

    b = await acting_user(guild_role=GuildRole.member, guild=a.guild)
    response = await client.patch(
        _url(a.guild.id, f"/{subscription_id}"),
        json={"active": False},
        headers=b.headers,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "WEBHOOK_SUBSCRIPTION_NOT_FOUND"


async def test_a_guild_admin_may_rewrite_any_of_them(client, acting_user):
    a = await acting_user(guild_role=GuildRole.member)
    with _mock_public_dns():
        created = await client.post(_url(a.guild.id), json=_body(), headers=a.headers)
    subscription_id = created.json()["id"]

    admin = await acting_user(guild_role=GuildRole.admin, guild=a.guild)
    response = await client.patch(
        _url(a.guild.id, f"/{subscription_id}"),
        json={"active": False},
        headers=admin.headers,
    )

    assert response.status_code == 200
    assert response.json()["active"] is False


async def test_a_subscription_in_another_guild_is_not_found(client, acting_user):
    a = await acting_user(guild_role=GuildRole.admin)
    with _mock_public_dns():
        created = await client.post(_url(a.guild.id), json=_body(), headers=a.headers)
    subscription_id = created.json()["id"]

    other = await acting_user(guild_role=GuildRole.admin)
    response = await client.delete(
        _url(other.guild.id, f"/{subscription_id}"), headers=other.headers
    )

    assert response.status_code == 404


async def test_a_private_target_url_is_refused(client, acting_user):
    a = await acting_user(guild_role=GuildRole.member)

    response = await client.post(
        _url(a.guild.id),
        json=_body(target_url="https://127.0.0.1/hook"),
        headers=a.headers,
    )

    assert response.status_code == 400
    assert response.json()["detail"] in {
        "WEBHOOK_PRIVATE_TARGET_URL",
        "WEBHOOK_INVALID_TARGET_URL",
    }


async def test_the_per_member_cap_is_enforced(client, acting_user, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "WEBHOOK_MAX_SUBSCRIPTIONS_PER_MEMBER", 1)
    a = await acting_user(guild_role=GuildRole.member)

    with _mock_public_dns():
        first = await client.post(_url(a.guild.id), json=_body(), headers=a.headers)
        assert first.status_code == 201
        second = await client.post(
            _url(a.guild.id),
            json=_body(target_url=f"https://{_WEBHOOK_HOST}/other"),
            headers=a.headers,
        )

    assert second.status_code == 409
    assert second.json()["detail"] == "WEBHOOK_TOO_MANY_SUBSCRIPTIONS"


async def test_a_member_never_sees_another_members_subscription(client, acting_user):
    """A target URL is a credential — receivers routinely carry their secret in
    the path or query — so the row is own-row scoped, like guild_app_subjects.
    RLS decides this, not a filter in the listing code."""
    a = await acting_user(guild_role=GuildRole.member)
    with _mock_public_dns():
        created = await client.post(_url(a.guild.id), json=_body(), headers=a.headers)
    assert created.status_code == 201

    b = await acting_user(guild_role=GuildRole.member, guild=a.guild)
    listing = await client.get(_url(a.guild.id), headers=b.headers)

    assert listing.status_code == 200
    assert listing.json() == [], (
        "another member's subscription was listed, disclosing its target URL"
    )


async def test_a_guild_admin_still_sees_them(client, acting_user):
    a = await acting_user(guild_role=GuildRole.member)
    with _mock_public_dns():
        await client.post(_url(a.guild.id), json=_body(), headers=a.headers)

    admin = await acting_user(guild_role=GuildRole.admin, guild=a.guild)
    listing = await client.get(_url(a.guild.id), headers=admin.headers)

    assert listing.status_code == 200
    assert len(listing.json()) == 1


async def test_a_url_carrying_credentials_is_refused(client, acting_user):
    a = await acting_user(guild_role=GuildRole.member)

    with _mock_public_dns():
        response = await client.post(
            _url(a.guild.id),
            json=_body(target_url=f"https://user:pw@{_WEBHOOK_HOST}/in"),
            headers=a.headers,
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "WEBHOOK_INVALID_TARGET_URL"


async def test_a_fields_only_update_is_accepted(client, acting_user):
    """Validation judges the row the patch produces, not the patch alone —
    otherwise a fields-only change has no event types to check against and a
    valid narrowing is rejected."""
    a = await acting_user(guild_role=GuildRole.member)
    with _mock_public_dns():
        created = await client.post(
            _url(a.guild.id),
            json=_body(event_types=["tasks.updated"]),
            headers=a.headers,
        )
    subscription_id = created.json()["id"]

    response = await client.patch(
        _url(a.guild.id, f"/{subscription_id}"),
        json={"fields": ["task_status_id"]},
        headers=a.headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["fields"] == ["task_status_id"]


async def test_narrowing_events_rechecks_the_stored_fields(client, acting_user):
    """The other direction: changing only event_types must re-check the fields
    already stored, or a filter that can never match survives the narrowing."""
    a = await acting_user(guild_role=GuildRole.member)
    with _mock_public_dns():
        created = await client.post(
            _url(a.guild.id),
            json=_body(event_types=["tasks.updated"], fields=["task_status_id"]),
            headers=a.headers,
        )
    subscription_id = created.json()["id"]

    response = await client.patch(
        _url(a.guild.id, f"/{subscription_id}"),
        json={"event_types": ["documents.updated"]},
        headers=a.headers,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "WEBHOOK_UNKNOWN_FIELD"
