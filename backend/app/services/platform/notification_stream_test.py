"""The per-user notification signal channel.

These pin the three properties the bell now depends on, having given up its
fast poll:

* a frame reaches every socket belonging to its recipient, and only those,
* a frame is emitted only after the writing transaction commits — never on
  flush, and never at all if the transaction rolls back,
* a frame stays content-free: an id envelope, never a notification's payload.
"""

import asyncio

import pytest
from sqlmodel import select

from app.models.platform.notification import Notification, NotificationType
from app.services.platform import notification_stream
from app.services.platform import user_notifications
from app.services.platform.notification_stream import (
    NotificationStream,
    queue_signal,
    signal_user,
)
from app.testing import create_user


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
    stream = NotificationStream()
    laptop, phone = FakeWebSocket(), FakeWebSocket()
    await stream.connect(7, laptop)
    await stream.connect(7, phone)

    await stream.send(7, {"resource": "notification"})

    assert laptop.sent == [{"resource": "notification"}]
    assert phone.sent == [{"resource": "notification"}]


@pytest.mark.unit
async def test_frame_never_reaches_another_user() -> None:
    stream = NotificationStream()
    mine, theirs = FakeWebSocket(), FakeWebSocket()
    await stream.connect(7, mine)
    await stream.connect(8, theirs)

    await stream.send(7, {"resource": "notification"})

    assert len(mine.sent) == 1
    assert theirs.sent == []


@pytest.mark.unit
async def test_disconnect_drops_only_that_socket() -> None:
    stream = NotificationStream()
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
    stream = NotificationStream()
    tab = FakeWebSocket()
    await stream.connect(7, tab)
    await stream.disconnect(tab)

    assert stream.socket_count(7) == 0
    # Idempotent: a socket the endpoint's ``finally`` already removed.
    await stream.disconnect(tab)
    assert stream.socket_count(7) == 0


@pytest.mark.unit
async def test_a_dead_socket_is_dropped_and_does_not_block_the_others() -> None:
    stream = NotificationStream()
    dead, alive = BrokenWebSocket(), FakeWebSocket()
    await stream.connect(7, dead)
    await stream.connect(7, alive)

    await stream.send(7, {"resource": "notification"})

    assert len(alive.sent) == 1
    assert stream.socket_count(7) == 1


@pytest.mark.unit
async def test_frame_carries_no_notification_content() -> None:
    """An id envelope, and the inbox needs no ids — so nothing but the shape."""
    stream = NotificationStream()
    tab = FakeWebSocket()
    await stream.connect(7, tab)
    original = notification_stream.stream
    notification_stream.stream = stream
    try:
        await signal_user(7, "created")
    finally:
        notification_stream.stream = original

    frame = tab.sent[0]
    assert frame["resource"] == "notification"
    assert frame["action"] == "created"
    assert frame["ids"] == {}
    assert set(frame) == {"resource", "action", "ids", "timestamp"}


# ---------------------------------------------------------------------------
# Commit coupling
# ---------------------------------------------------------------------------


async def _drain_tasks() -> None:
    """Let the fire-and-forget send tasks the commit hook spawned run."""
    for _ in range(3):
        await asyncio.sleep(0)


@pytest.fixture
def captured_stream(monkeypatch):
    """Route the module-level stream at a fresh instance for one test."""
    stream = NotificationStream()
    monkeypatch.setattr(notification_stream, "stream", stream)
    return stream


@pytest.mark.integration
async def test_no_frame_before_the_commit(session, captured_stream) -> None:
    """A flushed-but-uncommitted notification must not poke anyone: the client
    would refetch an inbox that does not yet contain it, and nothing polls
    behind the signal any more."""
    user = await create_user(session)
    tab = FakeWebSocket()
    await captured_stream.connect(user.id, tab)

    await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.task_assignment,
        data={"task_id": 1},
    )
    await _drain_tasks()

    assert tab.sent == []


@pytest.mark.integration
async def test_frame_goes_out_on_commit(session, captured_stream) -> None:
    user = await create_user(session)
    tab = FakeWebSocket()
    await captured_stream.connect(user.id, tab)

    await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.task_assignment,
        data={"task_id": 1},
    )
    await session.commit()
    await _drain_tasks()

    assert [frame["action"] for frame in tab.sent] == ["created"]


@pytest.mark.integration
async def test_rollback_pokes_nobody(session, captured_stream) -> None:
    user = await create_user(session)
    tab = FakeWebSocket()
    await captured_stream.connect(user.id, tab)

    await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.task_assignment,
        data={"task_id": 1},
    )
    await session.rollback()
    await _drain_tasks()

    assert tab.sent == []


