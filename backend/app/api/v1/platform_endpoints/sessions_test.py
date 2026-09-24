"""The account's own "where you're signed in" list, and ending one from it."""

from types import SimpleNamespace
from typing import Optional

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.v1.platform_endpoints import sessions as sessions_endpoints
from app.api.v1.platform_endpoints import users as users_endpoints
from app.core import auth_context
from app.core.security import get_password_hash
from app.models.platform.user import UserStatus
from app.services import stream_authz
from app.services.platform import api_keys as api_keys_service
from app.services.platform import user_tokens
from app.services.platform.ws_auth import authenticate_ws_token
from app.services.stream_authz import WS_CREDENTIAL_ENDED, StreamAuthority
from app.testing import create_user, get_auth_headers

CHROME_MAC = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)
FIREFOX_WINDOWS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0"
)

PASSWORD = "testpassword123"


async def _signed_in_user(session: AsyncSession, email: str):
    return await create_user(
        session,
        email=email,
        hashed_password=get_password_hash(PASSWORD),
        status=UserStatus.active,
        email_verified=True,
    )


async def _sign_in(client: AsyncClient, email: str, *, user_agent: str):
    return await client.post(
        "/api/v1/auth/token",
        data={"username": email, "password": PASSWORD},
        headers={"user-agent": user_agent},
    )


@pytest.mark.integration
@pytest.mark.auth
async def test_the_list_names_each_browser_and_marks_the_one_asking(
    client: AsyncClient, session: AsyncSession
):
    """Two browsers signed in; the list says what each one is and which of
    them is reading it."""
    await _signed_in_user(session, "two-browsers@example.com")

    first = await _sign_in(
        client, "two-browsers@example.com", user_agent=FIREFOX_WINDOWS
    )
    assert first.status_code == 200
    client.cookies.clear()
    second = await _sign_in(client, "two-browsers@example.com", user_agent=CHROME_MAC)
    asking = second.json()["access_token"]

    listed = await client.get(
        "/api/v1/auth/sessions",
        headers={"Authorization": f"Bearer {asking}", "user-agent": CHROME_MAC},
    )
    assert listed.status_code == 200
    rows = listed.json()

    labels = {row["label"] for row in rows}
    assert labels == {"Chrome on macOS", "Firefox on Windows"}
    assert all(row["kind"] == "desktop" for row in rows)

    current = [row for row in rows if row["is_current"]]
    assert [row["label"] for row in current] == ["Chrome on macOS"]


