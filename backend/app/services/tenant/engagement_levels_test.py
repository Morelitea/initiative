"""The hourly pass that works out each community's engagement levels, and the
gates on what it writes."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, update
from sqlalchemy.exc import DBAPIError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import CommunityRole
from app.models.tenant.engagement_level import EngagementLevel
from app.models.tenant.event_outbox import EventOutbox
from app.models.tenant.recent_view import RecentView
from app.services.guild_sweeps import Scope, each_guild
from app.services.platform import app_settings as app_settings_service
from app.services.tenant import engagement_levels
from app.testing import create_task, guild_administration
from app.testing.routing import route_as


async def _pass(guild_id: int) -> None:
    await each_guild(
        [(Scope.ACTIVE, await engagement_levels.prepare())],
        name="test",
        only=[guild_id],
    )


async def _levels(session: AsyncSession) -> dict[tuple[str, int], int]:
    rows = (await session.exec(select(EngagementLevel))).all()
    return {(row.entity_type, row.entity_id): row.level for row in rows}


async def _three_people(session: AsyncSession, acting_user):
    """Three members of one initiative, and a task in its project."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    others = [
        await acting_user(
            guild_role=CommunityRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="member",
        )
        for _ in range(2)
    ]
    task = await create_task(session, a.project)
    return [a, *others], task


async def _all_opened(session: AsyncSession, people, task) -> None:
    now = datetime.now(timezone.utc)
    for person in people:
        session.add(
            RecentView(
                user_id=person.user.id,
                entity_type="task",
                entity_id=task.id,
                last_viewed_at=now,
            )
        )
    await session.commit()


async def test_an_item_has_a_level_once_three_people_engaged(
    session: AsyncSession, acting_user
):
    """Two opens and changes nobody made are not enough. A comment counts for
    the task it is on, and only the level is kept."""
    (a, b, c), task = await _three_people(session, acting_user)
    await _all_opened(session, (a, b), task)

    def change(actor: int | None, install: int | None = None) -> EventOutbox:
        return EventOutbox(
            txn_id=1,
            actor_user_id=actor,
            actor_install_id=install,
            initiative_id=a.initiative.id,
            resource_type="comments",
            resource_id=1,
            action="created",
            parents=[
                {"type": "tasks", "id": task.id},
                {"type": "projects", "id": a.project.id},
            ],
        )

    session.add(change(c.user.id, install=1))
    session.add(change(None))
    await session.commit()
    await _pass(a.guild.id)
    assert await _levels(session) == {}

    session.add(change(c.user.id))
    await session.commit()
    await _pass(a.guild.id)
    # Two opens at 1 and a change at 2: log2(1 + 4), floored.
    assert await _levels(session) == {("task", task.id): 2}


async def test_turning_ranking_off_clears_the_levels(
    session: AsyncSession, acting_user
):
    """A community's answer applies while it holds ``restrictions``; the
    deployment's applies to every community."""
    people, task = await _three_people(session, acting_user)
    guild = people[0].guild
    await _all_opened(session, people, task)
    await _pass(guild.id)
    # Three opens a moment old come to just under 3: log2(1 + 3), floored.
    assert await _levels(session) == {("task", task.id): 1}

    guild.allow_engagement_ranking = False
    session.add(guild)
    await session.commit()
    await guild_administration(session, guild, auth_options=[])
    await _pass(guild.id)
    assert await _levels(session) == {("task", task.id): 1}

    await guild_administration(session, guild, auth_options=["restrictions"])
    await _pass(guild.id)
    assert await _levels(session) == {}

    guild.allow_engagement_ranking = True
    session.add(guild)
    settings_row = await app_settings_service.ensure_settings_row(session)
    settings_row.engagement_ranking_enabled = False
    session.add(settings_row)
    await session.commit()
    await _pass(guild.id)
    assert await _levels(session) == {}


async def test_a_level_is_read_like_its_item_and_written_by_nobody(
    session: AsyncSession, acting_user, role_session
):
    """The project's owner reads the task's level; a member it isn't shared
    with, and a member of the community outside the initiative, read none. Not
    even the owner writes one."""
    people, task = await _three_people(session, acting_user)
    owner, unshared = people[0], people[1]
    outsider = await acting_user(guild_role=CommunityRole.member, guild=owner.guild)
    await _all_opened(session, people, task)
    await _pass(owner.guild.id)

    for who, reads in ((owner, True), (unshared, False), (outsider, False)):
        s = await role_session("app_user")
        await route_as(s, user_id=who.user.id, guild_id=owner.guild.id)
        assert bool((await s.exec(select(EngagementLevel))).all()) is reads

    s = await role_session("app_user")
    await route_as(s, user_id=owner.user.id, guild_id=owner.guild.id)
    await s.exec(update(EngagementLevel).values(level=7))  # type: ignore[arg-type]
    await s.exec(delete(EngagementLevel))  # type: ignore[arg-type]
    assert await _levels(s) == {("task", task.id): 1}
    with pytest.raises(DBAPIError):
        s.add(EngagementLevel(entity_type="task", entity_id=task.id + 1, level=7))
        await s.flush()
