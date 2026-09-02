"""The cross-worker half, and what happens when it is not there.

Two properties carry the design: a worker never delivers its own echo twice,
and a bus that cannot be reached costs cross-process delivery and nothing else.
"""

import json

import pytest

from app.core.config import settings
from app.services.platform import user_stream, user_stream_bus
from app.services.platform.user_stream import UserStream


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)


@pytest.fixture
def captured_stream(monkeypatch):
    stream = UserStream()
    monkeypatch.setattr(user_stream, "stream", stream)
    return stream


def _wire_frame(origin: str, user_id: int, action: str = "membership") -> str:
    return json.dumps(
        {
            "origin": origin,
            "user_id": user_id,
            "frame": user_stream.build_frame("account", action),
        }
    )


@pytest.mark.unit
async def test_a_frame_from_another_worker_reaches_our_sockets(
    captured_stream,
) -> None:
    tab = FakeWebSocket()
    await captured_stream.connect(7, tab)

    await user_stream.deliver_remote(_wire_frame("some-other-worker", 7))

    assert len(tab.sent) == 1
    assert tab.sent[0]["resource"] == "account"


@pytest.mark.unit
async def test_our_own_echo_is_not_delivered_twice(captured_stream) -> None:
    """We deliver locally before publishing, so the echo is already spent."""
    tab = FakeWebSocket()
    await captured_stream.connect(7, tab)

    await user_stream.deliver_remote(_wire_frame(user_stream.ORIGIN, 7))

    assert tab.sent == []


@pytest.mark.unit
async def test_an_unreadable_frame_is_dropped_not_raised(captured_stream) -> None:
    """Anything on the channel that is not ours must not take the reader down."""
    tab = FakeWebSocket()
    await captured_stream.connect(7, tab)

    await user_stream.deliver_remote("not json at all")
    await user_stream.deliver_remote(json.dumps({"origin": "x"}))

    assert tab.sent == []


@pytest.mark.unit
async def test_local_delivery_survives_a_bus_that_is_down(
    captured_stream, monkeypatch
) -> None:
    """The whole fail-soft claim, in one test.

    A deployment that cannot reach the bus behaves exactly as it did before the
    bus existed: every socket this process holds is still served.
    """

    async def _unavailable(_payload: str) -> None:
        raise RuntimeError("bus not connected")

    monkeypatch.setattr(user_stream_bus, "notify", _unavailable)
    tab = FakeWebSocket()
    await captured_stream.connect(7, tab)

    await user_stream.publish(7, user_stream.build_frame("account", "membership"))

    assert len(tab.sent) == 1


@pytest.mark.unit
async def test_a_published_frame_is_offered_to_the_other_workers(
    captured_stream, monkeypatch
) -> None:
    sent: list[str] = []

    async def _capture(payload: str) -> None:
        sent.append(payload)

    monkeypatch.setattr(user_stream_bus, "notify", _capture)

    await user_stream.publish(7, user_stream.build_frame("account", "membership"))

    assert len(sent) == 1
    envelope = json.loads(sent[0])
    assert envelope["user_id"] == 7
    assert envelope["origin"] == user_stream.ORIGIN
    # Content-free on the wire as well as at the socket.
    assert envelope["frame"]["ids"] == {}


@pytest.mark.unit
def test_the_listen_address_is_a_libpq_dsn(monkeypatch) -> None:
    """asyncpg is handed a plain postgresql:// URL, not SQLAlchemy's spelling."""
    monkeypatch.setattr(
        settings,
        "DATABASE_URL_LISTEN",
        "postgresql+asyncpg://someone:secret@db:5432/initiative",
    )
    assert user_stream_bus._dsn() == "postgresql://someone:secret@db:5432/initiative"


@pytest.mark.unit
def test_the_listen_address_defaults_to_the_database(monkeypatch) -> None:
    """Unset is the ordinary case: an app talking to Postgres directly."""
    monkeypatch.setattr(settings, "DATABASE_URL_LISTEN", None)
    monkeypatch.setattr(
        settings, "DATABASE_URL", "postgresql+asyncpg://a:b@localhost:5432/x"
    )
    assert user_stream_bus._dsn() == "postgresql://a:b@localhost:5432/x"


@pytest.mark.unit
async def test_notify_refuses_when_there_is_no_connection() -> None:
    """The caller treats this as 'no cross-process delivery', never a failure."""
    bus = user_stream_bus.UserStreamBus()
    assert not bus.running
    with pytest.raises(RuntimeError):
        await bus.notify("{}")
