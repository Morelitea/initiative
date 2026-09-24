"""Tests for the content-streaming spine (``stream_authz``): guild-namespaced
fan-out isolation, and continuous **every-level** re-authorization.

Fan-out is a ``(guild_id, resource_type, resource_id)`` room, so per-guild-schema
resource ids (document / counter-group / queue — all ``SERIAL`` per schema) never
collide across guilds. Re-authorization re-runs the FULL join check:
``establish_guild_access`` (guild membership / PAM / break-glass) THEN the
adapter's ``authorize`` (initiative RLS load + DAC). Either failing hard-disconnects.
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Optional

import pytest
from fastapi import status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import GuildAccessError
from app.core import auth_context
from app.services import stream_authz
from app.services.auth import sessions as session_service
from app.services.platform import user_tokens
from app.services.platform.ws_auth import authenticate_ws_token
from app.services.stream_authz import WS_CREDENTIAL_ENDED, StreamAuthority
from app.models.platform.user import UserStatus
from app.models.platform.user_token import UserToken
from app.testing import create_user, get_auth_token


class FakeWebSocket:
    """Records the frames it was sent and the close code it received."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.sent_bytes: list[bytes] = []
        self.closed: Optional[int] = None

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)

    async def send_bytes(self, payload: bytes) -> None:
        self.sent_bytes.append(payload)

    async def close(self, code: Optional[int] = None) -> None:
        self.closed = code


USER = SimpleNamespace(id=1)


@pytest.fixture
def authority():
    # A socket's credential is read off the auth context at join; start each
    # test with none recorded.
    auth_context.set_session_credential(None)
    auth_context.set_device_token_id(None)
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
    satisfied_providers=frozenset(),
    meta=None,
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
        satisfied_providers=satisfied_providers,
        meta=meta,
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


class _FakeSession:
    """The session ``_still_authorized`` opens, without a database behind it.

    ``get`` answers with the account as it stands now, which is the point: the
    socket carries the one it joined with.
    """

    def __init__(self, account_status: UserStatus = UserStatus.active) -> None:
        self._account_status = account_status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    async def exec(self, *_a, **_k):
        return None

    async def get(self, _model, _pk):
        return SimpleNamespace(id=USER.id, status=self._account_status)


def _patch_recheck(
    monkeypatch,
    *,
    establish_ok: bool,
    authorized: bool,
    account_status: UserStatus = UserStatus.active,
):
    """Drive ``_still_authorized`` without a DB: control the account's own
    status, ``establish_guild_access`` (the guild / PAM gate) and the adapter
    ``authorize`` (the initiative + DAC gate) independently, and return the
    authorize closure to register."""

    seen_satisfied: list = []

    async def fake_establish(_session, _user, _guild_id, satisfied_providers=None):
        seen_satisfied.append(satisfied_providers)
        if not establish_ok:
            raise GuildAccessError()

    monkeypatch.setattr(
        stream_authz,
        "request_sessionmaker",
        lambda _guild_id: lambda: _FakeSession(account_status),
    )
    monkeypatch.setattr(stream_authz, "establish_guild_access", fake_establish)

    async def authorize(_session, _user):
        return authorized

    return authorize, seen_satisfied


@pytest.mark.unit
async def test_revoke_keeps_socket_when_still_authorized(
    authority, monkeypatch
) -> None:
    authorize, _ = _patch_recheck(monkeypatch, establish_ok=True, authorized=True)
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
    authorize, _ = _patch_recheck(monkeypatch, establish_ok=True, authorized=False)
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
    authorize, _ = _patch_recheck(monkeypatch, establish_ok=False, authorized=True)
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
async def test_recheck_replays_join_time_satisfied_providers(
    authority, monkeypatch
) -> None:
    # The re-check must present the SAME satisfied-provider set the socket's
    # session proved at join — so a guild auth policy added mid-connection is
    # judged against the real session, and a satisfied session isn't dropped.
    authorize, seen = _patch_recheck(monkeypatch, establish_ok=True, authorized=True)
    ws = FakeWebSocket()
    await _join(
        authority,
        ws,
        guild_id=1,
        resource_type="document",
        resource_id=3,
        authorize=authorize,
        satisfied_providers=frozenset({42}),
    )

    await authority.revoke_user(1, USER.id)

    assert seen == [frozenset({42})]
    assert ws.closed is None


