"""The notification bell's push socket — the handshake and its bookkeeping.

The bell no longer polls, so this socket is the only thing standing between a
notification landing and a user seeing it. What matters here is that it
registers exactly the sockets it authenticated, and nothing else: an
unauthenticated socket that ended up in the registry would be handed the
recipient's "your inbox changed" pokes, and an authenticated one that never
left it would keep a dead peer in every fan-out.

The socket is driven directly rather than over the wire — the HTTP test client
here is ``httpx``, which speaks no WebSocket — with a stand-in that records what
the endpoint did to it.
"""

import pytest
from fastapi import WebSocketDisconnect
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.v1.platform_endpoints import notifications as notifications_endpoint
from app.api.v1.platform_endpoints.notifications import (
    MSG_AUTH,
    websocket_notifications,
)
from app.core.security import SESSION_COOKIE_NAME
from app.services.platform import notification_stream
from app.services.platform.notification_stream import NotificationStream
from app.testing import create_user, get_auth_token

WS_POLICY_VIOLATION = 1008


class FakeWebSocket:
    """Drives the endpoint through one handshake, then hangs up.

    ``frames`` are the client's inbound frames; once they run out the socket
    raises ``WebSocketDisconnect`` from the keepalive loop, which is how a real
    client leaving arrives.
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

    async def receive_text(self) -> str:
        raise WebSocketDisconnect(code=1000)

    async def close(self, code: int = 1000) -> None:
        self.closed_with = code

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)


def _auth_frame(payload: bytes) -> bytes:
    return bytes([MSG_AUTH]) + payload


@pytest.fixture
def stream(monkeypatch) -> NotificationStream:
    """A registry of this test's own, so assertions see only its sockets."""
    fresh = NotificationStream()
    monkeypatch.setattr(notification_stream, "stream", fresh)
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

    async def receive_text() -> str:
        counted.append(stream.socket_count(user.id))
        raise WebSocketDisconnect(code=1000)

    monkeypatch.setattr(websocket, "receive_text", receive_text)
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

    async def receive_text() -> str:
        counted.append(stream.socket_count(user.id))
        raise WebSocketDisconnect(code=1000)

    monkeypatch.setattr(websocket, "receive_text", receive_text)
    await websocket_notifications(websocket)

    assert websocket.closed_with is None
    assert counted == [1]


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
async def test_hanging_up_before_authenticating_registers_nothing(stream) -> None:
    websocket = FakeWebSocket([])

    await websocket_notifications(websocket)

    assert websocket.accepted
    assert websocket.closed_with is None
