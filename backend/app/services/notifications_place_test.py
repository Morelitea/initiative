"""A notification records where it happened.

The three columns are what light the navigation, so a notifier that does not
fill them leaves its community's dot saying "somewhere in here" and nothing
below it lighting at all.
"""

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.models.platform.notification import Notification
from app.services import notifications as notifications_service
from app.services.platform import user_notifications
from app.testing import create_guild, create_user


async def _only(session: AsyncSession, user_id: int) -> Notification:
    rows = (
        await session.exec(select(Notification).where(Notification.user_id == user_id))
    ).all()
    assert len(rows) == 1
    return rows[0][0] if isinstance(rows[0], tuple) else rows[0]


@pytest.mark.unit
def test_an_explicit_tool_wins_over_the_entity_type():
    """They differ for a task comment: the entity is the task, the tool is the
    project list it lives in — and the link resolver reads ``entity_type``."""
    place = user_notifications._place(
        {"guild_id": 3, "initiative_id": 9, "tool": "project", "entity_type": "task"}
    )
    assert place == {"guild_id": 3, "initiative_id": 9, "tool": "project"}


@pytest.mark.unit
def test_the_entity_type_is_used_when_no_tool_is_stated():
    place = user_notifications._place({"guild_id": 3, "entity_type": "queue"})
    assert place == {"guild_id": 3, "initiative_id": None, "tool": "queue"}


@pytest.mark.unit
def test_a_payload_naming_nowhere_carries_no_place():
    assert user_notifications._place({}) == {
        "guild_id": None,
        "initiative_id": None,
        "tool": None,
    }


@pytest.mark.integration
async def test_a_comment_on_a_task_names_its_initiative_and_tool(
    session: AsyncSession,
):
    owner = await create_user(session, email="place-owner@example.com")
    guild = await create_guild(session, creator=owner)
    talker = await create_user(session, email="place-talker@example.com")

    await notifications_service.notify_comment_on_task(
        session,
        assignee=owner,
        commenter=talker,
        comment_id=1,
        task_id=42,
        task_title="Fix the login redirect",
        project_name="Web",
        guild_id=guild.id,
        initiative_id=9,
        tool=Tool.project.value,
    )
    await session.commit()

    line = await _only(session, owner.id)
    assert line.guild_id == guild.id
    assert line.initiative_id == 9
    assert line.tool == Tool.project.value


@pytest.mark.integration
async def test_a_document_mention_names_the_documents_tool(session: AsyncSession):
    reader = await create_user(session, email="place-doc@example.com")
    guild = await create_guild(session, creator=reader)
    writer = await create_user(session, email="place-writer@example.com")

    await notifications_service.notify_document_mention(
        session,
        mentioned_user=reader,
        mentioned_by=writer,
        document_id=5,
        document_name="Runbook",
        guild_id=guild.id,
        initiative_id=11,
    )
    await session.commit()

    line = await _only(session, reader.id)
    assert line.initiative_id == 11
    assert line.tool == Tool.document.value


@pytest.mark.integration
async def test_a_notification_with_no_initiative_still_names_its_community(
    session: AsyncSession,
):
    """A membership notice belongs to a community and to nothing inside it, so
    the community lights and nothing below it does."""
    member = await create_user(session, email="place-guildonly@example.com")
    guild = await create_guild(session, creator=member)

    await user_notifications.create_notification(
        session,
        user_id=member.id,
        notification_type=notifications_service.NotificationType.initiative_added,
        data={"guild_id": guild.id},
    )
    await session.commit()

    line = await _only(session, member.id)
    assert line.guild_id == guild.id
    assert line.initiative_id is None
    assert line.tool is None


