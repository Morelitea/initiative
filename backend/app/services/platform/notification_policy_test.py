"""What a notification may leave the app carrying.

Two levels answer three questions, and the stricter of each pair binds. The
tests below cover the resolution itself and then the two seams that apply it —
the one every push goes through and the one every notification email is written
at — because a switch that resolves correctly and is not read anywhere is not a
switch.
"""

from unittest.mock import AsyncMock

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.notification_categories import NotificationCategory
from app.models.platform.email_outbox import EmailOutboxItem
from app.models.platform.notification import NotificationType
from app.services import email as email_service
from app.services.platform import app_settings as app_settings_service
from app.services.platform import (
    email_outbox,
    notification_policy,
    push_notifications,
    push_tokens,
)
from app.testing import create_guild, create_user

pytestmark = [pytest.mark.integration, pytest.mark.database]


async def _platform(session: AsyncSession, **fields: bool) -> None:
    """Set the deployment's answers, as an owner's PUT would."""
    row = await app_settings_service.ensure_settings_row(session)
    for name, value in fields.items():
        setattr(row, name, value)
    session.add(row)
    await session.commit()


def _pieces() -> email_service.EmailPieces:
    return email_service.EmailPieces(
        subject="Ana mentioned you in Q3 budget",
        headline="Ana mentioned you in Q3 budget",
        body="<strong>Ana</strong> mentioned you in <strong>Q3 budget</strong>",
        link="https://example.test/x",
    )


@pytest.fixture
def configured(monkeypatch):
    """A deployment that can send mail."""
    monkeypatch.setattr(email_service, "email_configured", AsyncMock(return_value=True))


# --- resolution --------------------------------------------------------------


async def test_a_fresh_deployment_restricts_nothing(session: AsyncSession) -> None:
    """The shape the app had before any of this existed."""
    guild = await create_guild(session)
    assert await notification_policy.resolve(session, guild.id) == (
        notification_policy.UNRESTRICTED
    )
    assert await notification_policy.resolve(session, None) == (
        notification_policy.UNRESTRICTED
    )


async def test_the_deployment_binds_every_community(session: AsyncSession) -> None:
    guild = await create_guild(session)
    await _platform(session, push_notifications_enabled=False)

    assert (await notification_policy.resolve(session, guild.id)).push is False
    assert (await notification_policy.resolve(session, None)).push is False


async def test_a_community_answers_only_for_itself(session: AsyncSession) -> None:
    quiet = await create_guild(session)
    other = await create_guild(session)
    quiet.allow_push_notifications = False
    quiet.redact_notification_content = True
    session.add(quiet)
    await session.commit()

    here = await notification_policy.resolve(session, quiet.id)
    assert here.push is False
    assert here.redact is True

    elsewhere = await notification_policy.resolve(session, other.id)
    assert elsewhere == notification_policy.UNRESTRICTED
    # A notification belonging to no community is the deployment's answer alone.
    assert await notification_policy.resolve(session, None) == (
        notification_policy.UNRESTRICTED
    )


async def test_the_stricter_of_the_pair_binds(session: AsyncSession) -> None:
    """A community may narrow what the deployment permits, never widen it."""
    guild = await create_guild(session)
    guild.allow_push_notifications = True
    guild.allow_email_notifications = True
    guild.redact_notification_content = False
    session.add(guild)
    await session.commit()
    await _platform(
        session,
        push_notifications_enabled=False,
        email_notifications_enabled=False,
        redact_notification_content=True,
    )

    resolved = await notification_policy.resolve(session, guild.id)
    assert (resolved.push, resolved.email, resolved.redact) == (False, False, True)


async def test_resolve_many_answers_each_community(session: AsyncSession) -> None:
    """What a cross-guild digest needs: one answer per community it gathered
    from, and one for the items belonging to none."""
    quiet = await create_guild(session)
    loud = await create_guild(session)
    quiet.allow_email_notifications = False
    session.add(quiet)
    await session.commit()

    answers = await notification_policy.resolve_many(session, [quiet.id, loud.id, None])

    assert answers[quiet.id].email is False
    assert answers[loud.id].email is True
    assert answers[None].email is True


async def test_a_community_that_no_longer_exists_is_answered_by_the_deployment(
    session: AsyncSession,
) -> None:
    """A row's community can be deleted between the write and the send."""
    await _platform(session, redact_notification_content=True)
    resolved = await notification_policy.resolve(session, 10_000_000)
    assert resolved.redact is True
    assert resolved.push is True


# --- the redacted wording ----------------------------------------------------


async def test_a_redacted_line_says_the_kind_of_thing_and_stops() -> None:
    title, body = notification_policy.redacted_push(NotificationType.mention, "en")
    assert title == "You were mentioned"
    assert body == "Open Initiative to see where."


async def test_every_category_has_a_redacted_line() -> None:
    """A category with no line of its own would push its own key at somebody."""
    for category in NotificationCategory:
        subject = notification_policy.redacted_subject(category, "en")
        body = notification_policy.redacted_body(category, "en")
        assert not subject.startswith("redacted."), category
        assert not body.startswith("redacted."), category


# --- the push seam -----------------------------------------------------------


@pytest.fixture
def fcm(monkeypatch):
    """A deployment wired to FCM, capturing what would go on the wire."""
    monkeypatch.setattr(push_notifications.settings, "FCM_ENABLED", True, raising=False)
    calls: list[dict] = []

    async def _send(
        push_token, title, body, data=None, platform="android", channel_id=None
    ):
        calls.append({"title": title, "body": body})
        return (True, False)

    monkeypatch.setattr(push_notifications, "send_push_notification", _send)
    return calls


