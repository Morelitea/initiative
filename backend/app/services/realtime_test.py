"""Tenancy tests for the initiative-scoped realtime signal fan-out.

The ``/events/updates`` socket is a content-free **invalidation bus**: it carries
id envelopes only and routes them by ``(guild_id, initiative_id)`` room. These
tests pin the tenancy boundary:

* the ``ConnectionManager`` delivers a room's messages only to that room's
  sockets — and the ``guild_id`` in the key keeps per-guild-schema initiative ids
  (``id SERIAL`` per schema, so id 5 exists in many guilds) from colliding,
* ``broadcast_event`` ships **no tooling content** — an id envelope, never a
  serialized model,
* the socket joins exactly the initiative rooms its user can reach
  (``_accessible_initiative_ids`` → the one ``initiative_access`` function), and
  never any initiative outside the addressed guild.
"""

from datetime import datetime, timedelta, timezone

import inspect

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import establish_guild_access
from app.api.v1.tenant_endpoints.events import _accessible_initiative_ids
from app.models.platform.access_grant import AccessGrant, AccessGrantStatus, AccessLevel
from app.models.platform.guild import GuildRole
from app.services import realtime
from app.services.realtime import ConnectionManager, broadcast_event, manager
from app.testing import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
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
async def test_broadcast_isolated_by_guild_and_initiative() -> None:
    """A signal for (guild 1, initiative 5) reaches only that room — not the same
    initiative id in another guild (the cross-guild collision guard), and not a
    different initiative in the same guild."""
    cm = ConnectionManager()
    same_room = FakeWebSocket()
    other_guild_same_id = FakeWebSocket()
    same_guild_other_init = FakeWebSocket()
    await cm.connect(1, [5], same_room)
    await cm.connect(2, [5], other_guild_same_id)  # SAME local id, different guild
    await cm.connect(1, [6], same_guild_other_init)

    await cm.broadcast(1, 5, {"hello": "g1-i5"})

    assert same_room.sent == [{"hello": "g1-i5"}]
    # initiative id 5 in guild 2 is a DIFFERENT initiative — must not leak.
    assert other_guild_same_id.sent == []
    assert same_guild_other_init.sent == []


@pytest.mark.unit
async def test_broadcast_event_envelope_carries_no_content() -> None:
    """``broadcast_event`` ships an id envelope, never a serialized model — driven
    through the real module ``manager``/``broadcast_event`` every endpoint uses."""
    guild_id, initiative_id = 101, 9
    socket = FakeWebSocket()
    await manager.connect(guild_id, [initiative_id], socket)
    try:
        await broadcast_event(
            guild_id,
            initiative_id,
            "task",
            "updated",
            {"task_id": 7, "project_id": 3},
        )

        assert len(socket.sent) == 1
        message = socket.sent[0]
        assert message["resource"] == "task"
        assert message["action"] == "updated"
        assert message["ids"] == {"task_id": 7, "project_id": 3}
        # No serialized model body may ride the bus.
        assert "data" not in message
    finally:
        await manager.disconnect(socket)


@pytest.mark.unit
async def test_disconnect_removes_socket_from_all_rooms() -> None:
    cm = ConnectionManager()
    socket = FakeWebSocket()
    await cm.connect(5, [1, 2], socket)
    assert cm.room_size(5, 1) == 1
    assert cm.room_size(5, 2) == 1

    await cm.disconnect(socket)
    assert cm.room_size(5, 1) == 0
    assert cm.room_size(5, 2) == 0
    await cm.broadcast(5, 1, {"x": 1})  # broadcast to an emptied room is a no-op
    assert socket.sent == []


@pytest.mark.unit
async def test_failed_send_prunes_socket() -> None:
    class ExplodingWebSocket(FakeWebSocket):
        async def send_json(self, message: dict) -> None:
            raise RuntimeError("connection reset")

    cm = ConnectionManager()
    bad = ExplodingWebSocket()
    await cm.connect(9, [1], bad)

    await cm.broadcast(9, 1, {"x": 1})  # must not raise
    assert cm.room_size(9, 1) == 0  # the dead socket was pruned


def test_broadcast_event_signature_is_guild_and_initiative_scoped() -> None:
    """Guard against a regression to a guild-only or untenanted signature."""
    params = list(inspect.signature(realtime.broadcast_event).parameters)
    assert params[:5] == ["guild_id", "initiative_id", "resource", "action", "ids"]


# ---------------------------------------------------------------------------
# Initiative-room resolution (which rooms a socket joins)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_accessible_initiatives_member_sees_only_their_own(
    session: AsyncSession,
) -> None:
    owner = await create_user(session, email="owner@example.com")
    guild = await create_guild(session, creator=owner)
    member = await create_user(session, email="member@example.com")
    await create_guild_membership(
        session, user=member, guild=guild, role=GuildRole.member
    )
    joined = await create_initiative(session, guild, owner)
    await create_initiative_member(session, joined, member)
    other = await create_initiative(session, guild, owner)  # member NOT added

    await establish_guild_access(session, member, guild.id)
    ids = await _accessible_initiative_ids(session, user_id=member.id)

    assert joined.id in ids
    assert other.id not in ids  # an initiative they're not in is never a room


@pytest.mark.integration
async def test_accessible_initiatives_guild_admin_sees_all(
    session: AsyncSession,
) -> None:
    owner = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, creator=owner)
    await create_guild_membership(
        session, user=owner, guild=guild, role=GuildRole.admin
    )
    one = await create_initiative(session, guild, owner)
    two = await create_initiative(session, guild, owner)

    await establish_guild_access(session, owner, guild.id)
    ids = await _accessible_initiative_ids(session, user_id=owner.id)

    # The guild-admin leg of initiative_access reaches every initiative.
    assert one.id in ids
    assert two.id in ids


@pytest.mark.integration
async def test_accessible_initiatives_pam_grantee_sees_all(
    session: AsyncSession,
) -> None:
    """A live PAM read grantee has guild-wide read, so they may be notified about
    every initiative — they join all rooms, via the PAM leg of initiative_access."""
    owner = await create_user(session, email="grant-owner@example.com")
    guild = await create_guild(session, creator=owner)
    one = await create_initiative(session, guild, owner)
    two = await create_initiative(session, guild, owner)

    grantee = await create_user(session, email="grantee@example.com")  # not a member
    now = datetime.now(timezone.utc)
    session.add(
        AccessGrant(
            user_id=grantee.id,
            guild_id=guild.id,
            access_level=AccessLevel.read.value,
            status=AccessGrantStatus.approved.value,
            reason="support",
            requested_duration_minutes=60,
            requested_by_id=grantee.id,
            approved_by_id=owner.id,
            requested_at=now,
            decided_at=now,
            expires_at=now + timedelta(hours=1),
        )
    )
    await session.commit()

    await establish_guild_access(session, grantee, guild.id)
    ids = await _accessible_initiative_ids(session, user_id=grantee.id)

    assert one.id in ids
    assert two.id in ids
