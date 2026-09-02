"""The per-user socket: which frames reach which tabs.

The routing half of the shared transport, pinned here because both channels
ride it — the inbox and the account. What each frame *means* belongs to the
channel that sends it.
"""

import pytest

from app.services.platform.user_stream import UserStream


class FakeWebSocket:
    """Minimal stand-in that records the JSON frames it was sent."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)


class BrokenWebSocket(FakeWebSocket):
    """A socket whose peer has gone away."""

    async def send_json(self, message: dict) -> None:
        raise ConnectionResetError("peer gone")


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_frame_reaches_every_tab_of_its_recipient() -> None:
    stream = UserStream()
    laptop, phone = FakeWebSocket(), FakeWebSocket()
    await stream.connect(7, laptop)
    await stream.connect(7, phone)

    await stream.send(7, {"resource": "notification"})

    assert laptop.sent == [{"resource": "notification"}]
    assert phone.sent == [{"resource": "notification"}]


@pytest.mark.unit
async def test_frame_never_reaches_another_user() -> None:
    stream = UserStream()
    mine, theirs = FakeWebSocket(), FakeWebSocket()
    await stream.connect(7, mine)
    await stream.connect(8, theirs)

    await stream.send(7, {"resource": "notification"})

    assert len(mine.sent) == 1
    assert theirs.sent == []


@pytest.mark.unit
async def test_disconnect_drops_only_that_socket() -> None:
    stream = UserStream()
    laptop, phone = FakeWebSocket(), FakeWebSocket()
    await stream.connect(7, laptop)
    await stream.connect(7, phone)

    await stream.disconnect(laptop)
    await stream.send(7, {"resource": "notification"})

    assert laptop.sent == []
    assert len(phone.sent) == 1
    assert stream.socket_count(7) == 1


@pytest.mark.unit
async def test_last_socket_leaving_empties_the_user() -> None:
    stream = UserStream()
    tab = FakeWebSocket()
    await stream.connect(7, tab)
    await stream.disconnect(tab)

    assert stream.socket_count(7) == 0
    # Idempotent: a socket the endpoint's ``finally`` already removed.
    await stream.disconnect(tab)
    assert stream.socket_count(7) == 0


@pytest.mark.unit
async def test_a_dead_socket_is_dropped_and_does_not_block_the_others() -> None:
    stream = UserStream()
    dead, alive = BrokenWebSocket(), FakeWebSocket()
    await stream.connect(7, dead)
    await stream.connect(7, alive)

    await stream.send(7, {"resource": "notification"})

    assert len(alive.sent) == 1
    assert stream.socket_count(7) == 1
