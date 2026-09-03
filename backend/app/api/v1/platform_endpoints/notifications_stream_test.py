"""The notification bell's push socket — the handshake and its bookkeeping.

The invariant under test: the registry holds exactly the sockets that
authenticated, for exactly as long as they are connected. A socket joins it
only after a credential resolves to an active user, and leaves it when the
connection ends, however it ends.

The socket is driven directly rather than over the wire — the HTTP test client
here is ``httpx``, which speaks no WebSocket — with a stand-in that records what
the endpoint did to it.
"""

import asyncio

import pytest
from fastapi import WebSocketDisconnect
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.v1.platform_endpoints import notifications as notifications_endpoint
from app.api.v1.platform_endpoints.notifications import (
    MSG_ACTIVE,
    MSG_AUTH,
    websocket_notifications,
)
from app.core.security import SESSION_COOKIE_NAME
from app.services.platform import presence, user_stream
from app.services.platform.user_stream import UserStream
from app.testing import create_user, get_auth_token

WS_POLICY_VIOLATION = 1008


class FakeWebSocket:
    """Drives the endpoint through one handshake, then hangs up.

    ``frames`` are the client's inbound frames: the handshake reads the first,
    the keepalive loop the rest. Once they run out the socket reports a
    disconnect, which is how a real client leaving arrives.
    """

    def __init__(self, frames: list[bytes], cookies: dict | None = None) -> None:
        self._frames = list(frames)
        self.cookies = cookies or {}
        self.accepted = False
        self.closed_with: int | None = None
        self.sent: list[dict] = []

    async def accept(self) -> None:
        self.accepted = True

    async def receive_bytes(self) -> bytes:
        if not self._frames:
            raise WebSocketDisconnect(code=1000)
        return self._frames.pop(0)

    async def receive(self) -> dict:
        """The raw ASGI message, as Starlette hands it over: a disconnect
        arrives here as a message rather than an exception."""
        if not self._frames:
            return {"type": "websocket.disconnect", "code": 1000}
        return {"type": "websocket.receive", "bytes": self._frames.pop(0)}

    async def close(self, code: int = 1000) -> None:
        self.closed_with = code

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)


def _auth_frame(payload: bytes) -> bytes:
    return bytes([MSG_AUTH]) + payload


@pytest.fixture
def stream(monkeypatch) -> UserStream:
    """A registry of this test's own, so assertions see only its sockets."""
    fresh = UserStream()
    monkeypatch.setattr(user_stream, "stream", fresh)
    return fresh


@pytest.fixture
def ws_sessions(monkeypatch, engine):
    """Point the endpoint's own short-lived session factory at the test DB."""
    monkeypatch.setattr(
        notifications_endpoint,
        "AsyncSessionLocal",
        async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession),
    )


@pytest.mark.integration
async def test_a_valid_token_joins_and_then_leaves_the_registry(
    session, stream, ws_sessions
) -> None:
    user = await create_user(session)
    await session.commit()
    token = get_auth_token(user)
    websocket = FakeWebSocket([_auth_frame(f'{{"token": "{token}"}}'.encode())])

    await websocket_notifications(websocket)

    assert websocket.accepted
    assert websocket.closed_with is None
    # The keepalive loop ended with the client's disconnect, and the socket
    # left with it.
    assert stream.socket_count(user.id) == 0


@pytest.mark.integration
async def test_the_socket_is_registered_while_the_loop_runs(
    session, stream, ws_sessions, monkeypatch
) -> None:
    """The registry entry has to exist *during* the socket's life, which the
    disconnect above tears down before we can look at it."""
    user = await create_user(session)
    await session.commit()
    token = get_auth_token(user)
    websocket = FakeWebSocket([_auth_frame(f'{{"token": "{token}"}}'.encode())])

    counted: list[int] = []

    async def receive() -> dict:
        counted.append(stream.socket_count(user.id))
        return {"type": "websocket.disconnect", "code": 1000}

    monkeypatch.setattr(websocket, "receive", receive)
    await websocket_notifications(websocket)

    assert counted == [1]


