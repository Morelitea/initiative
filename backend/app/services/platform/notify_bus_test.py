"""The cross-worker half, and what happens when it is not there.

Two properties carry the design: a worker never delivers its own echo twice,
and a bus that cannot be reached costs cross-process delivery and nothing else.
"""

import json

import pytest

from app.core.config import settings
from app.services.platform import notify_bus, user_stream
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

    async def _unavailable(_channel: str, _payload: str) -> None:
        raise RuntimeError("bus not connected")

    monkeypatch.setattr(notify_bus, "notify", _unavailable)
    tab = FakeWebSocket()
    await captured_stream.connect(7, tab)

    await user_stream.publish(7, user_stream.build_frame("account", "membership"))

    assert len(tab.sent) == 1


@pytest.mark.unit
async def test_a_published_frame_is_offered_to_the_other_workers(
    captured_stream, monkeypatch
) -> None:
    sent: list[str] = []

    async def _capture(_channel: str, payload: str) -> None:
        sent.append(payload)

    monkeypatch.setattr(notify_bus, "notify", _capture)

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
    assert notify_bus._dsn() == "postgresql://someone:secret@db:5432/initiative"


@pytest.mark.unit
def test_the_listen_address_defaults_to_the_database(monkeypatch) -> None:
    """Unset is the ordinary case: an app talking to Postgres directly."""
    monkeypatch.setattr(settings, "DATABASE_URL_LISTEN", None)
    monkeypatch.setattr(
        settings, "DATABASE_URL", "postgresql+asyncpg://a:b@localhost:5432/x"
    )
    assert notify_bus._dsn() == "postgresql://a:b@localhost:5432/x"


@pytest.mark.unit
async def test_notify_refuses_when_there_is_no_connection() -> None:
    """The caller treats this as 'no cross-process delivery', never a failure."""
    bus = notify_bus.NotifyBus()
    assert not bus.running
    with pytest.raises(RuntimeError):
        await bus.notify(user_stream.CHANNEL, "{}")


# ---------------------------------------------------------------------------
# Coming back up
# ---------------------------------------------------------------------------
#
# Delivery is at-most-once, so a bus that was down is a gap in both directions:
# what this process tried to send was refused, and what it would have heard went
# past with nobody listening. Coming up is the only notice of either.


@pytest.mark.unit
async def test_subscribers_are_told_when_the_bus_comes_up() -> None:
    bus = notify_bus.NotifyBus()
    calls: list[str] = []

    async def _woke() -> None:
        calls.append("up")

    bus.register("a-channel", lambda _payload: _noop(), on_connect=_woke)
    await bus._announce_connected()

    assert calls == ["up"]


@pytest.mark.unit
async def test_one_subscriber_failing_does_not_silence_the_rest() -> None:
    """A subscriber's own catch-up is its business; the bus is up either way."""
    bus = notify_bus.NotifyBus()
    calls: list[str] = []

    async def _raises() -> None:
        raise RuntimeError("catch-up failed")

    async def _works() -> None:
        calls.append("up")

    bus.register("first", lambda _payload: _noop(), on_connect=_raises)
    bus.register("second", lambda _payload: _noop(), on_connect=_works)
    await bus._announce_connected()

    assert calls == ["up"]


async def _noop() -> None:
    return None


@pytest.mark.unit
async def test_a_refused_frame_is_sent_when_the_bus_returns(monkeypatch) -> None:
    """The far side is waiting on a signal that was dropped, not delayed."""
    user_stream._pending_remote.clear()
    sent: list[str] = []

    async def _unavailable(_channel: str, _payload: str) -> None:
        raise RuntimeError("bus not connected")

    monkeypatch.setattr(notify_bus, "notify", _unavailable)
    await user_stream.publish(7, user_stream.build_frame("notification", "created"))
    assert len(user_stream._pending_remote) == 1

    async def _capture(_channel: str, payload: str) -> None:
        sent.append(payload)

    monkeypatch.setattr(notify_bus, "notify", _capture)
    await user_stream.on_bus_connected()

    assert len(sent) == 1
    assert json.loads(sent[0])["user_id"] == 7
    assert user_stream._pending_remote == {}


