"""Tests for the OIDC sync auto-transfer of orphaned projects.

OIDC group sync removes a user from a guild non-interactively, so we
can't ask them where to transfer their owned projects (the way the
``leave_guild`` endpoint does). The sync re-homes the projects on its
own, picking an initiative manager first and a guild admin as the
fallback. These tests pin the picker rules so the orphan-project
regression we just shipped a fix for can't quietly come back through
the OIDC path.
"""

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.guild import GuildRole
from app.models.project import Project
from app.models.user import UserStatus
from app.services.oidc_sync import (
    _auto_transfer_owned_projects,
    _pick_fallback_owner,
)
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_project,
    create_user,
)


@pytest.mark.unit
@pytest.mark.service
async def test_pick_fallback_prefers_initiative_manager(session: AsyncSession):
    """When an initiative has a manager (other than the leaver), the
    picker returns them rather than falling through to a guild admin
    who isn't on the initiative."""
    from app.models.initiative import InitiativeMember

    admin = await create_user(session, email="admin@example.com")
    manager = await create_user(session, email="manager@example.com")
    leaver = await create_user(session, email="leaver@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=manager, guild=guild, role=GuildRole.member)
    await create_guild_membership(session, user=leaver, guild=guild, role=GuildRole.member)
    initiative = await create_initiative(session, guild=guild, creator=admin)
    # ``create_initiative`` auto-adds the creator as project manager.
    # Drop that so the only initiative manager is ``manager`` and the
    # test actually exercises the manager-vs-admin preference.
    admin_membership = (
        await session.exec(
            select(InitiativeMember).where(
                InitiativeMember.initiative_id == initiative.id,
                InitiativeMember.user_id == admin.id,
            )
        )
    ).one()
    await session.delete(admin_membership)
    await session.commit()
    await create_initiative_member(
        session, initiative=initiative, user=manager, role_name="project_manager"
    )

    chosen = await _pick_fallback_owner(
        session,
        excluded_user_id=leaver.id,
        guild_id=guild.id,
        initiative_id=initiative.id,
    )
    assert chosen == manager.id


@pytest.mark.unit
@pytest.mark.service
async def test_pick_fallback_uses_guild_admin_when_no_manager(session: AsyncSession):
    admin = await create_user(session, email="admin@example.com")
    leaver = await create_user(session, email="leaver@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=leaver, guild=guild, role=GuildRole.member)
    initiative = await create_initiative(session, guild=guild, creator=admin)
    # The admin is auto-added as the initiative's project manager when
    # the initiative is created via the factory; remove that membership
    # so we exercise the "no manager" fallback path.
    from app.models.initiative import InitiativeMember

    admin_membership = (
        await session.exec(
            select(InitiativeMember).where(
                InitiativeMember.initiative_id == initiative.id,
                InitiativeMember.user_id == admin.id,
            )
        )
    ).one()
    await session.delete(admin_membership)
    await session.commit()

    chosen = await _pick_fallback_owner(
        session,
        excluded_user_id=leaver.id,
        guild_id=guild.id,
        initiative_id=initiative.id,
    )
    assert chosen == admin.id


@pytest.mark.unit
@pytest.mark.service
async def test_pick_fallback_skips_inactive_candidates(session: AsyncSession):
    """Deactivated / anonymized users can't act on projects, so the
    fallback picker has to skip them — handing a project to a husk
    just shifts the orphan."""
    admin = await create_user(session, email="admin@example.com", status=UserStatus.deactivated)
    leaver = await create_user(session, email="leaver@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=leaver, guild=guild, role=GuildRole.member)
    initiative = await create_initiative(session, guild=guild, creator=admin)

    chosen = await _pick_fallback_owner(
        session,
        excluded_user_id=leaver.id,
        guild_id=guild.id,
        initiative_id=initiative.id,
    )
    assert chosen is None


@pytest.mark.unit
@pytest.mark.service
async def test_auto_transfer_reassigns_owner(session: AsyncSession):
    admin = await create_user(session, email="admin@example.com")
    leaver = await create_user(session, email="leaver@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=leaver, guild=guild, role=GuildRole.member)
    initiative = await create_initiative(session, guild=guild, creator=admin)
    project = await create_project(session, initiative=initiative, owner=leaver)

    await _auto_transfer_owned_projects(session, user_id=leaver.id, guild_id=guild.id)
    await session.flush()

    refreshed = (
        await session.exec(select(Project).where(Project.id == project.id))
    ).one()
    assert refreshed.owner_id == admin.id


@pytest.mark.unit
@pytest.mark.service
async def test_auto_transfer_leaves_orphan_when_no_fallback(session: AsyncSession, caplog):
    """No active fallback → log a warning, leave ``owner_id`` pointing at
    the departing user. The project is still orphaned in this case, but
    we don't crash the sync — there's nothing else to do."""
    # Only the leaver exists. They're a member (not admin) of the guild,
    # the sole manager of the initiative, and the project owner. With
    # the leaver excluded, no other candidate is available — neither a
    # different initiative manager nor a guild admin.
    leaver = await create_user(session, email="leaver@example.com")
    guild = await create_guild(session, creator=leaver)
    await create_guild_membership(session, user=leaver, guild=guild, role=GuildRole.member)
    initiative = await create_initiative(session, guild=guild, creator=leaver)
    project = await create_project(session, initiative=initiative, owner=leaver)

    with caplog.at_level("WARNING"):
        await _auto_transfer_owned_projects(session, user_id=leaver.id, guild_id=guild.id)

    refreshed = (
        await session.exec(select(Project).where(Project.id == project.id))
    ).one()
    assert refreshed.owner_id == leaver.id
    assert any("no fallback owner" in rec.message for rec in caplog.records)
