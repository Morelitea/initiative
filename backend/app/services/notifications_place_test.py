"""A notification records where it happened.

The three columns are what light the navigation, so a notifier that does not
fill them leaves its community's dot saying "somewhere in here" and nothing
below it lighting at all.
"""

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.models.platform.notification import Notification, NotificationType
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
        notification_type=NotificationType.initiative_added,
        data={"guild_id": guild.id},
    )
    await session.commit()

    line = await _only(session, member.id)
    assert line.guild_id == guild.id
    assert line.initiative_id is None
    assert line.tool is None


async def _thing(session: AsyncSession, kind: str, initiative, creator):
    """One row of ``kind`` in ``initiative``, and the tool that governs it."""
    from app.testing import (
        create_calendar,
        create_calendar_event,
        create_document,
        create_project,
        create_task,
        create_wiki,
        create_wiki_page,
    )

    if kind == "task":
        project = await create_project(session, initiative, creator)
        return await create_task(session, project), Tool.project
    if kind == "document":
        return await create_document(session, initiative, creator), Tool.document
    if kind == "calendar_event":
        calendar = await create_calendar(session, initiative, creator)
        return await create_calendar_event(session, calendar, creator), Tool.calendar
    wiki = await create_wiki(session, initiative, creator)
    return await create_wiki_page(session, wiki, creator), Tool.wiki


@pytest.mark.integration
@pytest.mark.parametrize("kind", ["task", "document", "calendar_event", "wiki_page"])
async def test_a_notice_is_placed_by_what_it_is_about(session: AsyncSession, kind: str):
    """Every notice lights the initiative and tool that govern the thing it
    names — a task the Projects row, an event its calendar, a page its wiki —
    because ``notify`` reads them off that thing rather than being told."""
    from app.db.session import set_rls_context
    from app.testing import create_initiative

    owner = await create_user(session, email=f"place-{kind}@example.com")
    guild = await create_guild(session, creator=owner)
    initiative = await create_initiative(session, guild, owner)
    row, tool = await _thing(session, kind, initiative, owner)
    actor = await create_user(session, email=f"place-actor-{kind}@example.com")
    await session.commit()

    await set_rls_context(session, guild_id=guild.id)
    await notifications_service.notify(
        session,
        NotificationType.mention,
        [owner.id],
        about=(kind, row.id),
        key="mention.comment",
        values={"actor": "someone", "context": "it"},
        actor=actor,
    )
    await session.commit()
    await set_rls_context(session)

    line = await _only(session, owner.id)
    assert line.guild_id == guild.id
    assert line.initiative_id == initiative.id
    assert line.tool == tool.value
