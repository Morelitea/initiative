"""The database decides sharing for the search index.

Every other gate on ``search_entries`` is a policy; sharing used to be applied
only by the query that read the table. These assert the policy answers it now —
each test reads the table with a plain SELECT, carrying no clause of its own, so
what comes back is what the database allowed.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlmodel import select

from app.db.session import set_override_initiatives, set_rls_context
from app.models.platform.guild import GuildRole
from app.models.tenant.search_entry import SearchEntry
from app.testing import create_tag, create_task

pytestmark = pytest.mark.integration


async def _unfiltered(
    session, guild_id: int, actor, *, role: str = "member"
) -> list[str]:
    """Titles the database hands back for a bare SELECT — no query-side gate."""
    await set_rls_context(
        session, user_id=actor.user.id, guild_id=guild_id, guild_role=role
    )
    rows = await session.exec(
        select(SearchEntry.title).where(SearchEntry.entity_type == "task")
    )
    return sorted(rows)


async def test_a_member_without_a_grant_is_refused_by_the_database(
    session, acting_user
):
    """In the initiative — so the membership gate admits the row — but holding
    no grant on the project it belongs to."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    await create_task(session, a.project, title="restricted vendor renewal")

    assert await _unfiltered(session, a.guild.id, b) == []


async def test_the_owner_is_admitted(session, acting_user):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    await create_task(session, a.project, title="restricted vendor renewal")

    assert await _unfiltered(session, a.guild.id, a) == ["restricted vendor renewal"]


async def test_a_guild_admin_is_admitted(session, acting_user):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    b = await acting_user(
        guild_role=GuildRole.admin,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    await create_task(session, a.project, title="restricted vendor renewal")

    assert await _unfiltered(session, a.guild.id, b, role="admin") == [
        "restricted vendor renewal"
    ]


async def test_full_access_is_carried_into_the_database(session, acting_user):
    """The override is computed in Python per request; the policy reads it from
    a session setting. If that plumbing breaks, a full-access member silently
    loses rows they can reach everywhere else."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    await create_task(session, a.project, title="restricted vendor renewal")

    # Without the override: refused, as above.
    assert await _unfiltered(session, a.guild.id, b) == []

    # With it: admitted, without any grant being issued.
    await set_rls_context(
        session, user_id=b.user.id, guild_id=a.guild.id, guild_role="member"
    )
    await set_override_initiatives(session, (a.initiative.id,))
    rows = await session.exec(
        select(SearchEntry.title).where(SearchEntry.entity_type == "task")
    )
    assert sorted(rows) == ["restricted vendor renewal"]


async def test_guild_vocabulary_answers_to_no_sharing(session, acting_user):
    """A tag carries no sharing identity, so the sharing gate has nothing to
    decide and must not filter it out."""
    a = await acting_user(guild_role=GuildRole.admin)
    b = await acting_user(guild_role=GuildRole.member, guild=a.guild)
    await create_tag(session, a.guild, name="urgent")

    await set_rls_context(
        session, user_id=b.user.id, guild_id=a.guild.id, guild_role="member"
    )
    rows = await session.exec(
        select(SearchEntry.title).where(SearchEntry.entity_type == "tag")
    )
    assert sorted(rows) == ["urgent"]


async def test_the_override_setting_defaults_to_empty(session, acting_user):
    """An unset override must read as "no initiatives", not as an error that
    faults the policy for every row."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    await set_rls_context(
        session, user_id=a.user.id, guild_id=a.guild.id, guild_role="member"
    )
    value = (
        await session.exec(
            text("SELECT current_setting('app.override_initiatives', true)")
        )
    ).one()[0]
    assert value == ""
