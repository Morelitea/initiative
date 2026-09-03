"""The contacts channel: who gets poked, and — mostly — who does not.

The channel is content-free, so what is worth asserting is the addressing. Half
of these are about an account that must hear nothing: a frame is as much a tell
as a notification, and an ignored account is told neither that it happened nor
that it was lifted.
"""

import asyncio
from typing import Any

import pytest

from app.models.platform.contact_grant import ContactGrantKind
from app.models.platform.user_dm_settings import DmPolicy
from app.models.platform.user_ignore import UserIgnore
from app.services.platform import contact_grants as contact_grants_service
from app.services.platform import contacts_stream, user_ignores, user_stream
from app.services.platform.user_stream import UserStream
from app.testing import create_user
from sqlalchemy import text

pytestmark = pytest.mark.asyncio


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)


async def _drain_tasks() -> None:
    """Let the after-commit hook's fire-and-forget sends finish."""
    for _ in range(3):
        await asyncio.sleep(0)


@pytest.fixture
def captured_stream(monkeypatch):
    stream = UserStream()
    monkeypatch.setattr(user_stream, "stream", stream)
    return stream


async def _socket_for(captured_stream, user) -> FakeWebSocket:
    socket = FakeWebSocket()
    await captured_stream.connect(user.id, socket)
    return socket


def _contacts_frames(socket: FakeWebSocket) -> list[dict]:
    return [f for f in socket.sent if f.get("resource") == contacts_stream.RESOURCE]


async def _as(session, user) -> None:
    await session.exec(
        text("SELECT set_config('app.current_user_id', :v, true)").bindparams(
            v=str(user.id)
        )
    )


async def _open(session, user, policy: DmPolicy = DmPolicy.public) -> None:
    await session.exec(
        text(
            "UPDATE public.user_dm_settings SET dm_policy = CAST(:p AS user_dm_policy) "
            "WHERE user_id = :u"
        ).bindparams(p=policy.value, u=user.id)
    )


async def test_a_request_pokes_both_parties(session, captured_stream):
    ada = await create_user(session)
    bram = await create_user(session)
    await _open(session, ada)
    await _open(session, bram)
    await session.commit()

    to_ada = await _socket_for(captured_stream, ada)
    to_bram = await _socket_for(captured_stream, bram)

    await _as(session, bram)
    await contact_grants_service.request(
        session, actor_id=bram.id, target_id=ada.id, kind=ContactGrantKind.connection
    )
    await _drain_tasks()

    assert _contacts_frames(to_ada), "the recipient is told there is something to see"
    assert _contacts_frames(to_bram), "and the requester that theirs is pending"


async def test_an_ignored_requester_pokes_only_themselves(session, captured_stream):
    """The row is stored and stays out of sight, so no frame says otherwise."""
    ada = await create_user(session)
    bram = await create_user(session)
    await _open(session, ada)
    await _open(session, bram)
    session.add(UserIgnore(user_id=ada.id, ignored_user_id=bram.id))
    await session.commit()

    to_ada = await _socket_for(captured_stream, ada)
    to_bram = await _socket_for(captured_stream, bram)

    await _as(session, bram)
    await contact_grants_service.request(
        session, actor_id=bram.id, target_id=ada.id, kind=ContactGrantKind.connection
    )
    await _drain_tasks()

    assert _contacts_frames(to_ada) == []
    assert _contacts_frames(to_bram), "and it looks entirely ordinary to them"


async def test_ignoring_pokes_the_holder_and_nobody_else(session, captured_stream):
    ada = await create_user(session)
    bram = await create_user(session)
    await session.commit()

    to_ada = await _socket_for(captured_stream, ada)
    to_bram = await _socket_for(captured_stream, bram)

    await user_ignores.add(session, user_id=ada.id, ignored_user_id=bram.id)
    await _drain_tasks()

    assert _contacts_frames(to_ada)
    assert _contacts_frames(to_bram) == []


async def test_lifting_an_ignore_pokes_the_holder_and_nobody_else(
    session, captured_stream
):
    """The other end of the same silence: stopping is as quiet as starting."""
    ada = await create_user(session)
    bram = await create_user(session)
    await user_ignores.add(session, user_id=ada.id, ignored_user_id=bram.id)
    await session.commit()

    to_ada = await _socket_for(captured_stream, ada)
    to_bram = await _socket_for(captured_stream, bram)

    await user_ignores.remove(session, user_id=ada.id, ignored_user_id=bram.id)
    await _drain_tasks()

    assert _contacts_frames(to_ada)
    assert _contacts_frames(to_bram) == []


async def test_the_frame_carries_nothing(session, captured_stream):
    ada = await create_user(session)
    bram = await create_user(session)
    await session.commit()
    to_ada = await _socket_for(captured_stream, ada)

    await user_ignores.add(session, user_id=ada.id, ignored_user_id=bram.id)
    await _drain_tasks()

    frame = _contacts_frames(to_ada)[0]
    assert frame["resource"] == "contacts"
    assert frame["ids"] == {}
    assert set(frame) == {"resource", "action", "ids", "timestamp"}


async def test_a_fan_out_publishes_for_everyone_it_names(
    session, captured_stream, monkeypatch
):
    """Not narrowed to this worker's own sockets.

    That narrowing would have to happen before ``publish``, which is also what
    puts a frame on the cross-worker bus — so an account connected only to
    another worker would never be published for. Here ``away`` stands in for
    that account: it holds no socket on this process, and the frame is still
    sent for it.
    """
    here = await create_user(session)
    away = await create_user(session)
    await session.commit()
    to_here = await _socket_for(captured_stream, here)

    published: list[int] = []

    async def _capture(user_id: int, frame: dict[str, Any]) -> None:
        published.append(user_id)
        await captured_stream.send(user_id, frame)

    monkeypatch.setattr(user_stream, "publish", _capture)

    contacts_stream.queue_many(session, [here.id, away.id])
    await session.commit()
    await _drain_tasks()

    assert _contacts_frames(to_here)
    assert set(published) == {here.id, away.id}
