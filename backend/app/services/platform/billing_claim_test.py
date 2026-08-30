"""The server-to-server guild claim to billing.

Pinned properties:

* FOSS gating — with billing unconfigured, or with no handoff signing key, the
  code path is a strict no-op: no task, no outbound call;
* the payload is one signed handoff and nothing else, carrying the user id and
  guild id inside the token;
* the claim names the guild's owner and its admin role;
* a failing billing service never surfaces into guild creation.
"""

from __future__ import annotations

import asyncio

import httpx
import jwt
import pytest

from conftest import HANDOFF_TEST_PRIVATE_PEM, HANDOFF_TEST_PUBLIC_PEM

from app.core import config as config_module
from app.core.security import BILLING_PORTAL_AUDIENCE
from app.services.platform import billing_claim

pytestmark = pytest.mark.integration

_URL = "https://billing.internal"


@pytest.fixture
def billing_configured(monkeypatch):
    """Reachable billing + the suite's handoff keypair (conftest configures it)."""
    monkeypatch.setattr(config_module.settings, "BILLING_SERVICE_URL", _URL)
    monkeypatch.setattr(
        config_module.settings,
        "HANDOFF_SIGNING_PRIVATE_KEY_PEM",
        HANDOFF_TEST_PRIVATE_PEM,
    )


@pytest.fixture
def sent_claims(monkeypatch):
    """Capture dispatched claims without any network."""
    calls: list[tuple[int, int]] = []

    async def _capture(user_id: int, guild_id: int) -> None:
        calls.append((user_id, guild_id))

    monkeypatch.setattr(billing_claim, "_send_claim", _capture)
    return calls


async def _drain():
    for _ in range(3):
        await asyncio.sleep(0)


def test_disabled_by_default():
    assert billing_claim.billing_claim_enabled() is False


async def test_unconfigured_is_a_strict_noop(sent_claims):
    billing_claim.claim_new_guild(user_id=1, guild_id=2)
    await _drain()
    assert sent_claims == []


async def test_a_reachable_billing_without_a_signing_key_still_sends_nothing(
    monkeypatch, sent_claims
):
    """The handoff is the credential, so signing configuration gates the send
    the same way reachability does."""
    monkeypatch.setattr(config_module.settings, "BILLING_SERVICE_URL", _URL)
    monkeypatch.setattr(config_module.settings, "HANDOFF_SIGNING_PRIVATE_KEY_PEM", "")
    billing_claim.claim_new_guild(user_id=1, guild_id=2)
    await _drain()
    assert sent_claims == []


async def test_configured_dispatches_one_claim(billing_configured, sent_claims):
    billing_claim.claim_new_guild(user_id=9, guild_id=77)
    await _drain()
    assert sent_claims == [(9, 77)]


async def test_the_request_carries_a_signed_handoff_and_no_bare_identity(
    billing_configured, monkeypatch
):
    seen: dict = {}

    class _Capture:
        def __init__(self, *a, **k): ...

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, **k):
            seen["url"] = url
            seen["json"] = json
            return httpx.Response(202)

    monkeypatch.setattr(billing_claim.httpx, "AsyncClient", _Capture)
    await billing_claim._send_claim(9, 77)

    assert seen["url"] == f"{_URL}/api/v1/guilds/claim"
    # The token is the whole payload: no user_id or guild_id in the clear.
    assert set(seen["json"]) == {"handoff_token"}

    claims = jwt.decode(
        seen["json"]["handoff_token"],
        HANDOFF_TEST_PUBLIC_PEM,
        algorithms=["RS256"],
        audience=BILLING_PORTAL_AUDIENCE,
    )
    assert claims["sub"] == "9"
    assert claims["guild_id"] == 77
    assert claims["guild_role"] == "admin"
    assert claims["iss"] == "initiative"


async def test_send_failure_never_raises(billing_configured, monkeypatch):
    class _DownClient:
        def __init__(self, *a, **k): ...

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            raise httpx.ConnectError("billing is down")

    monkeypatch.setattr(billing_claim.httpx, "AsyncClient", _DownClient)
    # Returns normally: an unreachable service stays inside the send.
    await billing_claim._send_claim(1, 2)


# --- the wiring: where a guild is actually born ---------------------------


async def test_creating_a_guild_claims_it_for_its_owner(
    client, session, billing_configured, sent_claims
):
    """Creation itself dispatches the claim, with no browser in the loop."""
    from app.testing import create_user, get_auth_headers

    user = await create_user(session, email="claim-create@example.com")
    response = await client.post(
        "/api/v1/guilds/",
        headers=get_auth_headers(user),
        json={"name": "Claimed Guild"},
    )
    assert response.status_code == 201
    await _drain()

    assert sent_claims == [(user.id, response.json()["id"])]


async def test_an_unconfigured_deployment_creates_guilds_without_claiming(
    client, session, sent_claims
):
    """Self-hosting does not bill, so there is nobody to tell — and guild
    creation must not notice the difference."""
    from app.testing import create_user, get_auth_headers

    user = await create_user(session, email="claim-foss@example.com")
    response = await client.post(
        "/api/v1/guilds/",
        headers=get_auth_headers(user),
        json={"name": "Self-Hosted Guild"},
    )
    assert response.status_code == 201
    await _drain()
    assert sent_claims == []


async def test_registration_claims_the_guild_it_creates(
    client, billing_configured, sent_claims
):
    """Registration seeds the new account a guild, and claims that one too."""
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "claim-register@example.com",
            "username": "claimregister",
            "full_name": "Claim Register",
            "password": "securepassword123",
        },
    )
    assert response.status_code == 201
    await _drain()

    assert len(sent_claims) == 1
    claimed_user, claimed_guild = sent_claims[0]
    assert claimed_user == response.json()["id"]
    assert claimed_guild > 0
