"""The notice worker: a notice waits for the request that caused it, is
delivered once, says no more than the community allows, and a push nobody
answered is tried again without a second bell line."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.notification_categories import category_of
from app.db.request_context import SystemGuild, Unattributed
from app.db.session import set_rls_context
from app.models.platform.notice_outbox import NoticeOutboxItem
from app.models.platform.notification import Notification, NotificationType
from app.services import notifications
from app.services.platform import (
    email_outbox,
    notice_outbox,
    notification_policy,
    push_notifications,
)
from app.testing import (
    create_guild,
    create_push_token,
    create_user,
    push_switched_on,
)


@pytest.fixture
def fcm(monkeypatch):
    """FCM, answering however the test says, and what was put on the wire."""
    calls: list[str] = []
    answer = {"now": (True, False)}

    async def _send(client, push_token, title, body, data=None, channel_id=None):
        calls.append(title)
        return answer["now"]

    monkeypatch.setattr(push_notifications, "send_push_notification", _send)
    with push_switched_on():
        yield calls, answer


async def _mention(session: AsyncSession, guild_id: int, recipient, actor) -> None:
    await set_rls_context(session, SystemGuild(guild_id))
    await notifications.notify(
        session,
        NotificationType.mention,
        [recipient.id],
        about=None,
        key="mention.comment",
        values={"actor": "Ana", "context": "Q3 budget"},
        actor=actor,
    )


async def _deliver(session: AsyncSession, at: datetime) -> None:
    await set_rls_context(session, Unattributed())
    await notice_outbox._run_pass(session, now=at)


async def _lines(session: AsyncSession, user_id: int) -> list[Notification]:
    await set_rls_context(session, Unattributed())
    rows = await session.exec(
        select(Notification).where(Notification.user_id == user_id)
    )
    return list(rows.all())


async def _waiting(session: AsyncSession) -> list[NoticeOutboxItem]:
    await set_rls_context(session, Unattributed())
    return list((await session.exec(select(NoticeOutboxItem))).all())


async def test_a_notice_is_delivered_once_and_only_if_its_request_commits(
    session: AsyncSession, fcm, monkeypatch
):
    pushed, _answer = fcm
    mailed: list[tuple[int, int | None]] = []

    async def _mail(_session, recipient, *, notification_id=None, **_rest):
        mailed.append((recipient.id, notification_id))
        return True

    monkeypatch.setattr(email_outbox, "enqueue", _mail)
    actor = await create_user(session)
    recipient = await create_user(session)
    guild = await create_guild(session, creator=actor)
    await create_push_token(session, recipient)
    await session.commit()
    guild_id = guild.id

    # A request that rolls back tells nobody.
    await _mention(session, guild_id, recipient, actor)
    await session.rollback()
    await set_rls_context(session, Unattributed())
    for user in (recipient, actor):
        await session.refresh(user)
    await _deliver(session, datetime.now(timezone.utc))
    assert await _lines(session, recipient.id) == []
    assert pushed == [] and mailed == []

    await _mention(session, guild_id, recipient, actor)
    await session.commit()
    await _deliver(session, datetime.now(timezone.utc))
    await _deliver(session, datetime.now(timezone.utc))

    [line] = await _lines(session, recipient.id)
    assert mailed == [(recipient.id, line.id)]
    assert pushed == ["You were mentioned"]
    assert await _waiting(session) == []


async def test_a_redacting_community_writes_down_no_more_than_it_will_say(
    session: AsyncSession,
):
    actor = await create_user(session)
    recipient = await create_user(session)
    guild = await create_guild(session, creator=actor)
    guild.redact_notification_content = True
    session.add(guild)
    await session.commit()

    with push_switched_on():
        await _mention(session, guild.id, recipient, actor)
    await session.commit()

    [row] = await _waiting(session)
    title, body = notification_policy.redacted_push(NotificationType.mention, "en")
    assert (row.push_title, row.push_body) == (title, body)
    assert row.email_subject == notification_policy.redacted_subject(
        category_of(NotificationType.mention), "en"
    )
    assert "Q3 budget" not in f"{row.push_body} {row.email_body} {row.email_subject}"


async def test_a_push_nobody_answered_is_tried_again_without_a_second_line(
    session: AsyncSession, fcm
):
    """…and given up once its attempts are spent."""
    pushed, answer = fcm
    actor = await create_user(session)
    recipient = await create_user(session)
    guild = await create_guild(session, creator=actor)
    await create_push_token(session, recipient)
    answer["now"] = (False, False)
    await _mention(session, guild.id, recipient, actor)
    await session.commit()
    start = datetime.now(timezone.utc)
    await _deliver(session, start)
    [row] = await _waiting(session)
    assert row.attempts == 1 and row.bell_written_at is not None
    await _deliver(session, start)  # not due yet
    assert len(pushed) == 1

    answer["now"] = (True, False)
    await _deliver(session, start + timedelta(seconds=31))
    assert len(pushed) == 2
    assert await _waiting(session) == []
    assert len(await _lines(session, recipient.id)) == 1

    answer["now"] = (False, False)
    await _mention(session, guild.id, recipient, actor)
    await session.commit()
    at = start + timedelta(seconds=31)
    for wait in notice_outbox.BACKOFF_SECONDS:
        await _deliver(session, at)
        at += timedelta(seconds=wait + 1)
    assert await _waiting(session) == []
    assert len(pushed) == 2 + len(notice_outbox.BACKOFF_SECONDS)
    assert len(await _lines(session, recipient.id)) == 2