@pytest.mark.unit
async def test_recheck_answers_for_the_session_that_opened_the_socket(
    authority, monkeypatch
) -> None:
    """A community that asks for a passkey is answered against the socket's own
    session. The re-check runs wherever the change came from — another
    account's request, or the bounded loop — so the standing it reads is the
    one captured at join, and what it found there is put back."""

    async def gate_wanting_a_passkey(
        _session, _user, _guild_id, satisfied_providers=None
    ):
        if not auth_context.session_amr() & {"hwk", "swk"}:
            raise GuildAccessError()

    monkeypatch.setattr(
        stream_authz, "request_sessionmaker", lambda _guild_id: lambda: _FakeSession()
    )
    monkeypatch.setattr(stream_authz, "establish_guild_access", gate_wanting_a_passkey)

    with_a_key = FakeWebSocket()
    auth_context.set_session_amr(frozenset({"mfa", "hwk"}))
    await _join(
        authority, with_a_key, guild_id=1, resource_type="document", resource_id=3
    )

    with_a_password = FakeWebSocket()
    auth_context.set_session_amr(None)
    await _join(
        authority, with_a_password, guild_id=1, resource_type="document", resource_id=4
    )

    # Re-checked from a context carrying neither: the passkey socket stays.
    await authority.revoke_user(1, USER.id)
    assert with_a_key.closed is None
    assert with_a_password.closed == status.WS_1008_POLICY_VIOLATION
    assert auth_context.session_amr() == frozenset()

    # And from one carrying both: the socket opened without a key still goes.
    again = FakeWebSocket()
    await _join(authority, again, guild_id=1, resource_type="document", resource_id=5)
    auth_context.set_session_amr(frozenset({"mfa", "hwk"}))
    await authority.revoke_user(1, USER.id)
    assert again.closed == status.WS_1008_POLICY_VIOLATION
    assert with_a_key.closed is None
    assert auth_context.session_amr() == frozenset({"mfa", "hwk"})


@pytest.mark.unit
async def test_recheck_answers_a_narrowed_provider_from_the_socket(
    authority, monkeypatch
) -> None:
    """A community that narrows its provider by a claim is answered the same
    way: from what the joining session asserted, not from whatever the task
    running the check happens to carry."""

    async def gate_wanting_the_claim(
        _session, _user, _guild_id, satisfied_providers=None
    ):
        asserted = auth_context.satisfied_claims().get("7", {})
        if "acme.com" not in asserted.get("hd", []):
            raise GuildAccessError()

    monkeypatch.setattr(
        stream_authz, "request_sessionmaker", lambda _guild_id: lambda: _FakeSession()
    )
    monkeypatch.setattr(stream_authz, "establish_guild_access", gate_wanting_the_claim)

    from_acme = FakeWebSocket()
    auth_context.set_satisfied_claims({"7": {"hd": ["acme.com"]}})
    await _join(
        authority, from_acme, guild_id=1, resource_type="document", resource_id=3
    )

    from_elsewhere = FakeWebSocket()
    auth_context.set_satisfied_claims({"7": {"hd": ["other.example"]}})
    await _join(
        authority, from_elsewhere, guild_id=1, resource_type="document", resource_id=4
    )

    # Re-checked from a context asserting nothing at all: each socket is
    # answered from what it joined with.
    auth_context.set_satisfied_claims(None)
    await authority.revoke_user(1, USER.id)
    assert from_acme.closed is None
    assert from_elsewhere.closed == status.WS_1008_POLICY_VIOLATION
    assert auth_context.satisfied_claims() == {}

    # And what the checking task carried is put back, not left as the socket's.
    auth_context.set_satisfied_claims({"7": {"hd": ["third.example"]}})
    await authority.revoke_user(1, USER.id)
    assert auth_context.satisfied_claims() == {"7": {"hd": ["third.example"]}}


