"""Integration tests for the webhook subscription endpoints.

Three properties, layered:

* **Who may call at all** — delivery targets belong to the configured
  automation delegate, so every route requires the delegation credential,
  and a deployment with no delegate configured refuses outright.
* **Which of the delegate's users may rewrite a given row** — the acting
  user (the workflow owner the delegation names) must be the creator, or a
  guild admin.
* **Where a target may point** — the SSRF checks on ``target_url``.

The delegation JWTs here are minted the same way as in
``auto_delegation_test.py`` / ``advanced_tool_run_test.py``: a per-module
RSA keypair whose public half is monkeypatched into settings, and one fresh
``jti`` per request (delegation tokens are one-shot).
"""

from __future__ import annotations

import secrets
import socket
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import AsyncClient

from app.core import config as config_module
from app.models.platform.guild import GuildRole
from app.testing import Actor

_WEBHOOK_HOST = "hooks.example.com"
# A public unicast IPv4 (example.com) with a real stream socket type/proto, so
# constructing a socket from the tuple is valid.
_FAKE_INFOS = [
    (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 0))
]

_keypair = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_PEM = _keypair.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()
_PUBLIC_PEM = (
    _keypair.public_key()
    .public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    .decode()
)


@pytest.fixture(autouse=True)
def _enable_delegation(monkeypatch):
    """Configure an automation delegate for the duration of each test here.

    Without it every route answers 503 — which is its own test below, not the
    baseline the rest of the file is written against.
    """
    monkeypatch.setattr(
        config_module.settings, "AUTO_DELEGATION_PUBLIC_KEY_PEM", _PUBLIC_PEM
    )


def _delegation_headers(*, user_id: int, guild_id: int) -> dict[str, str]:
    """Mint a fresh (one-shot) delegation JWT for the user + guild."""
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "jti": secrets.token_hex(8),
            "sub": str(user_id),
            "aud": "initiative:auto-delegation",
            "iss": "initiative-auto",
            "iat": int(now.timestamp()),
            "exp": now + timedelta(seconds=900),
            "guild_id": guild_id,
        },
        _PRIVATE_PEM,
        algorithm="RS256",
    )
    return {"Authorization": f"Bearer {token}"}


def _as_delegate(actor: Actor) -> dict[str, str]:
    """Delegation headers acting as ``actor`` inside ``actor``'s guild."""
    return _delegation_headers(user_id=actor.user.id, guild_id=actor.guild.id)


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


async def _authed_post(client: AsyncClient, actor: Actor, body: dict):
    """Create a subscription as the delegate, acting for ``actor``."""
    return await client.post(
        actor.g("/auto/subscriptions"), json=body, headers=_as_delegate(actor)
    )


def _subscription_body(**overrides) -> dict:
    return {
        "target_url": "https://hooks.example.com/in",
        "event_types": ["task.created"],
        **overrides,
    }


# ── The delegate gate ─────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/auto/subscriptions", _subscription_body()),
        ("get", "/auto/subscriptions", None),
        ("patch", "/auto/subscriptions/1", {"active": False}),
        ("delete", "/auto/subscriptions/1", None),
    ],
)
async def test_ordinary_caller_is_refused_on_every_route(
    client: AsyncClient, acting_user, method: str, path: str, body: dict | None
):
    """A guild admin — the most privileged ordinary caller — is still not the
    automation delegate, on any of the four routes.

    The ids in the mutation paths are deliberately nonexistent: the gate
    decides before the row is ever looked up, so the answer is 403 rather
    than 404.
    """
    a = await acting_user(guild_role=GuildRole.admin)

    kwargs: dict = {"headers": a.headers}
    if body is not None:
        kwargs["json"] = body
    with _mock_public_dns():
        response = await getattr(client, method)(a.g(path), **kwargs)

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "AUTOMATION_DELEGATE_REQUIRED"


@pytest.mark.integration
@pytest.mark.parametrize(
    ("method", "path"),
    [("post", "/auto/subscriptions"), ("get", "/auto/subscriptions")],
)
async def test_no_delegate_configured_refuses_with_503(
    client: AsyncClient, acting_user, monkeypatch, method: str, path: str
):
    """A deployment with no automation delegate has nothing that may own a
    delivery target, so the routes are unavailable rather than forbidden —
    503, which resolves itself once an operator configures a delegate."""
    monkeypatch.setattr(config_module.settings, "AUTO_DELEGATION_PUBLIC_KEY_PEM", None)
    a = await acting_user(guild_role=GuildRole.admin)

    kwargs: dict = {"headers": a.headers}
    if method == "post":
        kwargs["json"] = _subscription_body()
    with _mock_public_dns():
        response = await getattr(client, method)(a.g(path), **kwargs)

    assert response.status_code == 503, response.text
    assert response.json()["detail"] == "AUTOMATION_DELEGATE_NOT_CONFIGURED"


@pytest.mark.integration
async def test_delegation_token_for_another_guild_is_refused(
    client: AsyncClient, acting_user
):
    """A delegation token is minted for exactly one guild, so a token naming
    one guild can't manage another guild's delivery targets."""
    a = await acting_user(guild_role=GuildRole.admin)
    b = await acting_user(guild_role=GuildRole.admin)
    # The token names b's guild; the path names a's, where the user is admin.
    other_guild_token = _delegation_headers(user_id=a.user.id, guild_id=b.guild.id)

    response = await client.get(a.g("/auto/subscriptions"), headers=other_guild_token)
    assert response.status_code == 403
    assert response.json()["detail"] == "GUILD_ACCESS_DENIED"


