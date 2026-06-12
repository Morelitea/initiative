"""Regression tests for guild-scoped realtime event fan-out (SEC-2).

The ``/events/updates`` socket used to register every connection in one global
room, so ``broadcast_event`` leaked every guild's task/comment/project payloads
to every connected user. These tests pin the tenancy boundary:

* the ``ConnectionManager`` only delivers a guild's messages to that guild's
  sockets,
* ``broadcast_event`` fans an event out to a single guild,
* the socket's authorization gate (``_user_can_access_guild``) admits a member
  (or a live PAM grantee) and rejects everyone else.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.v1.endpoints.events import _user_can_access_guild
from app.models.access_grant import AccessGrant, AccessGrantStatus, AccessLevel
from app.models.guild import GuildRole
from app.services import realtime
from app.services.realtime import ConnectionManager, broadcast_event, manager
from app.testing import (
    create_guild,
    create_guild_membership,
    create_user,
)


class FakeWebSocket:
    """Minimal stand-in that records the JSON frames it was sent."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)


# ---------------------------------------------------------------------------
# ConnectionManager / broadcast fan-out isolation
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_broadcast_only_reaches_same_guild_room() -> None:
    cm = ConnectionManager()
    socket_a = FakeWebSocket()
    socket_b = FakeWebSocket()
    await cm.connect(1, socket_a)
    await cm.connect(2, socket_b)

    await cm.broadcast(1, {"hello": "guild-1"})

    assert socket_a.sent == [{"hello": "guild-1"}]
    assert socket_b.sent == []  # guild-2 socket must never see guild-1 traffic


@pytest.mark.unit
async def test_broadcast_event_is_delivered_only_to_event_guild() -> None:
    """The ticket's acceptance check: a task event in guild A reaches only the
    guild-A socket, never the guild-B socket — driven through the real module
    ``manager`` and ``broadcast_event`` used by every endpoint."""
    guild_a_id = 101
    guild_b_id = 202
    socket_a = FakeWebSocket()
    socket_b = FakeWebSocket()
    await manager.connect(guild_a_id, socket_a)
    await manager.connect(guild_b_id, socket_b)
    try:
        await broadcast_event(
            guild_a_id,
            "task",
            "updated",
            {"id": 7, "title": "Secret guild-A task", "guild_id": guild_a_id},
        )

        assert len(socket_a.sent) == 1
        message = socket_a.sent[0]
        assert message["resource"] == "task"
        assert message["action"] == "updated"
        assert message["data"]["title"] == "Secret guild-A task"
        # The guild-B socket must not receive the guild-A payload.
        assert socket_b.sent == []
    finally:
        await manager.disconnect(guild_a_id, socket_a)
        await manager.disconnect(guild_b_id, socket_b)


@pytest.mark.unit
async def test_disconnect_removes_socket_and_empty_room() -> None:
    cm = ConnectionManager()
    socket = FakeWebSocket()
    await cm.connect(5, socket)
    assert cm.room_size(5) == 1

    await cm.disconnect(5, socket)
    assert cm.room_size(5) == 0
    # An emptied room is dropped, and a broadcast to it is a no-op.
    await cm.broadcast(5, {"x": 1})
    assert socket.sent == []


@pytest.mark.unit
async def test_failed_send_disconnects_socket() -> None:
    class ExplodingWebSocket(FakeWebSocket):
        async def send_json(self, message: dict) -> None:
            raise RuntimeError("connection reset")

    cm = ConnectionManager()
    bad = ExplodingWebSocket()
    await cm.connect(9, bad)

    await cm.broadcast(9, {"x": 1})  # must not raise
    assert cm.room_size(9) == 0  # the dead socket was pruned


# ---------------------------------------------------------------------------
# Socket authorization gate
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_member_can_access_only_their_guild(session: AsyncSession) -> None:
    user = await create_user(session, email="member@example.com")
    guild_a = await create_guild(session, creator=user)
    await create_guild_membership(
        session, user=user, guild=guild_a, role=GuildRole.member
    )

    other_owner = await create_user(session, email="other@example.com")
    guild_b = await create_guild(session, creator=other_owner)

    assert await _user_can_access_guild(session, user=user, guild_id=guild_a.id) is True
    # Not a member of guild B (and no grant) → rejected.
    assert (
        await _user_can_access_guild(session, user=user, guild_id=guild_b.id) is False
    )


@pytest.mark.integration
async def test_live_pam_grant_admits_non_member(session: AsyncSession) -> None:
    user = await create_user(session, email="grantee@example.com")
    owner = await create_user(session, email="owner@example.com")
    guild = await create_guild(session, creator=owner)
    # The grantee is NOT a member of the guild.

    now = datetime.now(timezone.utc)
    grant = AccessGrant(
        user_id=user.id,
        guild_id=guild.id,
        access_level=AccessLevel.read.value,
        status=AccessGrantStatus.approved.value,
        reason="support",
        requested_duration_minutes=60,
        requested_by_id=user.id,
        approved_by_id=owner.id,
        requested_at=now,
        decided_at=now,
        expires_at=now + timedelta(hours=1),
    )
    session.add(grant)
    await session.commit()

    assert await _user_can_access_guild(session, user=user, guild_id=guild.id) is True


@pytest.mark.integration
async def test_expired_pam_grant_does_not_admit(session: AsyncSession) -> None:
    user = await create_user(session, email="stale@example.com")
    owner = await create_user(session, email="owner2@example.com")
    guild = await create_guild(session, creator=owner)

    now = datetime.now(timezone.utc)
    expired = AccessGrant(
        user_id=user.id,
        guild_id=guild.id,
        access_level=AccessLevel.read.value,
        status=AccessGrantStatus.approved.value,
        reason="support",
        requested_duration_minutes=60,
        requested_by_id=user.id,
        approved_by_id=owner.id,
        requested_at=now - timedelta(hours=2),
        decided_at=now - timedelta(hours=2),
        expires_at=now - timedelta(minutes=1),
    )
    session.add(expired)
    await session.commit()

    assert await _user_can_access_guild(session, user=user, guild_id=guild.id) is False


def test_realtime_module_exposes_guild_scoped_api() -> None:
    """Guard against a regression to the old global-broadcast signature."""
    import inspect

    sig = inspect.signature(realtime.broadcast_event)
    params = list(sig.parameters)
    assert params[0] == "guild_id"
    assert params[:4] == ["guild_id", "resource", "action", "payload"]
    # The old global helper must be gone so no caller can fan out untenanted.
    assert not hasattr(ConnectionManager, "add_connection")
