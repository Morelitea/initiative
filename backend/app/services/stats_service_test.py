"""Tests for user stats — schema-per-guild routing.

The stats service reads guild-scoped tasks/projects/initiatives, which live in
per-guild schemas. These tests assert it routes into the guild schema rather
than reading the empty ``public`` backup (which returned all-zero dashboards).
"""

import pytest

from app.models.guild import GuildRole
from app.models.task import TaskStatusCategory
from app.services import stats_service
from app.testing import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_project,
    create_task,
    create_user,
)


@pytest.mark.integration
async def test_user_stats_reads_guild_schema(session):
    """A guild with completed tasks must report non-zero stats. If stats read
    the unrouted (public) schema this is 0 — the dashboard-zeros regression."""
    user = await create_user(session, email="stats-user@example.com")
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, user, name="Stats Init")
    project = await create_project(session, initiative, user)

    # Two completed tasks assigned to the user (written into the guild schema).
    await create_task(
        session,
        project,
        status_category=TaskStatusCategory.done,
        assignees=[user],
    )
    await create_task(
        session,
        project,
        status_category=TaskStatusCategory.done,
        assignees=[user],
    )

    stats = await stats_service.get_user_stats(session, user=user, guild_id=guild.id)
    assert stats.tasks_completed_total == 2
    assert any(
        g.guild_id == guild.id and g.completed_count == 2 for g in stats.guild_breakdown
    )


@pytest.mark.integration
async def test_user_stats_all_guilds_aggregates(session):
    """guild_id=None aggregates completed counts across the user's guilds."""
    user = await create_user(session, email="multi-guild@example.com")
    totals = 0
    for n, count in (("A", 1), ("B", 2)):
        guild = await create_guild(session, creator=user)
        await create_guild_membership(
            session, user=user, guild=guild, role=GuildRole.admin
        )
        initiative = await create_initiative(session, guild, user, name=f"Init {n}")
        project = await create_project(session, initiative, user)
        for _ in range(count):
            await create_task(
                session,
                project,
                status_category=TaskStatusCategory.done,
                assignees=[user],
            )
        totals += count

    stats = await stats_service.get_user_stats(session, user=user, guild_id=None)
    assert stats.tasks_completed_total == totals  # 3, summed across both guilds
    assert len(stats.guild_breakdown) == 2
