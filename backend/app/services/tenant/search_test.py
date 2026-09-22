"""Sharing is enforced on index reads.

``search_entries`` is gated in the database by initiative membership, like the
content tables it mirrors. These assert the gate that is NOT in the database:
per-resource sharing, applied by :func:`search_scope_clause`.

The case that matters is the one the initiative gate cannot answer — a member OF
the initiative, whose RLS therefore admits the row, holding no grant on the
project the row belongs to.
"""

from __future__ import annotations

import pytest
from sqlmodel import select

from app.models.platform.guild import GuildRole
from app.models.tenant.search_entry import SearchEntry
from app.services.tenant.search import search_scope_clause
from app.testing import create_task

pytestmark = pytest.mark.integration


async def _search(reading_as, *, user_id: int, guild_id: int) -> list[str]:
    """Titles this user can read out of the index, through the one entry point.

    Read on the request login: what the index hands back is a policy answer,
    and the setup session's own login is one the database treats as trusted.
    """
    session = await reading_as(user_id, guild_id)
    rows = await session.exec(
        select(SearchEntry.title).where(
            SearchEntry.entity_type == "task",
            search_scope_clause(user_id, guild_id=guild_id),
        )
    )
    await session.rollback()
    return sorted(rows)


async def test_a_member_without_a_grant_gets_no_hits(session, acting_user, reading_as):
    """The initiative gate admits this row; sharing is what excludes it."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    await create_task(session, a.project, title="restricted vendor renewal")

    assert await _search(reading_as, user_id=b.user.id, guild_id=a.guild.id) == []


async def test_the_owner_does_get_the_hit(session, acting_user, reading_as):
    """...and the clause is not simply excluding everything."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    await create_task(session, a.project, title="restricted vendor renewal")

    assert await _search(reading_as, user_id=a.user.id, guild_id=a.guild.id) == [
        "restricted vendor renewal"
    ]


async def test_a_guild_admin_is_not_narrowed_by_sharing(
    session, acting_user, reading_as
):
    """A guild admin reaches every aspect of their guild, so the clause is the
    one the sharing gate already collapses to true."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    b = await acting_user(
        guild_role=GuildRole.admin,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    await create_task(session, a.project, title="restricted vendor renewal")

    assert await _search(reading_as, user_id=b.user.id, guild_id=a.guild.id) == [
        "restricted vendor renewal"
    ]
