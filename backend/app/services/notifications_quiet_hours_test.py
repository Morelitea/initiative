"""Quiet hours: suppress overnight, then say what happened once.

The suppression is a predicate next to the preference check. The summary is a
query, not a queue — everything held back is already in the inbox, unread and
stamped inside the window, so there is nothing else to record.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.notification import NotificationType
from app.services.notifications import _run_quiet_hours_summary_pass
from app.services.platform import notification_prefs, user_notifications
from app.testing import create_guild, create_user, set_notification_prefs

NIGHT = {"quiet_hours": {"start": "22:00", "end": "07:00"}}


def _at(hour: int, day: int = 9) -> datetime:
    return datetime(2026, 9, day, hour, 0, tzinfo=timezone.utc)


@pytest.mark.unit
def test_a_window_still_running_has_nothing_to_summarise():
    assert (
        notification_prefs.last_window_close(NIGHT, tz_name="UTC", now=_at(23)) is None
    )


@pytest.mark.unit
def test_the_window_that_just_closed_is_found():
    window = notification_prefs.last_window_close(NIGHT, tz_name="UTC", now=_at(8))
    assert window is not None
    opened, closed = window
    assert closed == _at(7)
    # Overnight: it opened the evening before.
    assert opened == _at(22, day=8)


@pytest.mark.unit
def test_a_long_past_window_is_not_summarised():
    """A "while you were asleep" about the night before last is noise."""
    assert (
        notification_prefs.last_window_close(NIGHT, tz_name="UTC", now=_at(20)) is None
    )


@pytest.mark.unit
def test_no_window_means_no_summary():
    assert notification_prefs.last_window_close({}, tz_name="UTC", now=_at(8)) is None


@pytest.mark.integration
async def test_the_summary_says_what_happened_and_only_once(session: AsyncSession):
    user = await create_user(session, email="quiet-summary@example.com", timezone="UTC")
    guild = await create_guild(session, creator=user)
    await set_notification_prefs(session, user, dict(NIGHT))

    # Two things, inside last night's window.
    for _ in range(2):
        notification = await user_notifications.create_notification(
            session,
            user_id=user.id,
            notification_type=NotificationType.mention,
            data={"guild_id": guild.id},
        )
        assert notification is not None
        notification.created_at = _at(23, day=8)
    await session.commit()

    with patch(
        "app.services.email.send_mention_email", new_callable=AsyncMock
    ) as email:
        await _run_quiet_hours_summary_pass(session, now=_at(8))
        assert email.await_count == 1
        body = email.await_args.kwargs["body_text"]
        assert "2" in body
        assert guild.name in body

        # The window is stamped, so a second pass inside the grace period says
        # nothing more.
        await _run_quiet_hours_summary_pass(session, now=_at(9))
        assert email.await_count == 1


@pytest.mark.integration
async def test_a_quiet_night_sends_nothing(session: AsyncSession):
    user = await create_user(session, email="quiet-nothing@example.com", timezone="UTC")
    await set_notification_prefs(session, user, dict(NIGHT))

    with patch(
        "app.services.email.send_mention_email", new_callable=AsyncMock
    ) as email:
        await _run_quiet_hours_summary_pass(session, now=_at(8))

    assert email.await_count == 0


@pytest.mark.integration
async def test_an_account_with_no_window_is_left_alone(session: AsyncSession):
    user = await create_user(session, email="quiet-none@example.com", timezone="UTC")
    await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.mention,
        data={},
    )
    await session.commit()

    with patch(
        "app.services.email.send_mention_email", new_callable=AsyncMock
    ) as email:
        await _run_quiet_hours_summary_pass(session, now=_at(8))

    assert email.await_count == 0


@pytest.mark.integration
async def test_nothing_read_before_the_window_closed_is_counted(
    session: AsyncSession,
):
    """The summary is what is still waiting, not what arrived."""
    user = await create_user(session, email="quiet-read@example.com", timezone="UTC")
    await set_notification_prefs(session, user, dict(NIGHT))
    notification = await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.mention,
        data={},
    )
    assert notification is not None
    notification.created_at = _at(23, day=8)
    notification.read_at = _at(23, day=8) + timedelta(minutes=5)
    await session.commit()

    with patch(
        "app.services.email.send_mention_email", new_callable=AsyncMock
    ) as email:
        await _run_quiet_hours_summary_pass(session, now=_at(8))

    assert email.await_count == 0


@pytest.mark.integration
async def test_the_summary_carries_only_what_the_channel_may_say(
    session: AsyncSession,
):
    """A category switched off for email is not named in the email."""
    user = await create_user(
        session, email="quiet-channels@example.com", timezone="UTC"
    )
    guild = await create_guild(session, creator=user)
    await set_notification_prefs(
        session,
        user,
        {**NIGHT, "categories": {"reactions": {"email": False}}},
    )
    for notification_type in (
        NotificationType.mention,
        NotificationType.comment_reaction,
    ):
        notification = await user_notifications.create_notification(
            session,
            user_id=user.id,
            notification_type=notification_type,
            data={"guild_id": guild.id},
        )
        assert notification is not None
        notification.created_at = _at(23, day=8)
    await session.commit()

    with patch(
        "app.services.email.send_mention_email", new_callable=AsyncMock
    ) as email:
        await _run_quiet_hours_summary_pass(session, now=_at(8))

    body = email.await_args.kwargs["body_text"]
    assert "mention" in body.lower()
    assert "reaction" not in body.lower()


@pytest.mark.integration
async def test_nothing_either_channel_may_say_sends_nothing(session: AsyncSession):
    user = await create_user(
        session, email="quiet-allmuted@example.com", timezone="UTC"
    )
    guild = await create_guild(session, creator=user)
    await set_notification_prefs(
        session,
        user,
        {
            **NIGHT,
            "categories": {"reactions": {"email": False, "push": False}},
        },
    )
    notification = await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.comment_reaction,
        data={"guild_id": guild.id},
    )
    assert notification is not None
    notification.created_at = _at(23, day=8)
    await session.commit()

    with patch(
        "app.services.email.send_mention_email", new_callable=AsyncMock
    ) as email:
        await _run_quiet_hours_summary_pass(session, now=_at(8))

    assert email.await_count == 0


@pytest.mark.integration
async def test_a_failed_send_is_tried_again(session: AsyncSession):
    """The window is stamped by a delivery, not by the attempt — an
    unconfigured channel must not burn the account's one summary."""
    user = await create_user(session, email="quiet-retry@example.com", timezone="UTC")
    await set_notification_prefs(session, user, dict(NIGHT))
    notification = await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.mention,
        data={},
    )
    assert notification is not None
    notification.created_at = _at(23, day=8)
    await session.commit()

    from app.services import email as email_service

    with patch(
        "app.services.email.send_mention_email",
        new_callable=AsyncMock,
        side_effect=email_service.EmailNotConfiguredError(),
    ) as failing:
        await _run_quiet_hours_summary_pass(session, now=_at(8))
        assert failing.await_count == 1

    with patch(
        "app.services.email.send_mention_email", new_callable=AsyncMock
    ) as retried:
        await _run_quiet_hours_summary_pass(session, now=_at(9))

    assert retried.await_count == 1