@pytest.mark.integration
@pytest.mark.parametrize(
    "notifier,kwargs,tool",
    [
        (
            "notify_comment_mention",
            {
                "comment_id": 1,
                "task_id": 4,
                "document_id": None,
                "context_title": "Fix it",
            },
            Tool.project.value,
        ),
        (
            "notify_comment_reply",
            {
                "comment_id": 1,
                "task_id": 4,
                "document_id": None,
                "context_title": "Fix it",
            },
            Tool.project.value,
        ),
        (
            "notify_comment_mention",
            {
                "comment_id": 1,
                "task_id": None,
                "document_id": 7,
                "context_title": "Runbook",
            },
            Tool.document.value,
        ),
    ],
)
async def test_every_comment_notifier_records_its_tool(
    session: AsyncSession, notifier: str, kwargs: dict, tool: str
):
    """A mention or reply lights the same row a comment does.

    Setting the tool on some of them and not others is what left Projects and
    Documents dark for the notifications people actually get.
    """
    recipient = await create_user(session, email=f"place-{notifier}-{tool}@example.com")
    guild = await create_guild(session, creator=recipient)
    actor = await create_user(
        session, email=f"place-actor-{notifier}-{tool}@example.com"
    )

    recipient_kwarg = {
        "notify_comment_mention": "mentioned_user",
        "notify_comment_reply": "parent_author",
    }[notifier]
    actor_kwarg = {
        "notify_comment_mention": "mentioned_by",
        "notify_comment_reply": "replier",
    }[notifier]

    await getattr(notifications_service, notifier)(
        session,
        **{recipient_kwarg: recipient, actor_kwarg: actor},
        guild_id=guild.id,
        initiative_id=3,
        tool=tool,
        **kwargs,
    )
    await session.commit()

    line = await _only(session, recipient.id)
    assert line.initiative_id == 3
    assert line.tool == tool


@pytest.mark.integration
async def test_an_event_notification_names_its_calendar_initiative(
    session: AsyncSession,
):
    """The one that was actually missing: an inbox full of event reminders lit
    its community and nothing under it."""
    from app.testing import create_calendar, create_calendar_event, create_initiative

    organizer = await create_user(session, email="place-event@example.com")
    guild = await create_guild(session, creator=organizer)
    initiative = await create_initiative(session, guild, organizer)
    calendar = await create_calendar(session, initiative, organizer)
    event = await create_calendar_event(session, calendar, organizer)
    attendee = await create_user(session, email="place-attendee@example.com")

    await notifications_service.notify_event_reminder(
        session, recipient=attendee, event=event, guild_id=guild.id
    )
    await session.commit()

    line = await _only(session, attendee.id)
    assert line.guild_id == guild.id
    assert line.initiative_id == initiative.id
    assert line.tool == Tool.calendar.value


@pytest.mark.integration
async def test_a_fan_out_asks_for_the_calendar_once(session: AsyncSession):
    """Every recipient gets their own notification, and they all share one
    lookup — an event with fifty attendees must not ask fifty times."""
    from app.services.notifications import _CALENDAR_INITIATIVES
    from app.testing import create_calendar, create_calendar_event, create_initiative

    organizer = await create_user(session, email="fanout-organizer@example.com")
    guild = await create_guild(session, creator=organizer)
    initiative = await create_initiative(session, guild, organizer)
    calendar = await create_calendar(session, initiative, organizer)
    event = await create_calendar_event(session, calendar, organizer)

    attendees = [
        await create_user(session, email=f"fanout-{i}@example.com") for i in range(3)
    ]

    session.info.pop(_CALENDAR_INITIATIVES, None)
    for attendee in attendees:
        await notifications_service.notify_event_reminder(
            session, recipient=attendee, event=event, guild_id=guild.id
        )
    await session.commit()

    # One entry, three recipients: the answer was reached for once and reused.
    assert list(session.info[_CALENDAR_INITIATIVES]) == [(guild.id, calendar.id)]
    for attendee in attendees:
        line = await _only(session, attendee.id)
        assert line.initiative_id == initiative.id


@pytest.mark.integration
async def test_two_communities_do_not_share_one_calendar_answer(
    session: AsyncSession,
):
    """Per-guild schemas mean two calendars can hold the same id, so the memo
    is keyed by guild as well — answering one community from another's entry
    would put a notification under the wrong initiative."""
    from app.services.notifications import _CALENDAR_INITIATIVES, _calendar_initiative

    memo = session.info.setdefault(_CALENDAR_INITIATIVES, {})
    memo[(1, 7)] = 100
    memo[(2, 7)] = 200

    assert await _calendar_initiative(session, calendar_id=7, guild_id=1) == 100
    assert await _calendar_initiative(session, calendar_id=7, guild_id=2) == 200
