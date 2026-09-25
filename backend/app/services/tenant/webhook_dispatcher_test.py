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


from app.testing.schema_harness import route_session_to_guild
from app.models.tenant.webhook_subscription import WebhookSubscription
from app.services.tenant.webhook_dispatcher import _sign, dispatch_event


def _verify_signature(secret: str, timestamp: str, body: bytes, signature: str) -> bool:
    """What the receiver does on its side. Re-implementing here so the
    tests don't depend on shared receiver code."""
    expected = hmac.new(secret.encode("utf-8"), digestmod=hashlib.sha256)
    expected.update(timestamp.encode("utf-8"))
    expected.update(b".")
    expected.update(body)
    return hmac.compare_digest(f"sha256={expected.hexdigest()}", signature)


def test_sign_is_deterministic_for_same_inputs():
    """Two signatures over the same (secret, timestamp, body) must
    match — load-bearing for the receiver's verification."""
    sig1 = _sign("topsecret", "1748000000", b'{"a":1}')
    sig2 = _sign("topsecret", "1748000000", b'{"a":1}')
    assert sig1 == sig2
    assert sig1.startswith("sha256=")


def test_sign_differs_when_body_changes():
    """Even a single-byte body change must produce a different signature.
    If this fails, an attacker could replay a captured envelope with
    edits."""
    sig1 = _sign("topsecret", "1748000000", b'{"a":1}')
    sig2 = _sign("topsecret", "1748000000", b'{"a":2}')
    assert sig1 != sig2


def test_sign_differs_when_timestamp_changes():
    """Timestamp is part of the signed input so a valid (body, sig) pair
    captured at T can't be re-presented at T+ seconds later — the
    receiver re-computes with the *new* timestamp and the signature
    won't match."""
    sig1 = _sign("topsecret", "1748000000", b'{"a":1}')
    sig2 = _sign("topsecret", "1748000001", b'{"a":1}')
    assert sig1 != sig2


def test_sign_round_trips_through_verifier():
    """Signing then verifying must succeed for the same inputs."""
    secret = "shared-with-receiver"
    timestamp = str(int(datetime.now(timezone.utc).timestamp()))
    body = json.dumps({"event_type": "task.created"}).encode()

    sig = _sign(secret, timestamp, body)
    assert _verify_signature(secret, timestamp, body, sig)


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
    app_install_id: int | None = None,
) -> WebhookSubscription:
    """Helper: create a sub bound to a real guild+user so FKs hold."""
    now = datetime.now(timezone.utc)
    sub = WebhookSubscription(
        initiative_id=initiative_id,
        created_by=user.id,
        app_install_id=app_install_id,
        target_url=target_url,
        hmac_secret="test-secret",
        event_types=event_types,
        active=active,
        created_at=now,
        updated_at=now,
    )
    await route_session_to_guild(session, guild.id)
    session.add(sub)
    await session.commit()
    return sub


async def test_dispatch_skips_when_no_subscribers(session):
    """No subscriptions, no work — and crucially no errors."""
    from app.testing import route_session_to_guild
    from app.testing.factories import create_guild

    guild = await create_guild(session)
    # Production callers pass a guild-routed session (webhook_subscriptions is
    # guild-scoped); mirror that — no tenant write here routes it implicitly.
    await route_session_to_guild(session, guild.id)
    with patch(
        "app.services.tenant.webhook_dispatcher.deliver", new=AsyncMock()
    ) as mock_deliver:
        await dispatch_event(
            session,
            event_type="task.created",
            guild_id=guild.id,
            initiative_id=None,
            payload={"id": 1},
        )
        assert mock_deliver.await_count == 0


async def test_dispatch_matches_only_active_subscriptions(session):
    """Inactive subscriptions must NOT receive deliveries."""
    from app.testing.factories import create_guild, create_user

    user = await create_user(session, email="dispatcher-active@example.com")
    guild = await create_guild(session)
    await _make_subscription(
        session,
        guild=guild,
        user=user,
        target_url="https://active.example.com/hook",
        event_types=["task.created"],
        active=True,
    )
    await _make_subscription(
        session,
        guild=guild,
        user=user,
        target_url="https://inactive.example.com/hook",
        event_types=["task.created"],
        active=False,
    )

    delivered_to: list[str] = []

    async def fake_deliver(*, target_url: str, secret: str, envelope: dict) -> bool:
        delivered_to.append(target_url)
        return True

    with patch("app.services.tenant.webhook_dispatcher.deliver", new=fake_deliver):
        await dispatch_event(
            session,
            event_type="task.created",
            guild_id=guild.id,
            payload={"id": 1},
        )

    assert delivered_to == ["https://active.example.com/hook"]