@pytest.mark.integration
async def test_a_channel_that_failed_is_retried_while_the_other_is_not(
    session: AsyncSession,
):
    """Each channel is stamped by its own delivery.

    A successful email must not mark the window done for a push that never
    went, and the retry must not send the email a second time.
    """
    user = await create_user(
        session, email="quiet-per-channel@example.com", timezone="UTC"
    )
    await set_notification_prefs(session, user, dict(NIGHT))
    notification = await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.mention,
        data={},
    )
    assert notification is not None
    notification.created_at = _at(23, day=8)
    await session.commit()

    with (
        patch("app.services.email.send_mention_email", new_callable=AsyncMock) as email,
        patch(
            "app.services.platform.push_notifications.send_push_to_user",
            new_callable=AsyncMock,
            side_effect=RuntimeError("no FCM"),
        ) as push,
    ):
        await _run_quiet_hours_summary_pass(session, now=_at(8))
        assert email.await_count == 1
        assert push.await_count == 1

    with (
        patch("app.services.email.send_mention_email", new_callable=AsyncMock) as email,
        patch(
            "app.services.platform.push_notifications.send_push_to_user",
            new_callable=AsyncMock,
            return_value=True,
        ) as push,
    ):
        await _run_quiet_hours_summary_pass(session, now=_at(9))

    # The push is tried again; the email that already went is not repeated.
    assert push.await_count == 1
    assert email.await_count == 0


@pytest.mark.integration
async def test_a_setting_changed_mid_send_is_not_taken_back(session: AsyncSession):
    """Stamping re-reads the document, so a change made while the summary was
    being sent survives it."""
    user = await create_user(session, email="quiet-raced@example.com", timezone="UTC")
    await set_notification_prefs(session, user, dict(NIGHT))
    notification = await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.mention,
        data={},
    )
    assert notification is not None
    notification.created_at = _at(23, day=8)
    await session.commit()

    async def _change_a_setting_then_send(*args, **kwargs):
        await notification_prefs.save_prefs(
            session,
            user.id,
            {**NIGHT, "categories": {"reactions": {"push": False}}},
        )
        await session.commit()

    with (
        patch(
            "app.services.email.send_mention_email",
            new_callable=AsyncMock,
            side_effect=_change_a_setting_then_send,
        ),
        patch(
            "app.services.platform.push_notifications.send_push_to_user",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        await _run_quiet_hours_summary_pass(session, now=_at(8))

    settled = await notification_prefs.load_prefs(session, user.id)
    assert settled["categories"]["reactions"]["push"] is False
    assert settled["quiet_hours"]["last_summary_at"]["email"]