@pytest.mark.integration
async def test_several_notifications_in_one_transaction_send_one_frame(
    session, captured_stream
) -> None:
    """The frame says "refetch", so a batch of notifications for one recipient
    is one refetch, not one per row."""
    user = await create_user(session)
    tab = FakeWebSocket()
    await captured_stream.connect(user.id, tab)

    for task_id in (1, 2, 3):
        await user_notifications.create_notification(
            session,
            user_id=user.id,
            notification_type=NotificationType.task_assignment,
            data={"task_id": task_id},
        )
    await session.commit()
    await _drain_tasks()

    assert len(tab.sent) == 1


@pytest.mark.integration
async def test_a_batch_pokes_each_recipient_once(session, captured_stream) -> None:
    alice = await create_user(session)
    bob = await create_user(session)
    alice_tab, bob_tab = FakeWebSocket(), FakeWebSocket()
    await captured_stream.connect(alice.id, alice_tab)
    await captured_stream.connect(bob.id, bob_tab)

    for user_id in (alice.id, bob.id, alice.id):
        await user_notifications.create_notification(
            session,
            user_id=user_id,
            notification_type=NotificationType.task_assignment,
            data={"task_id": 1},
        )
    await session.commit()
    await _drain_tasks()

    assert len(alice_tab.sent) == 1
    assert len(bob_tab.sent) == 1


@pytest.mark.integration
async def test_marking_read_pokes_the_users_other_tabs(
    session, captured_stream
) -> None:
    """The badge on a second device is otherwise stale until something else
    happens."""
    user = await create_user(session)
    notification = await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.task_assignment,
        data={"task_id": 1},
    )
    await session.commit()
    await _drain_tasks()  # let the "created" frame go out before we listen

    tab = FakeWebSocket()
    await captured_stream.connect(user.id, tab)
    await user_notifications.mark_notification_read(
        session, user_id=user.id, notification_id=notification.id
    )
    await _drain_tasks()

    assert [frame["action"] for frame in tab.sent] == ["read"]


@pytest.mark.integration
async def test_mark_all_read_pokes_once(session, captured_stream) -> None:
    user = await create_user(session)
    for task_id in (1, 2):
        await user_notifications.create_notification(
            session,
            user_id=user.id,
            notification_type=NotificationType.task_assignment,
            data={"task_id": task_id},
        )
    await session.commit()
    await _drain_tasks()  # let the "created" frame go out before we listen

    tab = FakeWebSocket()
    await captured_stream.connect(user.id, tab)
    await user_notifications.mark_all_notifications_read(session, user_id=user.id)
    await _drain_tasks()

    assert [frame["action"] for frame in tab.sent] == ["read"]
    unread = (
        await session.exec(
            select(Notification).where(
                Notification.user_id == user.id,
                Notification.read_at.is_(None),
            )
        )
    ).all()
    assert unread == []


@pytest.mark.integration
async def test_rolling_a_line_up_pokes_the_recipient(session, captured_stream) -> None:
    """A rolled-up reaction rewrites the existing line rather than adding one,
    so the rewrite is the only trace the second event leaves — and with no poll
    behind the signal, an unsignalled rewrite is an invisible one."""
    user = await create_user(session)
    notification = await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.comment_reaction,
        data={"target_id": 7, "count": 1},
    )
    await session.commit()
    await _drain_tasks()

    tab = FakeWebSocket()
    await captured_stream.connect(user.id, tab)
    await user_notifications.refresh_notification(
        session, notification, data={"target_id": 7, "count": 2}
    )
    await session.commit()
    await _drain_tasks()

    assert [frame["action"] for frame in tab.sent] == ["updated"]


@pytest.mark.integration
async def test_a_withdrawal_pokes_without_claiming_to_be_news(
    session, captured_stream
) -> None:
    user = await create_user(session)
    notification = await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.comment_reaction,
        data={"target_id": 7, "count": 2},
    )
    await session.commit()
    await _drain_tasks()

    tab = FakeWebSocket()
    await captured_stream.connect(user.id, tab)
    await user_notifications.refresh_notification(
        session, notification, data={"target_id": 7, "count": 1}, bump=False
    )
    await session.commit()
    await _drain_tasks()

    assert [frame["action"] for frame in tab.sent] == ["withdrawn"]


@pytest.mark.integration
async def test_deleting_a_line_pokes_the_recipient(session, captured_stream) -> None:
    """The last reaction being taken back removes the line outright; a bell
    still showing it is what this prevents."""
    user = await create_user(session)
    notification = await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.comment_reaction,
        data={"target_id": 7, "count": 1},
    )
    await session.commit()
    await _drain_tasks()

    tab = FakeWebSocket()
    await captured_stream.connect(user.id, tab)
    await user_notifications.delete_notification(session, notification)
    await session.commit()
    await _drain_tasks()

    assert [frame["action"] for frame in tab.sent] == ["withdrawn"]


@pytest.mark.unit
async def test_queue_signal_ignores_a_missing_recipient() -> None:
    """Defensive: a caller with no user id queues nothing rather than erroring
    inside someone else's transaction."""

    class Session:
        info: dict = {}

    session = Session()
    queue_signal(session, None)
    assert session.info == {}
