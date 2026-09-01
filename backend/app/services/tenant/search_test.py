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

from app.core.role_context import set_active_role
from app.db.session import set_rls_context
from app.models.platform.guild import GuildRole
from app.models.tenant.search_entry import SearchEntry
from app.services.tenant.search import search_scope_clause
from app.testing import create_task

pytestmark = pytest.mark.integration


async def _search(
    session,
    *,
    user_id: int,
    guild_id: int,
    guild_role: str,
) -> list[str]:
    """Titles this user can read out of the index, through the one entry point."""
    set_active_role(guild_id, guild_role)
    await set_rls_context(
        session, user_id=user_id, guild_id=guild_id, guild_role=guild_role
    )
    rows = await session.exec(
        select(SearchEntry.title).where(
            SearchEntry.entity_type == "task",
            search_scope_clause(user_id, guild_id=guild_id),
        )
    )
    return sorted(rows)


async def test_a_member_without_a_grant_gets_no_hits(session, acting_user):
    """The initiative gate admits this row; sharing is what excludes it."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    await create_task(session, a.project, title="restricted vendor renewal")

    assert (
        await _search(
            session, user_id=b.user.id, guild_id=a.guild.id, guild_role="member"
        )
        == []
    )


async def test_the_owner_does_get_the_hit(session, acting_user):
    """...and the clause is not simply excluding everything."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    await create_task(session, a.project, title="restricted vendor renewal")

    assert await _search(
        session, user_id=a.user.id, guild_id=a.guild.id, guild_role="member"
    ) == ["restricted vendor renewal"]


async def test_a_guild_admin_is_not_narrowed_by_sharing(session, acting_user):
    """A guild admin reaches every aspect of their guild, so the clause is the
    one ``dac_scope_clause`` already collapses to true."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    b = await acting_user(
        guild_role=GuildRole.admin,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    await create_task(session, a.project, title="restricted vendor renewal")

    assert await _search(
        session, user_id=b.user.id, guild_id=a.guild.id, guild_role="admin"
    ) == ["restricted vendor renewal"]
