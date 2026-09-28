"""The per-user channel: which frames reach which tabs, and how they leave.

The routing half of the shared transport, pinned here because every channel
rides it — the inbox, the account, contacts and direct messages. What each
frame *means* belongs to the channel that sends it.
"""

import asyncio
import json

import pytest

from app.services.platform import notify_bus, user_stream
from app.testing.sockets import FakeWebSocket, settle


class BrokenWebSocket(FakeWebSocket):
    """A socket whose peer has gone away."""

    async def send_json(self, message: dict) -> None:
        raise ConnectionResetError("peer gone")


class StalledWebSocket(FakeWebSocket):
    """A socket whose reader has stopped reading."""

    async def send_json(self, message: dict) -> None:
        await asyncio.Event().wait()


@pytest.fixture
def notices(monkeypatch) -> list[dict]:
    """What this worker put on the bus for the others."""
    sent: list[dict] = []

    async def _capture(_channel: str, payload: str) -> None:
        sent.append(json.loads(payload))

    monkeypatch.setattr(notify_bus, "notify", _capture)
    return sent


def _frame() -> dict:
    return user_stream.build_frame("notification", "created")


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


async def test_frame_reaches_every_tab_of_its_recipient(
    account_socket, notices
) -> None:
    laptop, phone = account_socket(7), account_socket(7)

    await user_stream.publish([7], _frame())
    await settle()

    assert [f["resource"] for f in laptop.sent] == ["notification"]
    assert [f["resource"] for f in phone.sent] == ["notification"]


async def test_frame_never_reaches_another_user(account_socket, notices) -> None:
    mine, theirs = account_socket(7), account_socket(8)

    await user_stream.publish([7], _frame())
    await settle()

    assert len(mine.sent) == 1
    assert theirs.sent == []


async def test_a_dead_socket_does_not_block_the_others(account_socket, notices) -> None:
    account_socket(7, BrokenWebSocket())
    alive = account_socket(7)

    await user_stream.publish([7], _frame())
    await settle()

    assert len(alive.sent) == 1


async def test_a_stalled_reader_holds_nobody_up(account_socket, notices) -> None:
    """Publishing queues on each socket and returns: a reader that stopped
    reading costs its own outbox, not the sender or the other tabs."""
    account_socket(7, StalledWebSocket())
    alive = account_socket(8)

    await asyncio.wait_for(user_stream.publish([7, 8], _frame()), timeout=1)
    await settle()

    assert len(alive.sent) == 1


# ---------------------------------------------------------------------------
# Leaving on commit
# ---------------------------------------------------------------------------


async def test_one_transaction_is_one_notice_per_kind_of_frame(
    session, notices
) -> None:
    """Frames that say the same thing leave together, naming every reader;
    frames that say different things leave apart."""
    for user_id in (1, 2, 3):
        user_stream.queue_frame(session, user_id, _frame())
    user_stream.queue_frame(session, 2, user_stream.build_frame("account", "changed"))

    await session.commit()
    await asyncio.gather(*user_stream._inflight)

    assert sorted(
        (notice["frame"]["resource"], notice["user_ids"]) for notice in notices
    ) == [("account", [2]), ("notification", [1, 2, 3])]


async def test_a_large_audience_is_split_across_notices(
    session, notices, monkeypatch
) -> None:
    monkeypatch.setattr(user_stream, "IDS_PER_NOTICE", 2)
    for user_id in range(1, 6):
        user_stream.queue_frame(session, user_id, _frame())

    await session.commit()
    await asyncio.gather(*user_stream._inflight)

    assert [notice["user_ids"] for notice in notices] == [[1, 2], [3, 4], [5]]
