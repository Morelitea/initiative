"""Tests for the content-streaming spine (``stream_authz``): guild-namespaced
fan-out isolation, and continuous **every-level** re-authorization.

Fan-out is a ``(guild_id, resource_type, resource_id)`` room, so per-guild-schema
resource ids (document / counter-group / queue — all ``SERIAL`` per schema) never
collide across guilds. Re-authorization re-runs the FULL join check:
``establish_guild_access`` (guild membership / PAM / break-glass) THEN the
adapter's ``authorize`` (initiative RLS load + DAC). Either failing hard-disconnects.
"""

from types import SimpleNamespace
from typing import Optional

import pytest
from fastapi import status

from app.api.deps import GuildAccessError
from app.services import stream_authz
from app.services.stream_authz import StreamAuthority


class FakeWebSocket:
    """Records the frames it was sent and the close code it received."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.closed: Optional[int] = None

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)

    async def close(self, code: Optional[int] = None) -> None:
        self.closed = code


USER = SimpleNamespace(id=1)


@pytest.fixture
def authority():
    auth = StreamAuthority()
    yield auth
    # join() lazily starts the bounded re-auth loop; cancel it so the task
    # doesn't outlive the test.
    if auth._loop_task is not None:
        auth._loop_task.cancel()


async def _join(
    auth,
    ws,
    *,
    guild_id,
    resource_type,
    resource_id,
    user=USER,
    authorize=None,
):
    async def _ok(_session, _user):
        return True

    await auth.join(
        ws,
        user,
        guild_id=guild_id,
        initiative_id=99,
        resource_type=resource_type,
        resource_id=resource_id,
        authorize=authorize or _ok,
    )


# ── fan-out isolation ────────────────────────────────────────────────────────


@pytest.mark.unit
async def test_emit_isolated_by_guild_and_resource(authority) -> None:
    same = FakeWebSocket()
    other_guild_same_id = FakeWebSocket()
    same_guild_other_type = FakeWebSocket()
    await _join(authority, same, guild_id=1, resource_type="queue", resource_id=5)
    await _join(
        authority, other_guild_same_id, guild_id=2, resource_type="queue", resource_id=5
    )
    await _join(
        authority,
        same_guild_other_type,
        guild_id=1,
        resource_type="counter_group",
        resource_id=5,
    )

    await authority.emit(1, "queue", 5, "turn_held", {"item": 7})

    assert len(same.sent) == 1
    message = same.sent[0]
    assert message["type"] == "turn_held"
    assert message["data"] == {"item": 7}
    assert "timestamp" in message
    # queue id 5 in guild 2 is a DIFFERENT queue (per-schema ids) — must not leak.
    assert other_guild_same_id.sent == []
    # same guild, different resource type — different room.
    assert same_guild_other_type.sent == []


@pytest.mark.unit
async def test_leave_removes_socket_from_room(authority) -> None:
    ws = FakeWebSocket()
    await _join(authority, ws, guild_id=1, resource_type="document", resource_id=3)
    assert authority.room_size(1, "document", 3) == 1

    await authority.leave(ws)
    assert authority.room_size(1, "document", 3) == 0
    await authority.emit(
        1, "document", 3, "x", {}
    )  # broadcast to empty room is a no-op
    assert ws.sent == []


# ── continuous re-authorization (every level) ────────────────────────────────


def _patch_recheck(monkeypatch, *, establish_ok: bool, authorized: bool):
    """Drive ``_still_authorized`` without a DB: control ``establish_guild_access``
    (the guild / PAM gate) and the adapter ``authorize`` (the initiative + DAC
    gate) independently, and return the authorize closure to register."""

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def execute(self, *_a, **_k):
            return None

    async def fake_establish(_session, _user, _guild_id):
        if not establish_ok:
            raise GuildAccessError()

    monkeypatch.setattr(stream_authz, "AsyncSessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(stream_authz, "establish_guild_access", fake_establish)

    async def authorize(_session, _user):
        return authorized

    return authorize


@pytest.mark.unit
async def test_revoke_keeps_socket_when_still_authorized(
    authority, monkeypatch
) -> None:
    authorize = _patch_recheck(monkeypatch, establish_ok=True, authorized=True)
    ws = FakeWebSocket()
    await _join(
        authority,
        ws,
        guild_id=1,
        resource_type="document",
        resource_id=3,
        authorize=authorize,
    )

    await authority.revoke_user(1, USER.id)

    assert ws.closed is None
    assert authority.room_size(1, "document", 3) == 1


@pytest.mark.unit
async def test_revoke_disconnects_when_dac_or_initiative_lost(
    authority, monkeypatch
) -> None:
    # Guild access is intact (establish succeeds) but the resource-level authorize
    # fails — initiative removed (RLS hides the resource) or DAC revoked.
    authorize = _patch_recheck(monkeypatch, establish_ok=True, authorized=False)
    ws = FakeWebSocket()
    await _join(
        authority,
        ws,
        guild_id=1,
        resource_type="document",
        resource_id=3,
        authorize=authorize,
    )

    await authority.revoke_user(1, USER.id)

    assert ws.closed == status.WS_1008_POLICY_VIOLATION
    assert authority.room_size(1, "document", 3) == 0


@pytest.mark.unit
async def test_revoke_disconnects_when_guild_access_lost(
    authority, monkeypatch
) -> None:
    # establish_guild_access raises (guild membership / PAM gone) — disconnect even
    # though the adapter authorize would pass. Proves the guild-level gate is
    # re-enforced, not just DAC.
    authorize = _patch_recheck(monkeypatch, establish_ok=False, authorized=True)
    ws = FakeWebSocket()
    await _join(
        authority,
        ws,
        guild_id=1,
        resource_type="document",
        resource_id=3,
        authorize=authorize,
    )

    await authority.revoke_user(1, USER.id)

    assert ws.closed == status.WS_1008_POLICY_VIOLATION


@pytest.mark.unit
async def test_revoke_is_scoped_to_guild_and_user(authority, monkeypatch) -> None:
    # A revoke for (guild 1, user 1) must not touch a different user or guild, even
    # when the re-check would deny everyone.
    authorize = _patch_recheck(monkeypatch, establish_ok=False, authorized=False)
    target = FakeWebSocket()
    other_user = FakeWebSocket()
    other_guild = FakeWebSocket()
    await _join(
        authority,
        target,
        guild_id=1,
        resource_type="document",
        resource_id=3,
        user=SimpleNamespace(id=1),
        authorize=authorize,
    )
    await _join(
        authority,
        other_user,
        guild_id=1,
        resource_type="document",
        resource_id=3,
        user=SimpleNamespace(id=2),
        authorize=authorize,
    )
    await _join(
        authority,
        other_guild,
        guild_id=2,
        resource_type="document",
        resource_id=3,
        user=SimpleNamespace(id=1),
        authorize=authorize,
    )

    await authority.revoke_user(1, 1)

    assert target.closed == status.WS_1008_POLICY_VIOLATION
    assert other_user.closed is None  # different user — not re-checked
    assert other_guild.closed is None  # different guild — not re-checked
