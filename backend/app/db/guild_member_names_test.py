"""The name in the guild projection is the one the member set there.

``public.guild_member_profiles`` is what a guild-routed session reads a person
from, and the name it answers with is ``guild_memberships.display_name`` for
the guild the request is routed into — never the account's own name, and
whatever the guild's ``show_member_names`` says. With none set, the column is
empty and the handle is what renders.

These read the projection through the request-path role rather than the
superuser-backed ``session`` fixture, which answers for a role nothing runs as.
"""

from sqlmodel import select

from app.db.request_context import ContentGrantee
from app.db.session import set_rls_context
from app.models.platform.user import User
from app.models.platform.user_profile_view import MemberProfile
from app.testing import route_as
from app.testing.factories import create_guild, create_guild_membership, create_user


async def _name_read_in(role_session, *, user, guild):
    """What the guild projection answers for ``user``, read as a member of
    ``guild``."""
    s = await role_session("app_user")
    await route_as(s, user_id=user.id, guild_id=guild.id)
    return (
        await s.exec(select(MemberProfile.full_name).where(MemberProfile.id == user.id))
    ).one()


async def test_a_guild_reads_the_name_set_there_and_nowhere_else(session, role_session):
    user = await create_user(session, full_name="Ana Real")
    named = await create_guild(session, creator=user, show_member_names=False)
    shows_names = await create_guild(session, creator=user, show_member_names=True)
    await create_guild_membership(session, user=user, guild=named, display_name="Ana Q")
    await create_guild_membership(session, user=user, guild=shows_names)

    assert await _name_read_in(role_session, user=user, guild=named) == "Ana Q"
    # The account's name does not reach a guild, whatever the guild asks for.
    assert await _name_read_in(role_session, user=user, guild=shows_names) is None


async def test_the_account_row_still_carries_its_name(session, role_session):
    """Addressing somebody outside a guild — a notification, an email — reads
    the account on the system engine, which is a different route."""
    user = await create_user(session, full_name="Ana Real")
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild, display_name="Ana Q")

    s = await role_session("app_admin")
    name = (await s.exec(select(User.full_name).where(User.id == user.id))).one()

    assert name == "Ana Real"


async def test_a_grant_reads_the_name_set_in_the_guild_it_reaches(
    session, role_session
):
    """A time-bound grant names its guild in its own field and leaves the
    membership one unset, so the projection asks about both."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild, display_name="Ana Q")
    visitor = await create_user(session)

    s = await role_session("app_user")
    await set_rls_context(
        s, ContentGrantee(guild_id=guild.id, user_id=visitor.id, read_write=False)
    )
    assert (
        await s.exec(select(MemberProfile.full_name).where(MemberProfile.id == user.id))
    ).one() == "Ana Q"
