"""Unit tests for the webhook dispatcher.

These cover the cryptographic contract — given a known secret and
known body, the signature is deterministic and verifies — plus the
matching rules that decide which subscriptions get a given event.
HTTP delivery is mocked; we don't need a real socket to assert that
the right URL was called with the right headers and body.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.models.webhook_subscription import WebhookSubscription
from app.services.webhook_dispatcher import _sign, dispatch_event


def _verify_signature(secret: str, timestamp: str, body: bytes, signature: str) -> bool:
    """What the receiver does on its side. Re-implementing here so the
    tests don't depend on shared receiver code."""
    expected = hmac.new(secret.encode("utf-8"), digestmod=hashlib.sha256)
    expected.update(timestamp.encode("utf-8"))
    expected.update(b".")
    expected.update(body)
    return hmac.compare_digest(f"sha256={expected.hexdigest()}", signature)


@pytest.mark.unit
def test_sign_is_deterministic_for_same_inputs():
    """Two signatures over the same (secret, timestamp, body) must
    match — load-bearing for the receiver's verification."""
    sig1 = _sign("topsecret", "1748000000", b'{"a":1}')
    sig2 = _sign("topsecret", "1748000000", b'{"a":1}')
    assert sig1 == sig2
    assert sig1.startswith("sha256=")


@pytest.mark.unit
def test_sign_differs_when_body_changes():
    """Even a single-byte body change must produce a different signature.
    If this fails, an attacker could replay a captured envelope with
    edits."""
    sig1 = _sign("topsecret", "1748000000", b'{"a":1}')
    sig2 = _sign("topsecret", "1748000000", b'{"a":2}')
    assert sig1 != sig2


@pytest.mark.unit
def test_sign_differs_when_timestamp_changes():
    """Timestamp is part of the signed input so a valid (body, sig) pair
    captured at T can't be re-presented at T+ seconds later — the
    receiver re-computes with the *new* timestamp and the signature
    won't match."""
    sig1 = _sign("topsecret", "1748000000", b'{"a":1}')
    sig2 = _sign("topsecret", "1748000001", b'{"a":1}')
    assert sig1 != sig2


@pytest.mark.unit
def test_sign_round_trips_through_verifier():
    """Signing then verifying must succeed for the same inputs."""
    secret = "shared-with-receiver"
    timestamp = str(int(datetime.now(timezone.utc).timestamp()))
    body = json.dumps({"event_type": "task.created"}).encode()

    sig = _sign(secret, timestamp, body)
    assert _verify_signature(secret, timestamp, body, sig)


@pytest.mark.unit
def test_verifier_rejects_wrong_secret():
    """A receiver with the wrong secret must NOT verify successfully —
    that's the entire point of HMAC."""
    timestamp = "1748000000"
    body = b'{"event_type":"task.created"}'

    sig = _sign("real-secret", timestamp, body)
    assert not _verify_signature("attacker-guess", timestamp, body, sig)


# ── Dispatch matching rules ───────────────────────────────────────────


async def _make_subscription(
    session,
    *,
    guild,
    user,
    target_url: str,
    event_types: list[str],
    initiative_id: int | None = None,
    active: bool = True,
) -> WebhookSubscription:
    """Helper: create a sub bound to a real guild+user so FKs hold."""
    now = datetime.now(timezone.utc)
    sub = WebhookSubscription(
        guild_id=guild.id,
        initiative_id=initiative_id,
        workflow_id=None,
        created_by_user_id=user.id,
        target_url=target_url,
        hmac_secret="test-secret",
        event_types=event_types,
        active=active,
        created_at=now,
        updated_at=now,
    )
    session.add(sub)
    await session.commit()
    return sub


@pytest.mark.integration
async def test_dispatch_skips_when_no_subscribers(session):
    """No subscriptions, no work — and crucially no errors."""
    from app.testing.factories import create_guild

    guild = await create_guild(session)
    with patch("app.services.webhook_dispatcher._deliver", new=AsyncMock()) as mock_deliver:
        await dispatch_event(
            session,
            event_type="task.created",
            guild_id=guild.id,
            initiative_id=None,
            payload={"id": 1},
        )
        assert mock_deliver.await_count == 0


@pytest.mark.integration
async def test_dispatch_matches_only_active_subscriptions(session):
    """Inactive subscriptions must NOT receive deliveries."""
    from app.testing.factories import create_guild, create_user

    user = await create_user(session, email="dispatcher-active@example.com")
    guild = await create_guild(session)
    await _make_subscription(
        session, guild=guild, user=user,
        target_url="https://active.example.com/hook",
        event_types=["task.created"], active=True,
    )
    await _make_subscription(
        session, guild=guild, user=user,
        target_url="https://inactive.example.com/hook",
        event_types=["task.created"], active=False,
    )

    delivered_to: list[str] = []

    async def fake_deliver(*, target_url: str, secret: str, envelope: dict) -> None:
        delivered_to.append(target_url)

    with patch("app.services.webhook_dispatcher._deliver", new=fake_deliver):
        await dispatch_event(
            session, event_type="task.created", guild_id=guild.id, payload={"id": 1},
        )

    assert delivered_to == ["https://active.example.com/hook"]


