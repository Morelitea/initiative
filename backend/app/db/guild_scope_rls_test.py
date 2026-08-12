"""What `initiative_id IS NULL` means at the database layer.

A row that belongs to no initiative belongs to the guild. The initiative gate has
nothing to decide about it, so `initiative_access` passes for any session routed
into that guild's schema — and the gates on either side of it still hold: the
schema boundary keeps the row inside its own guild, and grants decide which
members may read or write it.

These run under the real `app_user` login with a routed context rather than the
superuser-backed `session` fixture, because the whole subject is what a policy
does — and a superuser session would show none of it.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import set_rls_context
from app.models.platform.guild import GuildRole
from app.testing import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_user,
)

pytestmark = pytest.mark.database


async def _access(
    session: AsyncSession, initiative_id: int | None, user_id: int, write: bool = False
) -> bool:
    """Ask the policy function directly — it is the single rule every content
    policy defers to, so this is the decision under test."""
    return (
        await session.exec(
            text(
                "SELECT public.initiative_access(:initiative_id, :user_id, :need_write)"
            ).bindparams(initiative_id=initiative_id, user_id=user_id, need_write=write)
        )
    ).scalar()


@pytest.fixture
async def guild_member(session):
    """A guild member who belongs to no initiative — the case that separates
    guild scope from initiative scope."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild)
    return user, guild


class TestGuildScope:
    async def test_a_guild_level_row_is_readable_by_a_routed_member(
        self, session, role_session, guild_member
    ):
        user, guild = guild_member
        s = await role_session("app_user")
        await set_rls_context(
            s, user_id=user.id, guild_id=guild.id, guild_role=GuildRole.member.value
        )
        assert await _access(s, None, user.id) is True

    async def test_a_guild_level_row_is_writable_at_this_layer(
        self, session, role_session, guild_member
    ):
        """The initiative gate does not decide writes on a row that belongs to no
        initiative — grants do, one layer up. This pins that the policy itself
        does not silently withhold write."""
        user, guild = guild_member
        s = await role_session("app_user")
        await set_rls_context(
            s, user_id=user.id, guild_id=guild.id, guild_role=GuildRole.member.value
        )
        assert await _access(s, None, user.id, write=True) is True

    async def test_initiative_rows_are_untouched_by_the_null_branch(
        self, session, role_session, guild_member
    ):
        """The change must not widen anything for rows that *do* name an
        initiative: a member of none still reaches none."""
        user, guild = guild_member
        other = await create_user(session)
        await create_guild_membership(session, user=other, guild=guild)
        initiative = await create_initiative(session, guild=guild, creator=other)

        s = await role_session("app_user")
        await set_rls_context(
            s, user_id=user.id, guild_id=guild.id, guild_role=GuildRole.member.value
        )
        assert await _access(s, initiative.id, user.id) is False
        assert await _access(s, initiative.id, user.id, write=True) is False

    async def test_a_member_of_the_initiative_still_reaches_it(
        self, session, role_session
    ):
        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        await create_guild_membership(session, user=user, guild=guild)
        initiative = await create_initiative(session, guild=guild, creator=user)

        s = await role_session("app_user")
        await set_rls_context(
            s, user_id=user.id, guild_id=guild.id, guild_role=GuildRole.member.value
        )
        assert await _access(s, initiative.id, user.id) is True


class TestBoundariesStillHold:
    async def test_guild_scope_does_not_reach_across_guilds(
        self, session, role_session, guild_member
    ):
        """Guild scope is the *schema* boundary, so a session routed into one
        guild sees that guild's guild-level rows and no other's. Checked on the
        thing that actually confines it — the search path the role is routed to
        — since the function itself knows nothing about guilds."""
        user, guild = guild_member
        stranger = await create_user(session)
        other_guild = await create_guild(session, creator=stranger)

        s = await role_session("app_user")
        await set_rls_context(
            s, user_id=user.id, guild_id=guild.id, guild_role=GuildRole.member.value
        )
        search_path = (
            await s.exec(text("SELECT current_setting('search_path')"))
        ).scalar()
        assert search_path.startswith(f"guild_{guild.id}")
        assert f"guild_{other_guild.id}" not in search_path

    async def test_an_unrouted_session_reaches_no_guild_content_at_all(
        self, session, role_session, guild_member
    ):
        """Guild-level rows are not reachable without being routed first.

        Not expressed through `initiative_access`: that function resolves
        `initiative_members` through the routed search path, so calling it
        unrouted raises rather than answering. Which is the point — the boundary
        that protects a guild-level row from an unrouted session is the schema
        and the role, one layer below the policy, and that is what this asserts.
        """
        _, guild = guild_member
        s = await role_session("app_user")
        with pytest.raises(DBAPIError):
            await s.exec(text(f"SELECT count(*) FROM guild_{guild.id}.calendars"))