async def test_dispatch_filters_by_event_type(session):
    """A sub for task.updated must NOT receive task.created events."""
    from app.testing.factories import create_guild, create_user

    user = await create_user(session, email="dispatcher-filter@example.com")
    guild = await create_guild(session)
    await _make_subscription(
        session,
        guild=guild,
        user=user,
        target_url="https://updated.example.com/hook",
        event_types=["task.updated"],
    )

    with patch(
        "app.services.tenant.webhook_dispatcher.deliver", new=AsyncMock()
    ) as mock_deliver:
        await dispatch_event(
            session,
            event_type="task.created",
            guild_id=guild.id,
            payload={"id": 1},
        )
        assert mock_deliver.await_count == 0


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
        session,
        guild=guild,
        user=user,
        target_url="https://guild-wide.example.com",
        event_types=["task.created"],
        initiative_id=None,
    )
    await _make_subscription(
        session,
        guild=guild,
        user=user,
        target_url="https://init-a.example.com",
        event_types=["task.created"],
        initiative_id=init_a.id,
    )
    await _make_subscription(
        session,
        guild=guild,
        user=user,
        target_url="https://init-b.example.com",
        event_types=["task.created"],
        initiative_id=init_b.id,
    )

    delivered_to: list[str] = []

    async def fake_deliver(*, target_url: str, secret: str, envelope: dict) -> bool:
        delivered_to.append(target_url)
        return True

    with patch("app.services.tenant.webhook_dispatcher.deliver", new=fake_deliver):
        await dispatch_event(
            session,
            event_type="task.created",
            guild_id=guild.id,
            initiative_id=init_a.id,
            payload={"id": 1},
        )

    assert sorted(delivered_to) == [
        "https://guild-wide.example.com",
        "https://init-a.example.com",
    ]


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
        session,
        guild=guild,
        user=user,
        target_url="https://a.example.com",
        event_types=["task.created"],
    )
    await _make_subscription(
        session,
        guild=guild,
        user=user,
        target_url="https://b.example.com",
        event_types=["task.created"],
    )

    seen_event_ids: list[str] = []

    async def fake_deliver(*, target_url: str, secret: str, envelope: dict) -> bool:
        seen_event_ids.append(envelope["event_id"])
        return True

    with patch("app.services.tenant.webhook_dispatcher.deliver", new=fake_deliver):
        await dispatch_event(
            session,
            event_type="task.created",
            guild_id=guild.id,
            payload={"id": 1},
        )

    assert len(seen_event_ids) == 2
    assert len(set(seen_event_ids)) == 2, "event_id must differ per delivery"


async def test_dispatch_does_not_cross_guilds(session):
    """A subscription in guild B must NOT receive events in guild A —
    tenant isolation, the most load-bearing property."""
    from app.testing.factories import create_guild, create_user

    user = await create_user(session, email="dispatcher-cross-guild@example.com")
    guild_a = await create_guild(session, name="A")
    guild_b = await create_guild(session, name="B")
    await _make_subscription(
        session,
        guild=guild_b,
        user=user,
        target_url="https://other-guild.example.com",
        event_types=["task.created"],
    )

    # The real caller is a request routed into guild A; B's rows are in
    # another schema, and the dispatcher reads the one its session is on.
    await route_session_to_guild(session, guild_a.id)
    with patch(
        "app.services.tenant.webhook_dispatcher.deliver", new=AsyncMock()
    ) as mock_deliver:
        await dispatch_event(
            session,
            event_type="task.created",
            guild_id=guild_a.id,
            payload={"id": 1},
        )
        assert mock_deliver.await_count == 0


async def test_dispatch_delivers_to_a_matching_subscription(session):
    """The baseline: a matching subscription is delivered to."""
    from app.testing.factories import create_guild, create_user

    user = await create_user(session, email="dispatcher-configured@example.com")
    guild = await create_guild(session, creator=user)
    await _make_subscription(
        session,
        guild=guild,
        user=user,
        target_url="https://configured.example.com/hook",
        event_types=["task.created"],
    )

    delivered_to: list[str] = []

    async def fake_deliver(*, target_url: str, secret: str, envelope: dict) -> bool:
        delivered_to.append(target_url)
        return True

    with patch("app.services.tenant.webhook_dispatcher.deliver", new=fake_deliver):
        await dispatch_event(
            session,
            event_type="task.created",
            guild_id=guild.id,
            payload={"id": 1},
        )

    assert delivered_to == ["https://configured.example.com/hook"]


async def test_an_install_that_is_gone_is_delivered_to_by_nobody(session):
    """Uninstalling switches an app's subscriptions off, which is what stops
    deliveries promptly. This is what makes it true anyway.

    ``app_install_id`` carries no foreign key — the install and the
    subscription are both guild content, but nothing enforces the link — so the
    selector asks whether the install is still there rather than trusting that
    every path which removes one remembered to switch its subscriptions off.
    """
    from app.testing.factories import create_guild, create_user

    user = await create_user(session, email="dispatcher-install@example.com")
    guild = await create_guild(session)
    await _make_subscription(
        session,
        guild=guild,
        user=user,
        target_url="https://an-install-that-went.example.com/hook",
        event_types=["task.created"],
        active=True,
        # No guild_apps row: an install that is not there any more.
        app_install_id=987654,
    )
    await _make_subscription(
        session,
        guild=guild,
        user=user,
        target_url="https://a-member-of-this-guild.example.com/hook",
        event_types=["task.created"],
        active=True,
        app_install_id=None,
    )

    delivered_to: list[str] = []

    async def fake_deliver(*, target_url: str, secret: str, envelope: dict) -> bool:
        delivered_to.append(target_url)
        return True

    with patch("app.services.tenant.webhook_dispatcher.deliver", new=fake_deliver):
        await dispatch_event(
            session,
            event_type="task.created",
            guild_id=guild.id,
            payload={"id": 1},
        )

    assert delivered_to == ["https://a-member-of-this-guild.example.com/hook"]
