"""The name in the guild projection answers to the guild's own setting.

``public.guild_member_profiles`` is what a guild-routed session reads a person
from, and whether it comes back with a real name is that guild's
``show_member_names`` — read by the projection off the guild row, so the
request carries no answer of its own to disagree with it.

These read the projection through the request-path role rather than the
superuser-backed ``session`` fixture, which answers for a role nothing runs as.
"""

from sqlmodel import select

from app.db.session import set_rls_context
from app.models.platform.user import User
from app.models.platform.user_profile_view import MemberProfile
from app.testing.factories import create_guild, create_guild_membership, create_user
from app.testing import route_as


async def _name_read_in(role_session, *, user, guild):
    """What the guild projection answers for ``user``, read as a member of
    ``guild``. Nothing here says whether names are rendered: routing into the
    guild is the whole of the question, which is the point."""
    s = await role_session("app_user")
    await route_as(s, user_id=user.id, guild_id=guild.id)
    return (
        await s.exec(select(MemberProfile.full_name).where(MemberProfile.id == user.id))
    ).one()


async def _member_of(session, **guild_kwargs):
    user = await create_user(session, full_name="Ana Real")
    guild = await create_guild(session, creator=user, **guild_kwargs)
    await create_guild_membership(session, user=user, guild=guild)
    return user, guild


async def test_a_guild_that_renders_names_reads_one(session, role_session):
    user, guild = await _member_of(session, show_member_names=True)

    assert await _name_read_in(role_session, user=user, guild=guild) == "Ana Real"


async def test_a_guild_that_renders_handles_reads_no_name(session, role_session):
    """The setting is the projection's answer, not a later edit to it: the
    column comes back empty from Postgres, for a member of the guild."""
    user, guild = await _member_of(session, show_member_names=False)

    assert await _name_read_in(role_session, user=user, guild=guild) is None


async def test_a_listed_guild_reads_no_name(session, role_session):
    """Listing a guild turns its real names off in the same write, so a
    community guild reaches the projection with nothing to render."""
    user, guild = await _member_of(session, show_member_names=True)
    guild.categories = ["other"]
    guild.has_adult_content = False
    guild.is_community = True
    session.add(guild)
    await session.commit()
    await session.refresh(guild)

    assert guild.show_member_names is False
    assert await _name_read_in(role_session, user=user, guild=guild) is None


async def test_the_account_row_still_carries_the_name(session, role_session):
    """Addressing somebody — a notification, an email — reads the account on the
    system engine, which is a different route and keeps the name it needs."""
    user, _guild = await _member_of(session, show_member_names=False)

    s = await role_session("app_admin")
    name = (await s.exec(select(User.full_name).where(User.id == user.id))).one()

    assert name == "Ana Real"


async def test_two_guilds_answer_differently_on_one_session(session, role_session):
    """The same account, read from a guild that renders names and one that does
    not. The answer follows the guild being read, not anything the caller
    carried in."""
    user = await create_user(session, full_name="Ana Real")
    loud = await create_guild(session, creator=user, show_member_names=True)
    quiet = await create_guild(session, creator=user, show_member_names=False)
    await create_guild_membership(session, user=user, guild=loud)
    await create_guild_membership(session, user=user, guild=quiet)

    assert await _name_read_in(role_session, user=user, guild=loud) == "Ana Real"
    assert await _name_read_in(role_session, user=user, guild=quiet) is None


async def test_a_grant_reads_the_guild_it_reaches(session, role_session):
    """A time-bound grant names its guild in its own field and leaves the
    membership one unset, so the projection asks about both. A grantee reading
    a guild that renders names gets them, the same as a member would."""
    user, guild = await _member_of(session, show_member_names=True)
    visitor = await create_user(session)

    s_ = await role_session("app_user")
    await set_rls_context(
        s_,
        user_id=visitor.id,
        pam_guild_id=guild.id,
        pam_read=True,
    )
    assert (
        await s_.exec(
            select(MemberProfile.full_name).where(MemberProfile.id == user.id)
        )
    ).one() == "Ana Real"


async def test_a_grant_into_a_quiet_guild_still_reads_no_name(session, role_session):
    user, guild = await _member_of(session, show_member_names=False)
    visitor = await create_user(session)

    s_ = await role_session("app_user")
    await set_rls_context(
        s_,
        user_id=visitor.id,
        pam_guild_id=guild.id,
        pam_read=True,
    )
    assert (
        await s_.exec(
            select(MemberProfile.full_name).where(MemberProfile.id == user.id)
        )
    ).one() is None
