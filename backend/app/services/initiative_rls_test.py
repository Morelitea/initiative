"""DB-level initiative RLS isolation tests.

These bypass the app layer entirely: they set the guild RLS context and run a raw
``SELECT`` as the assumed guild role, so a missing/incorrect policy fails the
assertion (the app-layer ``membership.py`` clause can't paper over it). Proves the
``public.initiative_access`` policies on the guild content tables actually enforce
initiative-membership for non-admin guild roles.
"""

import pytest
from sqlalchemy import text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import set_rls_context
from app.models.guild import GuildRole
from app.models.project import Project
from app.testing import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_project,
    create_user,
)


@pytest.mark.integration
async def test_non_admin_member_sees_only_their_initiatives_content(
    session: AsyncSession,
):
    """Under the guild role, a non-admin member sees content rows only for the
    initiatives they belong to — a co-guild-member's other initiative is hidden by
    RLS, not just by app code. A guild admin sees everything in the guild."""
    owner = await create_user(session, email="irls-owner@example.com")
    member = await create_user(session, email="irls-member@example.com")
    guild = await create_guild(session, creator=owner)
    await create_guild_membership(
        session, user=member, guild=guild, role=GuildRole.member
    )
    init_a = await create_initiative(session, guild, owner, name="Alpha")
    init_b = await create_initiative(session, guild, owner, name="Bravo")
    await create_initiative_member(session, init_a, member)  # member of Alpha only
    await create_project(session, init_a, owner, name="A-Proj")
    await create_project(session, init_b, owner, name="B-Proj")
    await session.commit()

    # Act as the guild role with this member's (non-admin) context — RLS applies.
    await set_rls_context(
        session, user_id=member.id, guild_id=guild.id, guild_role="member"
    )
    member_view = set((await session.execute(select(Project.name))).scalars().all())
    assert "A-Proj" in member_view, "member must see their own initiative's project"
    assert "B-Proj" not in member_view, (
        "RLS must hide a project in an initiative the member doesn't belong to"
    )

    # A guild admin (current_guild_role='admin') sees every initiative's content.
    await set_rls_context(
        session, user_id=member.id, guild_id=guild.id, guild_role="admin"
    )
    admin_view = set((await session.execute(select(Project.name))).scalars().all())
    assert {"A-Proj", "B-Proj"} <= admin_view

    await session.execute(text("RESET ROLE"))