@pytest.mark.unit
async def test_revoke_is_scoped_to_guild_and_user(authority, monkeypatch) -> None:
    # A revoke for (guild 1, user 1) must not touch a different user or guild, even
    # when the re-check would deny everyone.
    authorize, _ = _patch_recheck(monkeypatch, establish_ok=False, authorized=False)
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


@pytest.mark.unit
@pytest.mark.parametrize(
    "account_status",
    [UserStatus.suspended, UserStatus.deactivated, UserStatus.anonymized],
)
async def test_revoke_disconnects_when_the_account_is_no_longer_live(
    authority, monkeypatch, account_status
) -> None:
    """Both guild gates still pass — what changed is the account itself.

    A socket carries the account as it was when it joined, so the check has to
    read it again; suspension in particular leaves every membership in place,
    so nothing else here would notice.
    """
    authorize, _ = _patch_recheck(
        monkeypatch,
        establish_ok=True,
        authorized=True,
        account_status=account_status,
    )
    ws = FakeWebSocket()
    await _join(
        authority,
        ws,
        guild_id=1,
        resource_type="document",
        resource_id=3,
        authorize=authorize,
    )

    await authority.revoke_user_everywhere(USER.id)

    assert ws.closed == status.WS_1008_POLICY_VIOLATION
    assert authority.room_size(1, "document", 3) == 0


@pytest.mark.unit
async def test_a_live_account_keeps_its_socket(authority, monkeypatch) -> None:
    authorize, _ = _patch_recheck(monkeypatch, establish_ok=True, authorized=True)
    ws = FakeWebSocket()
    await _join(
        authority,
        ws,
        guild_id=1,
        resource_type="document",
        resource_id=3,
        authorize=authorize,
    )

    await authority.revoke_user_everywhere(USER.id)

    assert ws.closed is None
    assert authority.room_size(1, "document", 3) == 1


# ── binary fan-out ───────────────────────────────────────────────────────────


@pytest.mark.unit
async def test_emit_bytes_reaches_a_second_connection_of_the_same_account(
    authority,
) -> None:
    """One person's two tabs are two connections, and each is the other's peer.

    Exclusion is by socket, so the only frame withheld is the sender's own.
    """
    first = FakeWebSocket()
    second = FakeWebSocket()
    await _join(authority, first, guild_id=1, resource_type="document", resource_id=7)
    await _join(authority, second, guild_id=1, resource_type="document", resource_id=7)

    await authority.emit_bytes(1, "document", 7, b"\x02update", exclude=first)

    assert second.sent_bytes == [b"\x02update"]
    assert first.sent_bytes == []


@pytest.mark.unit
async def test_emit_bytes_is_isolated_by_guild(authority) -> None:
    same = FakeWebSocket()
    other_guild = FakeWebSocket()
    await _join(authority, same, guild_id=1, resource_type="document", resource_id=5)
    await _join(
        authority, other_guild, guild_id=2, resource_type="document", resource_id=5
    )

    await authority.emit_bytes(1, "document", 5, b"\x02payload")

    assert same.sent_bytes == [b"\x02payload"]
    assert other_guild.sent_bytes == []


@pytest.mark.unit
async def test_room_members_carries_the_channels_own_state(authority) -> None:
    ws = FakeWebSocket()
    await _join(
        authority,
        ws,
        guild_id=1,
        resource_type="document",
        resource_id=5,
        meta={"name": "Ada", "can_write": True},
    )

    members = authority.room_members(1, "document", 5)

    assert len(members) == 1
    assert members[0].user is USER
    assert members[0].meta["name"] == "Ada"
    assert members[0].meta["can_write"] is True


