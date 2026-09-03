"""The bus against a real Postgres, not a stand-in.

Everything else about the cross-worker half is tested with the transport
mocked out, which proves the wiring and not the mechanism. This one opens an
actual ``LISTEN``, sends an actual ``NOTIFY`` from a second connection, and
asserts a socket on this side received it — the two-worker shape, with the
database in the middle doing the part we are trusting it for.

It runs against the suite's own database over a direct connection.
``LISTEN`` is session state and cannot survive a pool that hands out a
different backend per transaction, so an address that pools that way skips
rather than fails — with a reason, so a skip is never mistaken for a pass.
"""

import asyncio
import json

import asyncpg
import pytest

from conftest import TEST_DATABASE_URL
from app.core.config import settings
from app.services.platform import user_stream, user_stream_bus
from app.services.platform.user_stream import UserStream


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)


async def _wait_for(predicate, timeout: float = 5.0) -> bool:
    """Poll until true or the timeout — delivery is asynchronous by nature."""
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.05)
    return False


@pytest.mark.integration
async def test_a_frame_crosses_between_two_connections(monkeypatch) -> None:
    stream = UserStream()
    monkeypatch.setattr(user_stream, "stream", stream)
    monkeypatch.setattr(settings, "DATABASE_URL_LISTEN", TEST_DATABASE_URL)

    tab = FakeWebSocket()
    await stream.connect(7, tab)

    bus = user_stream_bus.UserStreamBus()
    await bus.start()
    try:
        if not await _wait_for(lambda: bus.running, timeout=10.0):
            pytest.skip(
                "this address cannot hold a LISTEN (a transaction pooler); "
                "the round trip is unverified here"
            )

        # A second connection standing in for another worker: a different
        # origin, so our listener must not filter it out.
        other = await asyncpg.connect(dsn=user_stream_bus._dsn())
        try:
            await other.execute(
                "SELECT pg_notify($1, $2)",
                user_stream.CHANNEL,
                json.dumps(
                    {
                        "origin": "a-different-worker",
                        "user_id": 7,
                        "frame": user_stream.build_frame("account", "membership"),
                    }
                ),
            )
        finally:
            await other.close()

        assert await _wait_for(lambda: len(tab.sent) == 1), (
            "no frame arrived over the bus"
        )
        assert tab.sent[0]["resource"] == "account"
        assert tab.sent[0]["ids"] == {}
    finally:
        await bus.stop()


@pytest.mark.integration
async def test_our_own_publish_does_not_come_back_around(monkeypatch) -> None:
    """The dedupe, end to end: publish delivers locally exactly once.

    Our own listener sees the echo and must drop it — otherwise every frame on
    a single-worker install would arrive twice.
    """
    stream = UserStream()
    monkeypatch.setattr(user_stream, "stream", stream)
    monkeypatch.setattr(settings, "DATABASE_URL_LISTEN", TEST_DATABASE_URL)

    tab = FakeWebSocket()
    await stream.connect(7, tab)

    bus = user_stream_bus.UserStreamBus()
    monkeypatch.setattr(user_stream_bus, "bus", bus)
    await bus.start()
    try:
        if not await _wait_for(lambda: bus.running, timeout=10.0):
            pytest.skip("this address cannot hold a LISTEN (a transaction pooler)")

        await user_stream.publish(7, user_stream.build_frame("account", "membership"))

        # Give the echo every chance to arrive before claiming it did not.
        await asyncio.sleep(0.5)
        assert len(tab.sent) == 1
    finally:
        await bus.stop()


@pytest.mark.integration
async def test_a_burst_of_frames_all_reach_the_bus(monkeypatch) -> None:
    """The fan-out shape: many frames published at once, none lost.

    A connection performs one operation at a time, and the after-commit hook
    spawns a task per frame — so listing a community publishes a frame per
    member concurrently. Unserialized, all but the first are refused, and the
    caller treats a refused send as "no cross-process delivery" and moves on:
    the frames disappear without a trace. This is the test that sees that.
    """
    monkeypatch.setattr(settings, "DATABASE_URL_LISTEN", TEST_DATABASE_URL)

    bus = user_stream_bus.UserStreamBus()
    await bus.start()
    try:
        if not await _wait_for(lambda: bus.running, timeout=10.0):
            pytest.skip("this address cannot hold a LISTEN (a transaction pooler)")

        results = await asyncio.gather(
            *[
                bus.notify(json.dumps({"origin": "another", "user_id": n, "frame": {}}))
                for n in range(25)
            ],
            return_exceptions=True,
        )

        failures = [r for r in results if isinstance(r, Exception)]
        assert failures == [], f"{len(failures)} of 25 frames never reached the bus"
    finally:
        await bus.stop()


@pytest.mark.integration
async def test_a_community_listing_reaches_every_member_on_another_worker(
    monkeypatch,
) -> None:
    """The fan-out, end to end: each member's socket gets exactly one frame."""
    stream = UserStream()
    monkeypatch.setattr(user_stream, "stream", stream)
    monkeypatch.setattr(settings, "DATABASE_URL_LISTEN", TEST_DATABASE_URL)

    tabs = {}
    for user_id in range(1, 16):
        tab = FakeWebSocket()
        await stream.connect(user_id, tab)
        tabs[user_id] = tab

    bus = user_stream_bus.UserStreamBus()
    monkeypatch.setattr(user_stream_bus, "bus", bus)
    await bus.start()
    try:
        if not await _wait_for(lambda: bus.running, timeout=10.0):
            pytest.skip("this address cannot hold a LISTEN (a transaction pooler)")

        # Published as the after-commit hook does it: one task per member.
        await asyncio.gather(
            *[
                user_stream.publish(
                    user_id, user_stream.build_frame("account", "community")
                )
                for user_id in tabs
            ]
        )

        assert await _wait_for(
            lambda: all(len(tab.sent) == 1 for tab in tabs.values())
        ), {user_id: len(tab.sent) for user_id, tab in tabs.items()}
    finally:
        await bus.stop()
