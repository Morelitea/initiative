"""What a request-path session may write on ``public.users``.

An account belongs to the person it names. Reading other people is ordinary —
rosters, pickers and member management all do it — but a request-path session
writes one row, its own, whichever role it has assumed. Platform user
management (reactivate, platform role, delete, avatar takedown) runs on the
system engine instead, where a capability check is the authorization.

These run under the real ``app_user`` login with a routed context rather than
the superuser-backed ``session`` fixture: the subject is what a policy does,
and a superuser session would show none of it.
"""

import pytest
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import set_rls_context
from app.models.platform.guild import GuildRole
from app.models.platform.user import UserRole
from app.testing import create_guild, create_guild_membership, create_user

pytestmark = [pytest.mark.integration, pytest.mark.database]

# The columns an account holder alone writes.
CREDENTIAL_COLUMNS = ("hashed_password", "email_hash", "email_encrypted")


async def _update_returning(
    session: AsyncSession, user_id: int, column: str, value: str
) -> list[int]:
    """Run one column update and report which rows it actually reached.

    ``RETURNING`` rather than ``rowcount``: a policy that filters the row makes
    the statement succeed against nothing, which is the outcome under test.
    """
    result = await session.exec(
        text(
            f"UPDATE public.users SET {column} = :v WHERE id = :i RETURNING id"
        ).bindparams(v=value, i=user_id)
    )
    return [row[0] for row in result.all()]


async def _count_visible(session: AsyncSession, user_id: int) -> int:
    return (
        await session.exec(
            text("SELECT count(*) FROM public.users WHERE id = :i").bindparams(
                i=user_id
            )
        )
    ).scalar()


class TestGuildSession:
    """A guild-scoped session — ``SET ROLE guild_<id>``, the request path for
    everything under ``/g/{guild_id}``."""

    @pytest.fixture
    async def guild_with_two_members(self, session):
        admin = await create_user(session)
        guild = await create_guild(session, creator=admin)
        member = await create_user(session)
        await create_guild_membership(
            session, user=member, guild=guild, role=GuildRole.member
        )
        return admin, member, guild

    async def test_reads_another_member(
        self, session, role_session, guild_with_two_members
    ):
        admin, member, guild = guild_with_two_members
        s = await role_session("app_user")
        await set_rls_context(
            s, user_id=admin.id, guild_id=guild.id, guild_role="admin"
        )

        assert await _count_visible(s, member.id) == 1

    @pytest.mark.parametrize("column", CREDENTIAL_COLUMNS)
    async def test_does_not_write_another_members_credentials(
        self, session, role_session, guild_with_two_members, column
    ):
        admin, member, guild = guild_with_two_members
        s = await role_session("app_user")
        await set_rls_context(
            s, user_id=admin.id, guild_id=guild.id, guild_role="admin"
        )

        assert await _update_returning(s, member.id, column, "rewritten") == []

    async def test_writes_its_own_row(
        self, session, role_session, guild_with_two_members
    ):
        admin, _member, guild = guild_with_two_members
        s = await role_session("app_user")
        await set_rls_context(
            s, user_id=admin.id, guild_id=guild.id, guild_role="admin"
        )

        assert await _update_returning(s, admin.id, "full_name", "Renamed") == [
            admin.id
        ]


class TestPlatformSession:
    """A platform-tier session — ``SET ROLE platform_<tier>``, the request path
    for everything outside a guild."""

    @pytest.fixture
    async def moderator_and_subject(self, session):
        moderator = await create_user(session, role=UserRole.moderator)
        subject = await create_user(session)
        return moderator, subject

    async def test_moderator_reads_every_account(
        self, session, role_session, moderator_and_subject
    ):
        moderator, subject = moderator_and_subject
        s = await role_session("app_user")
        await set_rls_context(s, user_id=moderator.id, platform_role="moderator")

        assert await _count_visible(s, subject.id) == 1

    @pytest.mark.parametrize("column", CREDENTIAL_COLUMNS)
    async def test_moderator_does_not_write_another_accounts_credentials(
        self, session, role_session, moderator_and_subject, column
    ):
        moderator, subject = moderator_and_subject
        s = await role_session("app_user")
        await set_rls_context(s, user_id=moderator.id, platform_role="moderator")

        assert await _update_returning(s, subject.id, column, "rewritten") == []

    async def test_a_member_changes_their_own_password(
        self, session, role_session, moderator_and_subject
    ):
        _moderator, subject = moderator_and_subject
        s = await role_session("app_user")
        await set_rls_context(s, user_id=subject.id, platform_role="member")

        assert await _update_returning(
            s, subject.id, "hashed_password", "self-chosen"
        ) == [subject.id]
