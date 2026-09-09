"""The guild's own view of who its members are.

``public.guild_member_profiles`` projects an account for any id, deliberately:
a person is a person wherever they are looked up, and every name the app
renders is read through it.

``public.current_guild_members`` is the same projection narrowed to the guild a
request is routed into, and it exists because the query surface names relations
and gets their rows. What these check is that narrowing: the reader's own guild,
nobody else's, and nothing at all for a session routed nowhere.
"""

import pytest
from sqlalchemy import text

from app.testing import create_guild, create_guild_membership, create_user

pytestmark = pytest.mark.database

_COUNT = "SELECT count(*) FROM public.current_guild_members"
_IDS = "SELECT id FROM public.current_guild_members ORDER BY id"


async def _routed(conn, guild_id: int | None, *, pam: bool = False):
    setting = "app.pam_guild_id" if pam else "app.current_guild_id"
    await conn.execute(
        text("SELECT set_config(:name, :value, true)"),
        {"name": setting, "value": "" if guild_id is None else str(guild_id)},
    )


class TestItAnswersForTheRoutedGuild:
    async def test_a_member_of_one_guild_is_not_in_anothers(self, session, engine):
        mine = await create_user(session)
        theirs = await create_user(session)
        one = await create_guild(session, creator=mine)
        two = await create_guild(session, creator=theirs)
        # Membership is the whole of it: an account exists platform-wide and
        # appears here only where it has joined.
        await create_guild_membership(session, user=mine, guild=one)
        await create_guild_membership(session, user=theirs, guild=two)

        async with engine.connect() as conn:
            async with conn.begin():
                await _routed(conn, one.id)
                here = set((await conn.execute(text(_IDS))).scalars().all())
            async with conn.begin():
                await _routed(conn, two.id)
                there = set((await conn.execute(text(_IDS))).scalars().all())

        assert mine.id in here and theirs.id not in here
        assert theirs.id in there and mine.id not in there

    async def test_somebody_in_both_is_in_both(self, session, engine):
        person = await create_user(session)
        one = await create_guild(session, creator=person)
        two = await create_guild(session)
        await create_guild_membership(session, user=person, guild=one)
        await create_guild_membership(session, user=person, guild=two)

        async with engine.connect() as conn:
            for guild in (one, two):
                async with conn.begin():
                    await _routed(conn, guild.id)
                    found = (await conn.execute(text(_IDS))).scalars().all()
                    assert person.id in found

    async def test_a_session_routed_nowhere_sees_nobody(self, session, engine):
        person = await create_user(session)
        guild = await create_guild(session, creator=person)
        await create_guild_membership(session, user=person, guild=guild)
        async with engine.connect() as conn:
            async with conn.begin():
                await _routed(conn, None)
                assert await conn.scalar(text(_COUNT)) == 0

    async def test_a_grantee_is_routed_by_the_grant(self, session, engine):
        """A break-glass session leaves the guild unset and carries the grant
        instead, so the narrowing reads that."""
        person = await create_user(session)
        guild = await create_guild(session, creator=person)
        await create_guild_membership(session, user=person, guild=guild)

        async with engine.connect() as conn:
            async with conn.begin():
                await _routed(conn, None)
                await _routed(conn, guild.id, pam=True)
                assert person.id in (await conn.execute(text(_IDS))).scalars().all()

    async def test_it_never_widens_past_the_account_projection(self, session, engine):
        """It narrows the guild projection and adds nothing to it: a guild
        cannot see more of a person here than anywhere else."""
        person = await create_user(session)
        guild = await create_guild(session, creator=person)
        await create_guild_membership(session, user=person, guild=guild)

        async with engine.connect() as conn:
            async with conn.begin():
                await _routed(conn, guild.id)
                everywhere = await conn.scalar(
                    text("SELECT count(*) FROM public.guild_member_profiles")
                )
                here = await conn.scalar(text(_COUNT))
        assert here <= everywhere


class TestTheRolesThatReadIt:
    """The shared floors are kept as one set, and the query role reads through
    the read-only one."""

    @pytest.mark.parametrize("role", ["app_guild_base", "app_guild_base_ro"])
    async def test_both_floors_read_it(self, engine, role):
        async with engine.connect() as conn:
            assert await conn.scalar(
                text(
                    "SELECT has_table_privilege(:r, "
                    "'public.current_guild_members', 'SELECT')"
                ),
                {"r": role},
            )

    async def test_nobody_may_write_it(self, engine):
        """It is a read of a read.

        The schema hands every new relation in ``public`` full DML to the
        request-path floors, so a read-only one has to say so."""
        async with engine.connect() as conn:
            for role in ("app_guild_base", "app_guild_base_ro", "platform_base"):
                for verb in ("INSERT", "UPDATE", "DELETE"):
                    assert not await conn.scalar(
                        text(
                            "SELECT has_table_privilege(:r, "
                            "'public.current_guild_members', :v)"
                        ),
                        {"r": role, "v": verb},
                    ), f"{role} may {verb}"

    async def test_the_platform_floor_does_not_read_it(self, engine):
        """A request with no guild gets no rows from it, and holds no
        privilege on it either: it is the guild path's relation."""
        async with engine.connect() as conn:
            assert not await conn.scalar(
                text(
                    "SELECT has_table_privilege('platform_base', "
                    "'public.current_guild_members', 'SELECT')"
                )
            )