@pytest.mark.integration
async def test_dispatch_filters_by_event_type(session):
    """A sub for task.updated must NOT receive task.created events."""
    from app.testing.factories import create_guild, create_user

    user = await create_user(session, email="dispatcher-filter@example.com")
    guild = await create_guild(session)
    await _make_subscription(
        session, guild=guild, user=user,
        target_url="https://updated.example.com/hook",
        event_types=["task.updated"],
    )

    with patch("app.services.webhook_dispatcher._deliver", new=AsyncMock()) as mock_deliver:
        await dispatch_event(
            session, event_type="task.created", guild_id=guild.id, payload={"id": 1},
        )
        assert mock_deliver.await_count == 0


@pytest.mark.integration
async def test_dispatch_initiative_scope_matches_correctly(session):
    """An initiative-scoped subscription receives events in its
    initiative; a guild-scoped one (initiative_id NULL) gets ALL guild
    events; cross-initiative subs see nothing for events outside their
    scope."""
    from app.testing.factories import create_guild, create_initiative, create_user

    user = await create_user(session, email="dispatcher-scope@example.com")
    guild = await create_guild(session, creator=user)
    init_a = await create_initiative(session, guild, user, name="A")
    init_b = await create_initiative(session, guild, user, name="B")

    await _make_subscription(
        session, guild=guild, user=user,
        target_url="https://guild-wide.example.com",
        event_types=["task.created"], initiative_id=None,
    )
    await _make_subscription(
        session, guild=guild, user=user,
        target_url="https://init-a.example.com",
        event_types=["task.created"], initiative_id=init_a.id,
    )
    await _make_subscription(
        session, guild=guild, user=user,
        target_url="https://init-b.example.com",
        event_types=["task.created"], initiative_id=init_b.id,
    )

    delivered_to: list[str] = []

    async def fake_deliver(*, target_url: str, secret: str, envelope: dict) -> None:
        delivered_to.append(target_url)

    with patch("app.services.webhook_dispatcher._deliver", new=fake_deliver):
        await dispatch_event(
            session, event_type="task.created", guild_id=guild.id,
            initiative_id=init_a.id, payload={"id": 1},
        )

    assert sorted(delivered_to) == [
        "https://guild-wide.example.com",
        "https://init-a.example.com",
    ]


@pytest.mark.integration
async def test_each_subscription_gets_unique_event_id(session):
    """A single dispatch fan-out must give each subscriber its own
    ``event_id``. If they all shared one, a receiver dedup-ing on the
    header (which is the documented pattern) would silently drop
    legitimate deliveries fanned out to multiple subscribers, and any
    future per-target retry would collide across subscriptions."""
    from app.testing.factories import create_guild, create_user

    user = await create_user(session, email="dispatcher-eventid@example.com")
    guild = await create_guild(session, creator=user)
    await _make_subscription(
        session, guild=guild, user=user,
        target_url="https://a.example.com", event_types=["task.created"],
    )
    await _make_subscription(
        session, guild=guild, user=user,
        target_url="https://b.example.com", event_types=["task.created"],
    )

    seen_event_ids: list[str] = []

    async def fake_deliver(*, target_url: str, secret: str, envelope: dict) -> None:
        seen_event_ids.append(envelope["event_id"])

    with patch("app.services.webhook_dispatcher._deliver", new=fake_deliver):
        await dispatch_event(
            session, event_type="task.created", guild_id=guild.id, payload={"id": 1},
        )

    assert len(seen_event_ids) == 2
    assert len(set(seen_event_ids)) == 2, "event_id must differ per delivery"


@pytest.mark.integration
async def test_dispatch_does_not_cross_guilds(session):
    """A subscription in guild B must NOT receive events in guild A —
    tenant isolation, the most load-bearing property."""
    from app.testing.factories import create_guild, create_user

    user = await create_user(session, email="dispatcher-cross-guild@example.com")
    guild_a = await create_guild(session, name="A")
    guild_b = await create_guild(session, name="B")
    await _make_subscription(
        session, guild=guild_b, user=user,
        target_url="https://other-guild.example.com",
        event_types=["task.created"],
    )

    with patch("app.services.webhook_dispatcher._deliver", new=AsyncMock()) as mock_deliver:
        await dispatch_event(
            session, event_type="task.created", guild_id=guild_a.id, payload={"id": 1},
        )
        assert mock_deliver.await_count == 0
