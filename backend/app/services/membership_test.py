"""Tests for the shared guild/initiative membership helpers."""

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.guild import GuildRole
from app.models.initiative import Initiative
from app.services import membership as membership_service
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_user,
)


async def _setup(session: AsyncSession):
    admin = await create_user(session, email="admin@example.com")
    member = await create_user(session, email="member@example.com")
    outsider = await create_user(session, email="outsider@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    await create_guild_membership(
        session, user=member, guild=guild, role=GuildRole.member
    )
    initiative = await create_initiative(session, guild, admin)
    await create_initiative_member(session, initiative, member)
    return admin, member, outsider, guild, initiative


@pytest.mark.integration
async def test_initiative_member_user_ids_batch(session: AsyncSession):
    admin, member, outsider, _guild, initiative = await _setup(session)

    found = await membership_service.initiative_member_user_ids(
        session, initiative.id, (admin.id, member.id, outsider.id)
    )
    assert found == {admin.id, member.id}

    # Unrestricted: every member, still one query.
    assert await membership_service.initiative_member_user_ids(
        session, initiative.id
    ) == {admin.id, member.id}

    # Empty batch short-circuits without a query.
    assert (
        await membership_service.initiative_member_user_ids(session, initiative.id, ())
        == set()
    )


@pytest.mark.integration
async def test_user_member_initiative_ids(session: AsyncSession):
    admin, member, outsider, _guild, initiative = await _setup(session)

    assert await membership_service.user_member_initiative_ids(
        session, member.id, (initiative.id,)
    ) == {initiative.id}
    assert (
        await membership_service.user_member_initiative_ids(
            session, outsider.id, (initiative.id,)
        )
        == set()
    )
    assert await membership_service.is_initiative_member(
        session, initiative.id, member.id
    )
    assert not await membership_service.is_initiative_member(
        session, initiative.id, outsider.id
    )


@pytest.mark.integration
async def test_guild_role_map_batch(session: AsyncSession):
    admin, member, outsider, guild, _initiative = await _setup(session)

    roles = await membership_service.guild_role_map(
        session, guild.id, (admin.id, member.id, outsider.id)
    )
    assert roles == {admin.id: GuildRole.admin, member.id: GuildRole.member}

    assert await membership_service.is_guild_admin(session, guild.id, admin.id)
    assert not await membership_service.is_guild_admin(session, guild.id, member.id)
    assert not await membership_service.is_guild_admin(session, guild.id, outsider.id)

    found = await membership_service.guild_member_user_ids(
        session, guild.id, (admin.id, outsider.id)
    )
    assert found == {admin.id}


@pytest.mark.integration
async def test_initiative_member_clause_filters_rows(session: AsyncSession):
    """The clause builders compose into real statements."""
    admin, member, outsider, _guild, initiative = await _setup(session)

    for user, expected in ((member, [initiative.id]), (outsider, [])):
        stmt = select(Initiative.id).where(
            membership_service.initiative_member_clause(user.id, Initiative.id)
        )
        assert list((await session.execute(stmt)).scalars().all()) == expected


@pytest.mark.integration
async def test_initiative_scope_clause_legs(session: AsyncSession):
    """member / guild-admin / (no standing platform-bypass) legs of the clause."""
    from app.models.user import UserRole

    admin, member, outsider, _guild, initiative = await _setup(session)
    platform_admin = await create_user(
        session, email="platform@example.com", role=UserRole.admin
    )

    async def scoped_ids(user) -> list[int]:
        stmt = select(Initiative.id).where(
            membership_service.initiative_scope_clause(
                user.id, Initiative.id, Initiative.guild_id
            )
        )
        return list((await session.execute(stmt)).scalars().all())

    assert await scoped_ids(member) == [initiative.id]  # member leg
    assert await scoped_ids(admin) == [initiative.id]  # guild-admin leg
    assert await scoped_ids(outsider) == []  # no leg
    # Phase 3: ``data.bypass`` is NOT a standing leg any more — a platform admin
    # with no membership and no live grant sees nothing (they must break-glass).
    assert await scoped_ids(platform_admin) == []


@pytest.mark.integration
async def test_initiative_scope_clause_pam_leg(session: AsyncSession):
    """A live read PAM grant satisfies the scope clause via initiative_access's
    pam_read leg; a non-member with no grant matches nothing. (The grant's
    guild-scoping is enforced by schema routing + RLS — see access_grants_rls_test.)
    """
    from app.db.session import set_rls_context

    _admin, _member, outsider, guild, initiative = await _setup(session)

    def stmt():
        return select(Initiative.id).where(
            membership_service.initiative_scope_clause(
                outsider.id, Initiative.id, Initiative.guild_id
            )
        )

    # Routed as a read PAM grantee for this guild (sets pam_read + routes into the
    # guild schema), exactly like the request path does.
    await set_rls_context(
        session, user_id=outsider.id, pam_guild_id=guild.id, pam_read=True
    )
    assert list((await session.execute(stmt())).scalars().all()) == [initiative.id]

    # Same outsider routed as a (non-)member with no grant: matches nothing.
    await set_rls_context(
        session, user_id=outsider.id, guild_id=guild.id, guild_role="member"
    )
    assert list((await session.execute(stmt())).scalars().all()) == []
