"""The membership-change ping to billing (write-boundary plan D5).

Pinned properties:

* FOSS gating — with billing unconfigured (the self-host default) the code
  path is a strict no-op: no task, no outbound call;
* one ping per membership change, dispatched by the membership services;
* the payload carries the guild id and a fresh event id ONLY — no member
  data, no PII, and deliberately no member count (billing re-reads the
  authoritative headcount via its signed endpoint);
* the signature binds method/path/timestamp/body exactly like the inbound
  envelope, keyed by the shared HMAC secret;
* a failing billing service never surfaces into the join/leave path.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json

import httpx
import pytest

from app.core import config as config_module
from app.services.platform import billing_ping
from app.services.platform import guilds as guilds_service
from app.testing import create_guild, create_user, route_session_to_guild

pytestmark = pytest.mark.integration

_SECRET = "ping-test-secret"


@pytest.fixture
def billing_configured(monkeypatch):
    monkeypatch.setattr(
        config_module.settings, "BILLING_SERVICE_URL", "https://billing.internal"
    )
    monkeypatch.setattr(config_module.settings, "BILLING_HMAC_SECRET", _SECRET)


@pytest.fixture
def sent_pings(monkeypatch):
    """Capture dispatched pings without any network."""
    calls: list[int] = []

    async def _capture(guild_id: int) -> None:
        calls.append(guild_id)

    monkeypatch.setattr(billing_ping, "_send_membership_ping", _capture)
    return calls


async def _drain_pings():
    # Let fire-and-forget tasks run to completion.
    for _ in range(3):
        await asyncio.sleep(0)


def test_disabled_by_default():
    assert billing_ping.billing_ping_enabled() is False


async def test_unconfigured_is_a_strict_noop(sent_pings):
    billing_ping.notify_membership_changed(123)
    await _drain_pings()
    assert sent_pings == []


async def test_configured_dispatches_one_ping(billing_configured, sent_pings):
    billing_ping.notify_membership_changed(123)
    await _drain_pings()
    assert sent_pings == [123]


def test_payload_has_no_pii_and_verifiable_signature(billing_configured):
    url, body, headers = billing_ping.build_membership_ping(42)
    assert url == "https://billing.internal/api/v1/pings/membership"

    payload = json.loads(body)
    # guild id + event id ONLY: no emails, names, user ids, or member counts.
    assert set(payload) == {"guild_id", "event_id"}
    assert payload["guild_id"] == 42
    assert payload["event_id"]

    message = "\n".join(
        [
            "POST",
            "/api/v1/pings/membership",
            headers["X-Billing-Timestamp"],
            hashlib.sha256(body).hexdigest(),
        ]
    ).encode()
    expected = hmac.new(_SECRET.encode(), message, hashlib.sha256).hexdigest()
    assert headers["X-Billing-Signature"] == expected


def test_event_ids_are_unique_per_ping(billing_configured):
    ids = {
        json.loads(billing_ping.build_membership_ping(1)[1])["event_id"]
        for _ in range(5)
    }
    assert len(ids) == 5


async def test_send_failure_never_raises(billing_configured, monkeypatch):
    class _DownClient:
        def __init__(self, *a, **k): ...

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            raise httpx.ConnectError("billing is down")

    monkeypatch.setattr(billing_ping.httpx, "AsyncClient", _DownClient)
    # Must not raise — a dead billing service cannot fail a join.
    await billing_ping._send_membership_ping(7)


async def test_membership_insert_fires_exactly_one_ping(
    session, billing_configured, sent_pings
):
    guild = await create_guild(session)
    user = await create_user(session, email="ping-join@example.com")

    await guilds_service.ensure_membership(session, guild_id=guild.id, user_id=user.id)
    await _drain_pings()
    assert sent_pings == [guild.id]

    # Re-join / role refresh is not a membership change: no second ping.
    await guilds_service.ensure_membership(session, guild_id=guild.id, user_id=user.id)
    await _drain_pings()
    assert sent_pings == [guild.id]

    # Removal also cleans the guild's initiative memberships (tenant schema),
    # so the session must be routed to the guild first.
    await route_session_to_guild(session, guild.id)
    await guilds_service.remove_user_from_guild(
        session, guild_id=guild.id, user_id=user.id
    )
    await _drain_pings()
    assert sent_pings == [guild.id, guild.id]
    await session.rollback()


async def test_noop_removal_does_not_ping(session, billing_configured, sent_pings):
    """Removing a user who isn't a member deletes nothing, so — like a
    re-join — it must not nudge billing."""
    guild = await create_guild(session)
    stranger = await create_user(session, email="ping-stranger@example.com")

    await route_session_to_guild(session, guild.id)
    await guilds_service.remove_user_from_guild(
        session, guild_id=guild.id, user_id=stranger.id
    )
    await _drain_pings()
    assert sent_pings == []
    await session.rollback()