@pytest.mark.integration
async def test_delegate_can_use_every_route(client: AsyncClient, acting_user):
    """The happy path across all four routes on one subscription: the delegate
    creates, lists, patches and deletes it."""
    a = await acting_user(guild_role=GuildRole.member)

    with _mock_public_dns():
        created = await _authed_post(client, a, _subscription_body())
    assert created.status_code == 201, created.text
    sub_id = created.json()["id"]

    listed = await client.get(a.g("/auto/subscriptions"), headers=_as_delegate(a))
    assert listed.status_code == 200, listed.text
    assert [row["id"] for row in listed.json()] == [sub_id]
    # The one-time secret is never echoed on a read.
    assert "hmac_secret" not in listed.json()[0]

    patched = await client.patch(
        a.g(f"/auto/subscriptions/{sub_id}"),
        json={"active": False},
        headers=_as_delegate(a),
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["active"] is False

    deleted = await client.delete(
        a.g(f"/auto/subscriptions/{sub_id}"), headers=_as_delegate(a)
    )
    assert deleted.status_code == 204, deleted.text


# ── Target URL policy ─────────────────────────────────────────────────


@pytest.mark.integration
async def test_create_rejects_loopback_target_url(client: AsyncClient, acting_user):
    """Registering a target that resolves to loopback must 400."""
    a = await acting_user(guild_role=GuildRole.admin)

    response = await _authed_post(
        client, a, _subscription_body(target_url="https://127.0.0.1/hook")
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "WEBHOOK_PRIVATE_TARGET_URL"


@pytest.mark.integration
async def test_create_rejects_link_local_target(client: AsyncClient, acting_user):
    """A link-local address must be rejected at registration."""
    a = await acting_user(guild_role=GuildRole.admin)

    response = await _authed_post(
        client, a, _subscription_body(target_url="https://169.254.169.254/")
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "WEBHOOK_PRIVATE_TARGET_URL"


@pytest.mark.integration
async def test_create_rejects_plain_http(client: AsyncClient, acting_user):
    """Plain http:// is rejected with the structural-invalid code so
    the operator sees a different error than for a private-IP target."""
    a = await acting_user(guild_role=GuildRole.admin)

    response = await _authed_post(
        client, a, _subscription_body(target_url="http://hooks.example.com/in")
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

    with _mock_public_dns():
        response = await _authed_post(client, a, _subscription_body())
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["target_url"] == "https://hooks.example.com/in"
    # The delegation names a real user, so the row still records an owner.
    assert body["created_by_user_id"] == a.user.id
    assert "hmac_secret" in body  # one-time payload includes the secret


@pytest.mark.integration
async def test_patch_revalidates_target_url(client: AsyncClient, acting_user):
    """Rewriting the target re-runs the same checks as registering one."""
    a = await acting_user(guild_role=GuildRole.admin)

    with _mock_public_dns():
        created = await _authed_post(client, a, _subscription_body())
    assert created.status_code == 201, created.text

    response = await client.patch(
        a.g(f"/auto/subscriptions/{created.json()['id']}"),
        json={"target_url": "https://127.0.0.1/hook"},
        headers=_as_delegate(a),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "WEBHOOK_PRIVATE_TARGET_URL"


# ── Ownership, on the delegated path ──────────────────────────────────


@pytest.mark.integration
async def test_non_owner_member_cannot_delete(client: AsyncClient, acting_user):
    """The delegate acts as a real user, so the creator-or-admin rule still
    applies between two of its workflows: a member who didn't create the
    subscription can't delete it, even over the delegation credential."""
    creator = await acting_user(guild_role=GuildRole.admin)
    other = await acting_user(guild_role=GuildRole.member, guild=creator.guild)

    with _mock_public_dns():
        created = await _authed_post(client, creator, _subscription_body())
    assert created.status_code == 201
    sub_id = created.json()["id"]

    response = await client.delete(
        other.g(f"/auto/subscriptions/{sub_id}"),
        headers=_as_delegate(other),
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "WEBHOOK_SUBSCRIPTION_NOT_OWNER"


@pytest.mark.integration
async def test_non_owner_member_cannot_update(client: AsyncClient, acting_user):
    """Same authority check on PATCH — flipping ``active`` or rewriting
    ``target_url`` are both mutations."""
    creator = await acting_user(guild_role=GuildRole.admin)
    other = await acting_user(guild_role=GuildRole.member, guild=creator.guild)

    with _mock_public_dns():
        created = await _authed_post(client, creator, _subscription_body())
    assert created.status_code == 201
    sub_id = created.json()["id"]

    response = await client.patch(
        other.g(f"/auto/subscriptions/{sub_id}"),
        json={"active": False},
        headers=_as_delegate(other),
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

    with _mock_public_dns():
        created = await _authed_post(client, creator, _subscription_body())
    assert created.status_code == 201
    sub_id = created.json()["id"]

    response = await client.delete(
        admin.g(f"/auto/subscriptions/{sub_id}"), headers=_as_delegate(admin)
    )
    assert response.status_code == 204


@pytest.mark.integration
async def test_creator_can_update_own_subscription(client: AsyncClient, acting_user):
    """The happy path: the creator can mutate their own subscription."""
    a = await acting_user(guild_role=GuildRole.member)

    with _mock_public_dns():
        created = await _authed_post(client, a, _subscription_body())
    assert created.status_code == 201
    sub_id = created.json()["id"]

    response = await client.patch(
        a.g(f"/auto/subscriptions/{sub_id}"),
        json={"active": False},
        headers=_as_delegate(a),
    )
    assert response.status_code == 200
    assert response.json()["active"] is False