async def _with_a_phone(session: AsyncSession, email: str):
    user = await create_user(session, email=email)
    await push_tokens.register_push_token(
        session=session,
        user_id=user.id,
        push_token=f"token-{user.id}",
        platform="android",
        device_token_id=None,
    )
    return user


async def test_a_community_that_declines_push_gets_none(
    session: AsyncSession, fcm
) -> None:
    guild = await create_guild(session)
    guild.allow_push_notifications = False
    session.add(guild)
    await session.commit()
    user = await _with_a_phone(session, "declines-push@example.com")

    sent = await push_notifications.send_push_to_user(
        session=session,
        user_id=user.id,
        notification_type=NotificationType.mention,
        title="Ana mentioned you in Q3 budget",
        body="Ana mentioned you in a comment on Q3 budget",
        guild_id=guild.id,
        locale="en",
    )

    assert sent == 0
    assert fcm == []


async def test_a_redacting_community_sends_the_kind_of_thing(
    session: AsyncSession, fcm
) -> None:
    guild = await create_guild(session)
    guild.redact_notification_content = True
    session.add(guild)
    await session.commit()
    user = await _with_a_phone(session, "redacts@example.com")

    sent = await push_notifications.send_push_to_user(
        session=session,
        user_id=user.id,
        notification_type=NotificationType.mention,
        title="Ana mentioned you in Q3 budget",
        body="Ana mentioned you in a comment on Q3 budget",
        guild_id=guild.id,
        locale="en",
    )

    assert sent == 1
    assert fcm == [
        {"title": "You were mentioned", "body": "Open Initiative to see where."}
    ]


async def test_an_unrestricted_community_pushes_what_it_was_given(
    session: AsyncSession, fcm
) -> None:
    guild = await create_guild(session)
    user = await _with_a_phone(session, "unrestricted-push@example.com")

    await push_notifications.send_push_to_user(
        session=session,
        user_id=user.id,
        notification_type=NotificationType.mention,
        title="Ana mentioned you in Q3 budget",
        body="Ana mentioned you in a comment on Q3 budget",
        guild_id=guild.id,
        locale="en",
    )

    assert fcm[0]["title"] == "Ana mentioned you in Q3 budget"


async def test_a_redacted_push_reads_the_recipients_language(
    session: AsyncSession, fcm
) -> None:
    """The caller had no locale in hand, so the account's own is read."""
    guild = await create_guild(session)
    guild.redact_notification_content = True
    session.add(guild)
    await session.commit()
    user = await _with_a_phone(session, "french-push@example.com")
    user.locale = "fr"
    session.add(user)
    await session.commit()

    await push_notifications.send_push_to_user(
        session=session,
        user_id=user.id,
        notification_type=NotificationType.mention,
        title="Ana mentioned you in Q3 budget",
        body="Ana mentioned you in a comment on Q3 budget",
        guild_id=guild.id,
    )

    assert fcm[0]["title"] == "Vous avez été mentionné"


# --- the email seam ----------------------------------------------------------


async def _outbox(session: AsyncSession, user_id: int) -> list[EmailOutboxItem]:
    result = await session.exec(
        select(EmailOutboxItem).where(EmailOutboxItem.user_id == user_id)
    )
    return [row[0] if isinstance(row, tuple) else row for row in result.all()]


async def test_a_community_that_declines_email_writes_nothing(
    session: AsyncSession, configured
) -> None:
    guild = await create_guild(session)
    guild.allow_email_notifications = False
    session.add(guild)
    await session.commit()
    user = await create_user(session, email="declines-email@example.com")

    wrote = await email_outbox.enqueue(
        session,
        user,
        category=NotificationCategory.mentions,
        guild_id=guild.id,
        pieces=_pieces(),
    )
    await session.commit()

    assert wrote is False
    assert await _outbox(session, user.id) == []


async def test_a_redacting_community_stores_no_more_than_the_mail_will(
    session: AsyncSession, configured
) -> None:
    guild = await create_guild(session)
    guild.redact_notification_content = True
    session.add(guild)
    await session.commit()
    user = await create_user(session, email="redacted-email@example.com")

    assert await email_outbox.enqueue(
        session,
        user,
        category=NotificationCategory.mentions,
        guild_id=guild.id,
        pieces=_pieces(),
    )
    await session.commit()

    (row,) = await _outbox(session, user.id)
    assert row.subject == "You were mentioned"
    assert row.body == "Open Initiative to see where."
    assert "Q3 budget" not in row.subject + row.headline + row.body
    # The way back is not the content, so it survives.
    assert row.link == "https://example.test/x"


async def test_the_deployment_can_decline_email_for_everybody(
    session: AsyncSession, configured
) -> None:
    guild = await create_guild(session)
    await _platform(session, email_notifications_enabled=False)
    user = await create_user(session, email="no-mail-anywhere@example.com")

    assert (
        await email_outbox.enqueue(
            session,
            user,
            category=NotificationCategory.mentions,
            guild_id=guild.id,
            pieces=_pieces(),
        )
        is False
    )
    # And for a notification belonging to no community.
    assert (
        await email_outbox.enqueue(
            session,
            user,
            category=NotificationCategory.direct_messages,
            pieces=_pieces(),
        )
        is False
    )