@pytest.mark.integration
@pytest.mark.auth
async def test_the_list_carries_no_refresh_token(
    client: AsyncClient, session: AsyncSession
):
    """The row a person reads is the one they need to recognise a device, and
    nothing from the credential columns beside it."""
    await _signed_in_user(session, "no-secrets@example.com")
    login = await _sign_in(client, "no-secrets@example.com", user_agent=CHROME_MAC)

    listed = await client.get(
        "/api/v1/auth/sessions",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert listed.status_code == 200
    assert set(listed.json()[0]) == {
        "id",
        "label",
        "kind",
        "ip",
        "started_at",
        "last_used_at",
        "is_current",
    }


@pytest.mark.integration
@pytest.mark.auth
async def test_a_session_is_dated_from_its_sign_in_not_its_last_renewal(
    client: AsyncClient, session: AsyncSession
):
    """A refresh mints a new row, so reading the tip's own age would report a
    month-old browser as a quarter of an hour old."""
    await _signed_in_user(session, "long-lived@example.com")
    login = await _sign_in(client, "long-lived@example.com", user_agent=CHROME_MAC)
    before = await client.get(
        "/api/v1/auth/sessions",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    started = before.json()[0]["started_at"]

    rotated = await client.post("/api/v1/auth/refresh")
    assert rotated.status_code == 200

    after = await client.get(
        "/api/v1/auth/sessions",
        headers={"Authorization": f"Bearer {rotated.json()['access_token']}"},
    )
    rows = after.json()
    # Still one sign-in, still dated from it.
    assert len(rows) == 1
    assert rows[0]["started_at"] == started


@pytest.mark.integration
@pytest.mark.auth
async def test_ending_a_session_stops_it_renewing(
    client: AsyncClient, session: AsyncSession
):
    await _signed_in_user(session, "end-one@example.com")
    doomed = await _sign_in(client, "end-one@example.com", user_agent=FIREFOX_WINDOWS)
    doomed_refresh = doomed.cookies.get("refresh_token")
    client.cookies.clear()
    asking = await _sign_in(client, "end-one@example.com", user_agent=CHROME_MAC)
    headers = {"Authorization": f"Bearer {asking.json()['access_token']}"}

    rows = (await client.get("/api/v1/auth/sessions", headers=headers)).json()
    target = next(row for row in rows if row["label"] == "Firefox on Windows")

    ended = await client.delete(
        f"/api/v1/auth/sessions/{target['id']}", headers=headers
    )
    assert ended.status_code == 204

    client.cookies.clear()
    client.cookies.set("refresh_token", doomed_refresh, path="/api/v1/auth")
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401

    remaining = (await client.get("/api/v1/auth/sessions", headers=headers)).json()
    assert [row["label"] for row in remaining] == ["Chrome on macOS"]


@pytest.mark.integration
@pytest.mark.auth
async def test_somebody_elses_session_answers_as_missing(
    client: AsyncClient, session: AsyncSession
):
    """The id is the only thing the caller supplied, so a session that is not
    theirs and one that does not exist answer the same."""
    await _signed_in_user(session, "owner@example.com")
    theirs = await _sign_in(client, "owner@example.com", user_agent=CHROME_MAC)
    listed = await client.get(
        "/api/v1/auth/sessions",
        headers={"Authorization": f"Bearer {theirs.json()['access_token']}"},
    )
    target = listed.json()[0]["id"]

    stranger = await create_user(session, email="stranger@example.com")
    refused = await client.delete(
        f"/api/v1/auth/sessions/{target}", headers=get_auth_headers(stranger)
    )
    assert refused.status_code == 404
    assert refused.json()["detail"] == "SESSION_NOT_FOUND"

    # And it is still live for the account that owns it.
    still_there = await client.get(
        "/api/v1/auth/sessions",
        headers={"Authorization": f"Bearer {theirs.json()['access_token']}"},
    )
    assert len(still_there.json()) == 1


@pytest.mark.integration
@pytest.mark.auth
async def test_signing_out_everywhere_else_spares_the_one_asking(
    client: AsyncClient, session: AsyncSession
):
    await _signed_in_user(session, "sweep@example.com")
    await _sign_in(client, "sweep@example.com", user_agent=FIREFOX_WINDOWS)
    client.cookies.clear()
    asking = await _sign_in(client, "sweep@example.com", user_agent=CHROME_MAC)
    headers = {"Authorization": f"Bearer {asking.json()['access_token']}"}

    assert len((await client.get("/api/v1/auth/sessions", headers=headers)).json()) == 2

    swept = await client.post("/api/v1/auth/sessions/revoke-others", headers=headers)
    assert swept.status_code == 204

    rows = (await client.get("/api/v1/auth/sessions", headers=headers)).json()
    assert [row["label"] for row in rows] == ["Chrome on macOS"]
    assert rows[0]["is_current"] is True


@pytest.mark.integration
@pytest.mark.auth
async def test_signing_out_everywhere_else_takes_the_phones_too(
    client: AsyncClient, session: AsyncSession
):
    """The list shows both credentials, so a sweep that left the device tokens
    behind would not be telling the truth."""
    user = await _signed_in_user(session, "sweep-phones@example.com")
    phone = await user_tokens.create_device_token(
        session, user_id=user.id, device_name="Phone"
    )
    asking = await _sign_in(client, "sweep-phones@example.com", user_agent=CHROME_MAC)
    headers = {"Authorization": f"Bearer {asking.json()['access_token']}"}

    swept = await client.post("/api/v1/auth/sessions/revoke-others", headers=headers)
    assert swept.status_code == 204

    spent = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"DeviceToken {phone}"}
    )
    assert spent.status_code == 401