@pytest.mark.unit
async def test_repeat_frames_for_one_reader_collapse(monkeypatch) -> None:
    """They carry no content, so "your inbox changed" twice is once."""
    user_stream._pending_remote.clear()

    async def _unavailable(_channel: str, _payload: str) -> None:
        raise RuntimeError("bus not connected")

    monkeypatch.setattr(notify_bus, "notify", _unavailable)
    for _ in range(5):
        await user_stream.publish(7, user_stream.build_frame("notification", "created"))

    assert len(user_stream._pending_remote) == 1
    user_stream._pending_remote.clear()


@pytest.mark.unit
async def test_this_process_own_sockets_are_told_to_re_read(monkeypatch) -> None:
    """It heard nothing while it was away and cannot know what, so it says so."""
    user_stream._pending_remote.clear()
    stream = user_stream.UserStream()
    monkeypatch.setattr(user_stream, "stream", stream)
    tab = FakeWebSocket()
    await stream.connect(7, tab)

    await user_stream.on_bus_connected()

    assert [frame["resource"] for frame in tab.sent] == [user_stream.RESOURCE_RESYNC]
    assert tab.sent[0]["ids"] == {}


@pytest.mark.unit
async def test_more_refused_than_can_be_held_tells_everybody(monkeypatch) -> None:
    """Past the bound the frames were never kept, so whose they were cannot be
    said — and a reader on another worker has no timer behind it any more."""
    user_stream._pending_remote.clear()
    monkeypatch.setattr(user_stream, "_dropped_remote", False)
    monkeypatch.setattr(user_stream, "MAX_PENDING_REMOTE", 2)

    async def _unavailable(_channel: str, _payload: str) -> None:
        raise RuntimeError("bus not connected")

    monkeypatch.setattr(notify_bus, "notify", _unavailable)
    for reader in range(5):
        await user_stream.publish(
            reader, user_stream.build_frame("notification", "created")
        )

    sent: list[dict] = []

    async def _capture(_channel: str, payload: str) -> None:
        sent.append(json.loads(payload))

    monkeypatch.setattr(notify_bus, "notify", _capture)
    await user_stream.on_bus_connected()

    addressed_to_everyone = [message for message in sent if message["user_id"] is None]
    assert len(addressed_to_everyone) == 1
    assert addressed_to_everyone[0]["frame"]["resource"] == user_stream.RESOURCE_RESYNC
    user_stream._pending_remote.clear()


@pytest.mark.unit
async def test_a_frame_for_everybody_reaches_every_socket_here(monkeypatch) -> None:
    stream = user_stream.UserStream()
    monkeypatch.setattr(user_stream, "stream", stream)
    first, second = FakeWebSocket(), FakeWebSocket()
    await stream.connect(7, first)
    await stream.connect(8, second)

    await user_stream.deliver_remote(
        json.dumps(
            {
                "origin": "another-worker",
                "user_id": None,
                "frame": user_stream.build_frame(
                    user_stream.RESOURCE_RESYNC, "changed"
                ),
            }
        )
    )

    assert len(first.sent) == 1
    assert len(second.sent) == 1


@pytest.mark.unit
async def test_the_mark_stands_until_the_broad_frame_goes(monkeypatch) -> None:
    """A bus that fails again while this is recovering must not consume it.

    The refused frames survive that by re-queueing; the mark that says frames
    were dropped has nowhere to be re-queued, so it is cleared on success only.
    """
    user_stream._pending_remote.clear()
    monkeypatch.setattr(user_stream, "_dropped_remote", True)

    async def _unavailable(_channel: str, _payload: str) -> None:
        raise RuntimeError("bus not connected")

    monkeypatch.setattr(notify_bus, "notify", _unavailable)
    await user_stream.on_bus_connected()

    assert user_stream._dropped_remote is True

    sent: list[dict] = []

    async def _capture(_channel: str, payload: str) -> None:
        sent.append(json.loads(payload))

    monkeypatch.setattr(notify_bus, "notify", _capture)
    await user_stream.on_bus_connected()

    assert [message["user_id"] for message in sent] == [None]
    assert user_stream._dropped_remote is False