# ── the credential the socket was opened with ────────────────────────────────


async def _open_stream(
    auth: StreamAuthority, token: str, session: AsyncSession
) -> FakeWebSocket:
    """Authenticate ``token`` the way a socket's handshake does, then join.

    The handshake is what records which credential it was, so the member
    carries exactly what a real connection would.
    """
    user = await authenticate_ws_token(token, session)
    assert user is not None
    ws = FakeWebSocket()
    await _join(
        auth, ws, guild_id=1, resource_type="document", resource_id=3, user=user
    )
    return ws


@pytest.mark.integration
async def test_a_socket_on_an_ended_session_is_closed(
    authority, monkeypatch, session: AsyncSession
) -> None:
    _patch_recheck(monkeypatch, establish_ok=True, authorized=True)
    user = await create_user(session)
    issued = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[]
    )
    await session.commit()
    ws = await _open_stream(
        authority, get_auth_token(user, session_id=issued.session.id), session
    )

    await authority.revoke_user_everywhere(user.id)
    assert ws.closed is None

    await session_service.revoke_chain(session, session_id=issued.session.id)
    await session.commit()
    await authority.revoke_user_everywhere(user.id)

    assert ws.closed == WS_CREDENTIAL_ENDED
    assert authority.room_size(1, "document", 3) == 0


@pytest.mark.integration
async def test_a_socket_follows_its_session_through_a_renewal(
    authority, monkeypatch, session: AsyncSession
) -> None:
    """A refresh spends the row the socket was opened on and mints its
    successor; the sign-in is the same one, so the socket stays."""
    _patch_recheck(monkeypatch, establish_ok=True, authorized=True)
    user = await create_user(session)
    issued = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[]
    )
    await session.commit()
    ws = await _open_stream(
        authority, get_auth_token(user, session_id=issued.session.id), session
    )

    renewed = await session_service.rotate_session(
        session, raw_refresh_token=issued.refresh_token
    )
    assert renewed.ok and renewed.issued is not None
    await session.commit()
    await authority.revoke_user_everywhere(user.id)
    assert ws.closed is None

    # Ended from the row it renewed into, which the socket never named.
    await session_service.revoke_chain(session, session_id=renewed.issued.session.id)
    await session.commit()
    await authority.revoke_user_everywhere(user.id)
    assert ws.closed == WS_CREDENTIAL_ENDED


@pytest.mark.integration
async def test_a_token_version_bump_closes_the_socket(
    authority, monkeypatch, session: AsyncSession
) -> None:
    _patch_recheck(monkeypatch, establish_ok=True, authorized=True)
    user = await create_user(session)
    issued = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[]
    )
    await session.commit()
    ws = await _open_stream(
        authority, get_auth_token(user, session_id=issued.session.id), session
    )

    user.token_version += 1
    session.add(user)
    await session.commit()
    await authority.revoke_user_everywhere(user.id)

    assert ws.closed == WS_CREDENTIAL_ENDED


@pytest.mark.integration
async def test_a_consumed_device_token_closes_only_its_own_socket(
    authority, monkeypatch, session: AsyncSession
) -> None:
    _patch_recheck(monkeypatch, establish_ok=True, authorized=True)
    user = await create_user(session)
    phone = await user_tokens.create_device_token(
        session, user_id=user.id, device_name="Phone"
    )
    tablet = await user_tokens.create_device_token(
        session, user_id=user.id, device_name="Tablet"
    )
    on_phone = await _open_stream(authority, phone, session)
    phone_id = auth_context.device_token_id()
    on_tablet = await _open_stream(authority, tablet, session)

    row = await session.get(UserToken, phone_id)
    assert row is not None
    row.consumed_at = datetime.now(timezone.utc)
    session.add(row)
    await session.commit()
    await authority.revoke_user_everywhere(user.id)

    assert on_phone.closed == WS_CREDENTIAL_ENDED
    assert on_tablet.closed is None