@pytest.mark.integration
async def test_a_session_cookie_stands_in_for_a_null_token(
    session, stream, ws_sessions, monkeypatch
) -> None:
    """Web sessions hold the JWT in an HttpOnly cookie the page cannot read, so
    they send ``{"token": null}`` and the socket reads the cookie itself."""
    user = await create_user(session)
    await session.commit()
    websocket = FakeWebSocket(
        [_auth_frame(b'{"token": null}')],
        cookies={SESSION_COOKIE_NAME: get_auth_token(user)},
    )

    counted: list[int] = []

    async def receive() -> dict:
        counted.append(stream.socket_count(user.id))
        return {"type": "websocket.disconnect", "code": 1000}

    monkeypatch.setattr(websocket, "receive", receive)
    await websocket_notifications(websocket)

    assert websocket.closed_with is None
    assert counted == [1]


@pytest.mark.integration
async def test_an_active_frame_marks_its_person_present(
    session, stream, ws_sessions, monkeypatch
) -> None:
    """The one frame the client sends back says its person is at the keyboard,
    and names nobody — the socket already knows whose it is."""
    user = await create_user(session)
    await session.commit()
    token = get_auth_token(user)
    websocket = FakeWebSocket(
        [_auth_frame(f'{{"token": "{token}"}}'.encode()), bytes([MSG_ACTIVE])]
    )

    seen: list[int] = []
    monkeypatch.setattr(presence.online, "active", seen.append)

    await websocket_notifications(websocket)

    assert seen == [user.id]
    assert websocket.closed_with is None


@pytest.mark.integration
async def test_an_invalid_token_is_refused(session, stream, ws_sessions) -> None:
    websocket = FakeWebSocket([_auth_frame(b'{"token": "not-a-token"}')])

    await websocket_notifications(websocket)

    assert websocket.closed_with == WS_POLICY_VIOLATION


@pytest.mark.integration
async def test_a_revoked_token_is_refused(session, stream, ws_sessions) -> None:
    """Logout / password change revoke by bumping ``token_version``; the socket
    must honour that the same way the REST path does."""
    user = await create_user(session)
    await session.commit()
    token = get_auth_token(user)
    user.token_version += 1
    session.add(user)
    await session.commit()

    websocket = FakeWebSocket([_auth_frame(f'{{"token": "{token}"}}'.encode())])
    await websocket_notifications(websocket)

    assert websocket.closed_with == WS_POLICY_VIOLATION
    assert stream.socket_count(user.id) == 0


@pytest.mark.unit
async def test_a_first_frame_that_is_not_msg_auth_is_refused(stream) -> None:
    websocket = FakeWebSocket([bytes([0]) + b"{}"])

    await websocket_notifications(websocket)

    assert websocket.closed_with == WS_POLICY_VIOLATION


@pytest.mark.unit
async def test_a_malformed_auth_payload_is_refused(stream) -> None:
    websocket = FakeWebSocket([_auth_frame(b"not json")])

    await websocket_notifications(websocket)

    assert websocket.closed_with == WS_POLICY_VIOLATION


@pytest.mark.unit
async def test_no_token_and_no_cookie_is_refused(stream) -> None:
    websocket = FakeWebSocket([_auth_frame(b'{"token": null}')])

    await websocket_notifications(websocket)

    assert websocket.closed_with == WS_POLICY_VIOLATION


@pytest.mark.unit
async def test_a_socket_that_never_sends_its_first_frame_is_closed(
    stream, monkeypatch
) -> None:
    """An accepted socket is not held open waiting for a frame that may never
    come."""
    monkeypatch.setattr(notifications_endpoint, "AUTH_TIMEOUT_SECONDS", 0.01)
    websocket = FakeWebSocket([])

    async def receive_bytes() -> bytes:
        await asyncio.sleep(60)
        raise AssertionError("should have timed out")

    monkeypatch.setattr(websocket, "receive_bytes", receive_bytes)
    await websocket_notifications(websocket)

    assert websocket.closed_with == WS_POLICY_VIOLATION
    assert websocket.sent == []


@pytest.mark.unit
async def test_hanging_up_before_authenticating_registers_nothing(stream) -> None:
    websocket = FakeWebSocket([])

    await websocket_notifications(websocket)

    assert websocket.accepted
    assert websocket.closed_with is None