@pytest.mark.integration
@pytest.mark.auth
async def test_a_native_client_sweeping_spares_its_own_device(
    client: AsyncClient, session: AsyncSession
):
    """Which credential is spared follows what the caller is holding."""
    user = await _signed_in_user(session, "native-sweep@example.com")
    asking = await user_tokens.create_device_token(
        session, user_id=user.id, device_name="This phone"
    )
    other = await user_tokens.create_device_token(
        session, user_id=user.id, device_name="Old tablet"
    )
    headers = {"Authorization": f"DeviceToken {asking}"}

    swept = await client.post("/api/v1/auth/sessions/revoke-others", headers=headers)
    assert swept.status_code == 204

    assert (await client.get("/api/v1/users/me", headers=headers)).status_code == 200
    stale = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"DeviceToken {other}"}
    )
    assert stale.status_code == 401


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/auth/sessions"),
        ("POST", "/api/v1/auth/sessions/revoke-others"),
        ("GET", "/api/v1/auth/device-tokens"),
    ],
)
async def test_a_standing_credential_does_not_manage_sign_ins(
    client: AsyncClient, session: AsyncSession, method: str, path: str
):
    """The account's sign-ins are the person's to list and end, not a key's."""
    user = await _signed_in_user(session, f"sessions-key-{method}@example.com")
    secret, _row = await api_keys_service.create_api_key(
        session, user=user, name="script"
    )
    await session.commit()

    response = await client.request(
        method, path, headers={"Authorization": f"Bearer {secret}"}
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "SESSION_REQUIRED"


# ── open connections follow the sign-ins they were opened on ─────────────────


class _Socket:
    """Stands in for a content WebSocket: records the code it was closed with."""

    def __init__(self) -> None:
        self.closed: Optional[int] = None

    async def close(self, code: Optional[int] = None) -> None:
        self.closed = code


class _LiveAccountSession:
    """The session a surviving socket's access re-check opens, answering that
    the account is live. What these tests are about is the credential."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    async def exec(self, *_a, **_k):
        return None

    async def get(self, _model, _pk):
        return SimpleNamespace(status=UserStatus.active)


@pytest.fixture
def streams(monkeypatch):
    """A stream registry the endpoints under test report to, whose guild and
    resource checks pass, so a socket closes on its credential or not at all."""
    auth_context.set_session_credential(None)
    auth_context.set_device_token_id(None)
    authority = StreamAuthority()

    async def _admitted(*_a, **_k):
        return None

    monkeypatch.setattr(
        stream_authz, "request_sessionmaker", lambda _guild_id: _LiveAccountSession
    )
    monkeypatch.setattr(stream_authz, "establish_guild_access", _admitted)
    monkeypatch.setattr(sessions_endpoints, "stream_authority", authority)
    monkeypatch.setattr(users_endpoints, "stream_authority", authority)
    yield authority
    if authority._loop_task is not None:
        authority._loop_task.cancel()


async def _open_stream(
    authority: StreamAuthority, token: str, session: AsyncSession
) -> _Socket:
    """Authenticate the way a socket's handshake does, then join a room."""
    user = await authenticate_ws_token(token, session)
    assert user is not None

    async def _readable(_session, _user):
        return True

    socket = _Socket()
    await authority.join(
        socket,  # type: ignore[arg-type]
        user,
        guild_id=1,
        initiative_id=1,
        resource_type="document",
        resource_id=1,
        authorize=_readable,
    )
    return socket


@pytest.mark.integration
@pytest.mark.auth
async def test_ending_a_session_closes_the_connections_opened_on_it(
    client: AsyncClient, session: AsyncSession, streams: StreamAuthority
):
    await _signed_in_user(session, "end-streams@example.com")
    doomed = await _sign_in(
        client, "end-streams@example.com", user_agent=FIREFOX_WINDOWS
    )
    client.cookies.clear()
    asking = await _sign_in(client, "end-streams@example.com", user_agent=CHROME_MAC)
    asking_token = asking.json()["access_token"]
    headers = {"Authorization": f"Bearer {asking_token}"}

    on_doomed = await _open_stream(streams, doomed.json()["access_token"], session)
    on_asking = await _open_stream(streams, asking_token, session)

    rows = (await client.get("/api/v1/auth/sessions", headers=headers)).json()
    target = next(row for row in rows if row["label"] == "Firefox on Windows")
    ended = await client.delete(
        f"/api/v1/auth/sessions/{target['id']}", headers=headers
    )
    assert ended.status_code == 204

    assert on_doomed.closed == WS_CREDENTIAL_ENDED
    assert on_asking.closed is None


@pytest.mark.integration
@pytest.mark.auth
async def test_signing_out_everywhere_else_keeps_this_sessions_connections(
    client: AsyncClient, session: AsyncSession, streams: StreamAuthority
):
    user = await _signed_in_user(session, "sweep-streams@example.com")
    elsewhere = await _sign_in(
        client, "sweep-streams@example.com", user_agent=FIREFOX_WINDOWS
    )
    client.cookies.clear()
    asking = await _sign_in(client, "sweep-streams@example.com", user_agent=CHROME_MAC)
    asking_token = asking.json()["access_token"]
    phone = await user_tokens.create_device_token(
        session, user_id=user.id, device_name="Phone"
    )

    on_elsewhere = await _open_stream(
        streams, elsewhere.json()["access_token"], session
    )
    on_phone = await _open_stream(streams, phone, session)
    on_asking = await _open_stream(streams, asking_token, session)

    swept = await client.post(
        "/api/v1/auth/sessions/revoke-others",
        headers={"Authorization": f"Bearer {asking_token}"},
    )
    assert swept.status_code == 204

    assert on_elsewhere.closed == WS_CREDENTIAL_ENDED
    assert on_phone.closed == WS_CREDENTIAL_ENDED
    assert on_asking.closed is None


@pytest.mark.integration
@pytest.mark.auth
async def test_a_password_change_closes_the_connections_opened_before_it(
    client: AsyncClient, session: AsyncSession, streams: StreamAuthority
):
    """Every credential the account held goes with the old password, this
    device's included; its replacement session is what it reconnects with."""
    user = await _signed_in_user(session, "pw-streams@example.com")
    elsewhere = await _sign_in(
        client, "pw-streams@example.com", user_agent=FIREFOX_WINDOWS
    )
    client.cookies.clear()
    asking = await _sign_in(client, "pw-streams@example.com", user_agent=CHROME_MAC)
    asking_token = asking.json()["access_token"]
    phone = await user_tokens.create_device_token(
        session, user_id=user.id, device_name="Phone"
    )

    on_elsewhere = await _open_stream(
        streams, elsewhere.json()["access_token"], session
    )
    on_phone = await _open_stream(streams, phone, session)
    on_asking = await _open_stream(streams, asking_token, session)

    changed = await client.patch(
        "/api/v1/users/me",
        json={"password": "newpassword456", "current_password": PASSWORD},
        headers={"Authorization": f"Bearer {asking_token}"},
    )
    assert changed.status_code == 200, changed.text

    assert on_elsewhere.closed == WS_CREDENTIAL_ENDED
    assert on_phone.closed == WS_CREDENTIAL_ENDED
    assert on_asking.closed == WS_CREDENTIAL_ENDED
