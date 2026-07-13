"""
Integration tests for initiative endpoints.

Tests the initiative API endpoints at /api/v1/initiatives including:
- Listing initiatives
- Creating initiatives
- Updating initiatives
- Deleting initiatives
- Managing initiative members (add, remove, update roles)
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.testing.factories import create_initiative


@pytest.mark.integration
async def test_list_initiatives_as_admin_shows_all(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that guild admin can see all initiatives."""
    admin = await acting_user(guild_role=GuildRole.admin)

    # Create multiple initiatives (factory creates builtin roles + PM membership)
    await create_initiative(session, admin.guild, admin.user, name="Initiative 1")
    await create_initiative(session, admin.guild, admin.user, name="Initiative 2")

    response = await client.get(admin.g("/initiatives/"), headers=admin.headers)

    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 2
    initiative_names = {init["name"] for init in data}
    assert "Initiative 1" in initiative_names
    assert "Initiative 2" in initiative_names


@pytest.mark.integration
async def test_list_initiatives_as_member_shows_only_membership(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that regular members only see initiatives they're part of."""
    admin = await acting_user(guild_role=GuildRole.admin)

    # Create two initiatives
    initiative1 = await create_initiative(
        session, admin.guild, admin.user, name="Member's Initiative"
    )
    await create_initiative(session, admin.guild, admin.user, name="Other Initiative")

    # Add member to only initiative1
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=initiative1,
        initiative_role="member",
    )

    response = await client.get(member.g("/initiatives/"), headers=member.headers)

    assert response.status_code == 200
    data = response.json()
    initiative_names = {init["name"] for init in data}
    assert "Member's Initiative" in initiative_names
    assert "Other Initiative" not in initiative_names


@pytest.mark.integration
async def test_create_initiative_as_admin(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that guild admin can create initiatives."""
    admin = await acting_user(guild_role=GuildRole.admin)

    payload = {
        "name": "New Initiative",
        "description": "A test initiative",
        "color": "#FF0000",
    }

    response = await client.post(
        admin.g("/initiatives/"), headers=admin.headers, json=payload
    )

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "New Initiative"
    assert data["description"] == "A test initiative"
    assert data["color"] == "#FF0000"


@pytest.mark.integration
async def test_create_initiative_as_member_forbidden(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that regular members cannot create initiatives."""
    member = await acting_user(guild_role=GuildRole.member)

    payload = {"name": "New Initiative"}

    response = await client.post(
        member.g("/initiatives/"), headers=member.headers, json=payload
    )

    assert response.status_code == 403


@pytest.mark.integration
async def test_create_initiative_duplicate_name_fails(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that duplicate initiative names are rejected."""
    admin = await acting_user(guild_role=GuildRole.admin)

    # Create first initiative
    await create_initiative(
        session, admin.guild, admin.user, name="Existing Initiative"
    )

    payload = {"name": "Existing Initiative"}

    response = await client.post(
        admin.g("/initiatives/"), headers=admin.headers, json=payload
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "INITIATIVE_NAME_EXISTS"


@pytest.mark.integration
async def test_create_initiative_makes_creator_manager(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that creating an initiative makes the creator a manager."""
    admin = await acting_user(guild_role=GuildRole.admin)

    payload = {"name": "New Initiative"}

    response = await client.post(
        admin.g("/initiatives/"), headers=admin.headers, json=payload
    )

    assert response.status_code == 201
    data = response.json()
    assert len(data["members"]) == 1
    assert data["members"][0]["user"]["id"] == admin.user.id
    assert data["members"][0]["role"] == "project_manager"


@pytest.mark.integration
async def test_update_initiative_as_manager(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that initiative manager can update initiative."""
    # A plain guild member who creates (and therefore manages) an initiative.
    manager = await acting_user(guild_role=GuildRole.member, initiative=True)

    payload = {"name": "Updated Initiative", "description": "Updated description"}

    response = await client.patch(
        manager.g(f"/initiatives/{manager.initiative.id}"),
        headers=manager.headers,
        json=payload,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Initiative"
    assert data["description"] == "Updated description"


@pytest.mark.integration
async def test_update_initiative_as_admin(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that guild admin can update any initiative."""
    manager = await acting_user(guild_role=GuildRole.member, initiative=True)
    admin = await acting_user(guild_role=GuildRole.admin, guild=manager.guild)

    payload = {"name": "Admin Updated"}

    response = await client.patch(
        admin.g(f"/initiatives/{manager.initiative.id}"),
        headers=admin.headers,
        json=payload,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Admin Updated"


@pytest.mark.integration
async def test_update_initiative_as_regular_member_forbidden(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that regular members cannot update initiatives."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )

    payload = {"name": "Hacked Name"}

    response = await client.patch(
        member.g(f"/initiatives/{admin.initiative.id}"),
        headers=member.headers,
        json=payload,
    )

    assert response.status_code == 403


@pytest.mark.integration
async def test_update_initiative_duplicate_name_fails(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that renaming to existing name fails."""
    admin = await acting_user(guild_role=GuildRole.admin)

    initiative1 = await create_initiative(
        session, admin.guild, admin.user, name="Initiative 1"
    )
    await create_initiative(session, admin.guild, admin.user, name="Initiative 2")

    payload = {"name": "Initiative 2"}

    response = await client.patch(
        admin.g(f"/initiatives/{initiative1.id}"),
        headers=admin.headers,
        json=payload,
    )

    assert response.status_code == 409


# ── Archive ──────────────────────────────────────────────────────────────────


@pytest.mark.integration
async def test_initiative_is_archived_defaults_false(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A freshly created initiative is not archived."""
    admin = await acting_user(guild_role=GuildRole.admin)
    initiative = await create_initiative(session, admin.guild, admin.user, name="Fresh")

    response = await client.get(
        admin.g(f"/initiatives/{initiative.id}"), headers=admin.headers
    )

    assert response.status_code == 200
    assert response.json()["is_archived"] is False


@pytest.mark.integration
async def test_archive_initiative_via_patch(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A guild admin can archive (and unarchive) an initiative through PATCH; it
    stays in the list either way (the settings table manages it there)."""
    admin = await acting_user(guild_role=GuildRole.admin)
    initiative = await create_initiative(
        session, admin.guild, admin.user, name="Archivable"
    )

    archive = await client.patch(
        admin.g(f"/initiatives/{initiative.id}"),
        headers=admin.headers,
        json={"is_archived": True},
    )
    assert archive.status_code == 200
    assert archive.json()["is_archived"] is True

    # Archived initiatives are NOT removed from the list — only the sidebar
    # filters them client-side; the settings table must still see them.
    listing = await client.get(admin.g("/initiatives/"), headers=admin.headers)
    assert listing.status_code == 200
    archived = next(i for i in listing.json() if i["id"] == initiative.id)
    assert archived["is_archived"] is True

    unarchive = await client.patch(
        admin.g(f"/initiatives/{initiative.id}"),
        headers=admin.headers,
        json={"is_archived": False},
    )
    assert unarchive.status_code == 200
    assert unarchive.json()["is_archived"] is False


@pytest.mark.integration
async def test_archive_initiative_as_manager_forbidden(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Archiving is guild-admin only. A plain initiative manager (who may edit
    other settings here) is rejected when toggling is_archived."""
    # Creator becomes the initiative's PM (manager) but is not a guild admin.
    manager = await acting_user(guild_role=GuildRole.member, initiative=True)

    # A non-archive edit still works for a manager...
    ok = await client.patch(
        manager.g(f"/initiatives/{manager.initiative.id}"),
        headers=manager.headers,
        json={"description": "Edited by manager"},
    )
    assert ok.status_code == 200

    # ...but flipping is_archived is admin-only.
    forbidden = await client.patch(
        manager.g(f"/initiatives/{manager.initiative.id}"),
        headers=manager.headers,
        json={"is_archived": True},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"] == "GUILD_ADMIN_REQUIRED"


@pytest.mark.integration
async def test_delete_initiative_as_admin(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that guild admin can delete initiatives."""
    admin = await acting_user(guild_role=GuildRole.admin)
    initiative = await create_initiative(
        session, admin.guild, admin.user, name="To Delete"
    )

    response = await client.delete(
        admin.g(f"/initiatives/{initiative.id}"), headers=admin.headers
    )

    assert response.status_code == 204


@pytest.mark.integration
async def test_delete_initiative_as_manager_forbidden(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that initiative manager cannot delete initiatives."""
    manager = await acting_user(guild_role=GuildRole.member, initiative=True)

    response = await client.delete(
        manager.g(f"/initiatives/{manager.initiative.id}"), headers=manager.headers
    )

    assert response.status_code == 403


@pytest.mark.integration
async def test_delete_default_initiative_forbidden(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that default initiative cannot be deleted."""
    admin = await acting_user(guild_role=GuildRole.admin)

    # Create and mark as default
    initiative = await create_initiative(
        session, admin.guild, admin.user, name="Default Initiative", is_default=True
    )

    response = await client.delete(
        admin.g(f"/initiatives/{initiative.id}"), headers=admin.headers
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "INITIATIVE_CANNOT_DELETE_DEFAULT"


@pytest.mark.integration
async def test_get_initiative_members(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test getting all members of an initiative."""
    admin = await acting_user(guild_role=GuildRole.admin)
    initiative = await create_initiative(
        session, admin.guild, admin.user, name="Test Initiative"
    )
    member1 = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=initiative,
        initiative_role="member",
        email="member1@example.com",
        full_name="Member One",
    )
    member2 = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=initiative,
        initiative_role="member",
        email="member2@example.com",
        full_name="Member Two",
    )

    response = await client.get(
        admin.g(f"/initiatives/{initiative.id}/members"), headers=admin.headers
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 3
    emails = {user["email"] for user in data}
    assert admin.user.email in emails
    assert member1.user.email in emails
    assert member2.user.email in emails


@pytest.mark.integration
async def test_get_initiative_members_as_nonmember_guild_admin(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A guild admin sees the roster of an initiative they never joined —
    the same guild-admin override every other initiative read honors (they
    already see the initiative's content via the RLS admin leg, and the
    assignee / linked-member pickers need the roster). A plain guild member
    outside the initiative stays locked out."""
    creator = await acting_user(guild_role=GuildRole.member, initiative=True)
    other_admin = await acting_user(guild_role=GuildRole.admin, guild=creator.guild)

    response = await client.get(
        other_admin.g(f"/initiatives/{creator.initiative.id}/members"),
        headers=other_admin.headers,
    )
    assert response.status_code == 200
    emails = {user["email"] for user in response.json()}
    assert creator.user.email in emails

    outsider = await acting_user(guild_role=GuildRole.member, guild=creator.guild)
    response = await client.get(
        outsider.g(f"/initiatives/{creator.initiative.id}/members"),
        headers=outsider.headers,
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "INITIATIVE_NOT_A_MEMBER"


@pytest.mark.integration
async def test_add_initiative_member_as_manager(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that manager can add members to initiative."""
    manager = await acting_user(guild_role=GuildRole.member, initiative=True)
    new_member = await acting_user(guild_role=GuildRole.member, guild=manager.guild)

    payload = {"user_id": new_member.user.id, "role": "member"}

    response = await client.post(
        manager.g(f"/initiatives/{manager.initiative.id}/members"),
        headers=manager.headers,
        json=payload,
    )

    assert response.status_code == 200
    data = response.json()
    member_ids = {m["user"]["id"] for m in data["members"]}
    assert new_member.user.id in member_ids


@pytest.mark.integration
async def test_add_initiative_member_as_regular_member_forbidden(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that regular members cannot add members."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    new_member = await acting_user(guild_role=GuildRole.member, guild=admin.guild)

    payload = {"user_id": new_member.user.id, "role": "member"}

    response = await client.post(
        member.g(f"/initiatives/{admin.initiative.id}/members"),
        headers=member.headers,
        json=payload,
    )

    assert response.status_code == 403


@pytest.mark.integration
async def test_add_user_not_in_guild_fails(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that adding a user not in the guild fails."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    # An outsider with no membership in the admin's guild.
    outsider = await acting_user(email="outsider@example.com")

    payload = {"user_id": outsider.user.id, "role": "member"}

    response = await client.post(
        admin.g(f"/initiatives/{admin.initiative.id}/members"),
        headers=admin.headers,
        json=payload,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "INITIATIVE_USER_NOT_IN_GUILD"


@pytest.mark.integration
async def test_update_initiative_member_role(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test updating an initiative member's role."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )

    # Look up the PM role ID for this initiative
    from app.models.tenant.initiative import InitiativeRoleModel
    from sqlmodel import select

    pm_role_stmt = select(InitiativeRoleModel).where(
        InitiativeRoleModel.initiative_id == admin.initiative.id,
        InitiativeRoleModel.name == "project_manager",
    )
    pm_role = (await session.exec(pm_role_stmt)).one()

    payload = {"role_id": pm_role.id}

    response = await client.patch(
        admin.g(f"/initiatives/{admin.initiative.id}/members/{member.user.id}"),
        headers=admin.headers,
        json=payload,
    )

    assert response.status_code == 200
    data = response.json()
    member_roles = {m["user"]["id"]: m["role"] for m in data["members"]}
    assert member_roles[member.user.id] == "project_manager"


@pytest.mark.integration
async def test_guild_admin_cannot_be_assigned_member_role(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A guild admin is an implicit full-access member; assigning them a
    standard member (or custom) role is rejected — they may only be elevated to
    a manager role."""
    from app.models.tenant.initiative import InitiativeRoleModel
    from sqlmodel import select

    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    target_admin = await acting_user(
        guild_role=GuildRole.admin, guild=admin.guild, email="admin2@example.com"
    )

    member_role = (
        await session.exec(
            select(InitiativeRoleModel).where(
                InitiativeRoleModel.initiative_id == admin.initiative.id,
                InitiativeRoleModel.name == "member",
            )
        )
    ).one()

    response = await client.post(
        admin.g(f"/initiatives/{admin.initiative.id}/members"),
        headers=admin.headers,
        json={"user_id": target_admin.user.id, "role_id": member_role.id},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "INITIATIVE_GUILD_ADMIN_ROLE_RESTRICTED"


@pytest.mark.integration
async def test_guild_admin_can_be_assigned_manager_role(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A guild admin may be elevated to the manager role (for manager-style
    features like notifications)."""
    from app.models.tenant.initiative import InitiativeRoleModel
    from sqlmodel import select

    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    target_admin = await acting_user(
        guild_role=GuildRole.admin, guild=admin.guild, email="admin2@example.com"
    )

    pm_role = (
        await session.exec(
            select(InitiativeRoleModel).where(
                InitiativeRoleModel.initiative_id == admin.initiative.id,
                InitiativeRoleModel.name == "project_manager",
            )
        )
    ).one()

    response = await client.post(
        admin.g(f"/initiatives/{admin.initiative.id}/members"),
        headers=admin.headers,
        json={"user_id": target_admin.user.id, "role_id": pm_role.id},
    )

    assert response.status_code == 200
    data = response.json()
    member_roles = {m["user"]["id"]: m["role"] for m in data["members"]}
    assert member_roles[target_admin.user.id] == "project_manager"


@pytest.mark.integration
async def test_remove_initiative_member(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test removing an initiative member."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )

    response = await client.delete(
        admin.g(f"/initiatives/{admin.initiative.id}/members/{member.user.id}"),
        headers=admin.headers,
    )

    assert response.status_code == 200
    data = response.json()
    member_ids = {m["user"]["id"] for m in data["members"]}
    assert member.user.id not in member_ids


@pytest.mark.integration
async def test_cannot_remove_last_manager(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that removing the last manager fails."""
    manager = await acting_user(guild_role=GuildRole.member, initiative=True)

    response = await client.delete(
        manager.g(f"/initiatives/{manager.initiative.id}/members/{manager.user.id}"),
        headers=manager.headers,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "INITIATIVE_MUST_HAVE_PM"


@pytest.mark.integration
async def test_cannot_demote_last_manager(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that demoting the last manager fails."""
    manager = await acting_user(guild_role=GuildRole.member, initiative=True)

    # Look up the member role ID for this initiative
    from app.models.tenant.initiative import InitiativeRoleModel
    from sqlmodel import select

    member_role_stmt = select(InitiativeRoleModel).where(
        InitiativeRoleModel.initiative_id == manager.initiative.id,
        InitiativeRoleModel.name == "member",
    )
    member_role = (await session.exec(member_role_stmt)).one()

    payload = {"role_id": member_role.id}

    response = await client.patch(
        manager.g(f"/initiatives/{manager.initiative.id}/members/{manager.user.id}"),
        headers=manager.headers,
        json=payload,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "INITIATIVE_MUST_HAVE_PM"


@pytest.mark.integration
async def test_initiative_guild_isolation(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that initiatives are isolated by guild."""
    from app.testing.factories import create_guild, create_guild_membership

    # One user who is an admin of two distinct guilds.
    a = await acting_user(guild_role=GuildRole.admin)
    guild2 = await create_guild(session)
    await create_guild_membership(
        session, user=a.user, guild=guild2, role=GuildRole.admin
    )

    initiative1 = await create_initiative(
        session, a.guild, a.user, name="Guild 1 Initiative"
    )
    await create_initiative(session, guild2, a.user, name="Guild 2 Initiative")

    # Request with guild1 context
    response1 = await client.get(a.g("/initiatives/"), headers=a.headers)

    assert response1.status_code == 200
    data1 = response1.json()
    initiative_names1 = {init["name"] for init in data1}
    assert "Guild 1 Initiative" in initiative_names1
    assert "Guild 2 Initiative" not in initiative_names1

    # Cannot access guild1's initiative with guild2 context. Under schema-per-guild
    # ids are per-schema (not globally unique), so initiative1.id may collide with
    # a guild2 initiative — but it must never resolve to guild1's initiative.
    response2 = await client.get(
        f"/api/v1/g/{guild2.id}/initiatives/{initiative1.id}", headers=a.headers
    )

    if response2.status_code == 200:
        assert response2.json()["name"] != "Guild 1 Initiative"
    else:
        assert response2.status_code == 404


# ---------------------------------------------------------------------------
# Advanced-tool handoff endpoint
#
# All five gates must hold before a token is minted:
#   1. ADVANCED_TOOL_URL configured
#   2. Initiative exists in the active guild
#   3. User is guild admin OR initiative member
#   4. initiative.advanced_tools_enabled = true
#   5. User's role grants advanced_tools_enabled (managers bypass)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_advanced_tool_handoff_returns_404_when_url_unset(
    client: AsyncClient, session: AsyncSession, acting_user, monkeypatch
):
    """Without ADVANCED_TOOL_URL the embed isn't deployed, so the
    endpoint must look like it doesn't exist — not even an authorized
    user should be able to mint a token that has nowhere to go."""
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "ADVANCED_TOOL_URL", None)

    admin = await acting_user(guild_role=GuildRole.admin)
    initiative = await create_initiative(
        session, admin.guild, admin.user, name="Init", advanced_tools_enabled=True
    )

    response = await client.post(
        admin.g(f"/initiatives/{initiative.id}/advanced-tool/handoff"),
        headers=admin.headers,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "ADVANCED_TOOL_NOT_CONFIGURED"


@pytest.mark.integration
async def test_advanced_tool_handoff_returns_403_when_master_switch_off(
    client: AsyncClient, session: AsyncSession, acting_user, monkeypatch
):
    """The per-initiative master switch is the manager's opt-in. Even a
    guild admin can't bypass it — the embed's data plane likely doesn't
    have the initiative provisioned yet."""
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "ADVANCED_TOOL_URL", "https://embed.example.com")

    admin = await acting_user(guild_role=GuildRole.admin)
    initiative = await create_initiative(
        session, admin.guild, admin.user, name="Init", advanced_tools_enabled=False
    )

    response = await client.post(
        admin.g(f"/initiatives/{initiative.id}/advanced-tool/handoff"),
        headers=admin.headers,
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "ADVANCED_TOOL_NOT_ENABLED"


@pytest.mark.integration
async def test_advanced_tool_handoff_returns_403_for_non_member(
    client: AsyncClient, session: AsyncSession, acting_user, monkeypatch
):
    """Members of the guild who aren't members of the initiative get
    rejected — view access is initiative-scoped, not guild-scoped (for
    non-admins)."""
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "ADVANCED_TOOL_URL", "https://embed.example.com")

    admin = await acting_user(guild_role=GuildRole.admin)
    outsider = await acting_user(guild_role=GuildRole.member, guild=admin.guild)
    initiative = await create_initiative(
        session, admin.guild, admin.user, name="Init", advanced_tools_enabled=True
    )

    response = await client.post(
        outsider.g(f"/initiatives/{initiative.id}/advanced-tool/handoff"),
        headers=outsider.headers,
    )

    assert response.status_code == 403


@pytest.mark.integration
async def test_advanced_tool_handoff_returns_403_when_role_lacks_view_permission(
    client: AsyncClient, session: AsyncSession, acting_user, monkeypatch
):
    """An initiative member whose role does NOT grant
    ``advanced_tools_enabled`` must be refused. The default ``member``
    role is exactly this case — view permission is opt-in per role.
    Without this gate, role-level access control would be a no-op."""
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "ADVANCED_TOOL_URL", "https://embed.example.com")

    # Both users are guild members (not admins) so guild-admin bypass doesn't apply.
    # pm creates the initiative and is auto-added as project_manager.
    pm = await acting_user(
        guild_role=GuildRole.member, initiative=True, email="pm@example.com"
    )
    pm.initiative.advanced_tools_enabled = True
    session.add(pm.initiative)
    await session.commit()
    # member joins with the default member role (advanced_tools_enabled=False)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=pm.guild,
        initiative=pm.initiative,
        initiative_role="member",
        email="member@example.com",
    )

    response = await client.post(
        member.g(f"/initiatives/{pm.initiative.id}/advanced-tool/handoff"),
        headers=member.headers,
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "ADVANCED_TOOL_NOT_ENABLED"


@pytest.mark.integration
async def test_advanced_tool_handoff_succeeds_for_initiative_manager(
    client: AsyncClient, session: AsyncSession, acting_user, monkeypatch
):
    """The happy path: manager opens the panel, gets a token with
    ``scope=initiative``, the right initiative_id, and ``can_create``
    set so the embed can show edit affordances."""
    from app.core.config import settings as app_settings
    from app.core.security import ADVANCED_TOOL_AUDIENCE
    import jwt

    monkeypatch.setattr(app_settings, "ADVANCED_TOOL_URL", "https://embed.example.com")

    pm = await acting_user(guild_role=GuildRole.member, email="pm@example.com")
    initiative = await create_initiative(
        session, pm.guild, pm.user, name="Init", advanced_tools_enabled=True
    )

    response = await client.post(
        pm.g(f"/initiatives/{initiative.id}/advanced-tool/handoff"),
        headers=pm.headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "initiative"
    assert body["initiative_id"] == initiative.id
    assert body["iframe_url"] == "https://embed.example.com"
    assert body["expires_in_seconds"] > 0

    payload = jwt.decode(
        body["handoff_token"],
        app_settings.SECRET_KEY,
        # Hardcoded HS256 (not JWT_ALGORITHM) — the handoff signing
        # path explicitly uses HS256 in its no-private-key fallback, so
        # tests must assert against that algorithm directly. Decoupling
        # from JWT_ALGORITHM keeps these tests stable if the global
        # session-token algorithm is ever changed.
        algorithms=["HS256"],
        audience=ADVANCED_TOOL_AUDIENCE,
    )
    assert payload["sub"] == str(pm.user.id)
    assert payload["scope"] == "initiative"
    assert payload["initiative_id"] == initiative.id
    assert payload["is_manager"] is True
    assert payload["can_create"] is True


@pytest.mark.integration
async def test_advanced_tool_handoff_can_create_false_for_view_only_role(
    client: AsyncClient, session: AsyncSession, acting_user, monkeypatch
):
    """A custom role that grants view but not create gets a token with
    ``can_create=false`` so the embed hides creation UI. The token is
    still issued — view access is enough to load the panel."""
    from app.core.config import settings as app_settings
    from app.core.security import ADVANCED_TOOL_AUDIENCE
    from app.models.tenant.initiative import (
        InitiativeRoleModel,
        InitiativeRolePermission,
        PermissionKey,
    )
    import jwt
    from sqlmodel import select

    monkeypatch.setattr(app_settings, "ADVANCED_TOOL_URL", "https://embed.example.com")

    pm = await acting_user(
        guild_role=GuildRole.member, initiative=True, email="pm@example.com"
    )
    pm.initiative.advanced_tools_enabled = True
    session.add(pm.initiative)
    await session.commit()

    # Flip the default member role to grant view but not create
    member_role = (
        await session.exec(
            select(InitiativeRoleModel).where(
                InitiativeRoleModel.initiative_id == pm.initiative.id,
                InitiativeRoleModel.name == "member",
            )
        )
    ).one()
    view_perm = (
        await session.exec(
            select(InitiativeRolePermission).where(
                InitiativeRolePermission.initiative_role_id == member_role.id,
                InitiativeRolePermission.permission_key
                == PermissionKey.advanced_tools_enabled,
            )
        )
    ).one()
    view_perm.enabled = True
    session.add(view_perm)
    await session.commit()

    viewer = await acting_user(
        guild_role=GuildRole.member,
        guild=pm.guild,
        initiative=pm.initiative,
        initiative_role="member",
        email="viewer@example.com",
    )

    response = await client.post(
        viewer.g(f"/initiatives/{pm.initiative.id}/advanced-tool/handoff"),
        headers=viewer.headers,
    )

    assert response.status_code == 200
    payload = jwt.decode(
        response.json()["handoff_token"],
        app_settings.SECRET_KEY,
        # Hardcoded HS256 (not JWT_ALGORITHM) — the handoff signing
        # path explicitly uses HS256 in its no-private-key fallback, so
        # tests must assert against that algorithm directly. Decoupling
        # from JWT_ALGORITHM keeps these tests stable if the global
        # session-token algorithm is ever changed.
        algorithms=["HS256"],
        audience=ADVANCED_TOOL_AUDIENCE,
    )
    assert payload["is_manager"] is False
    assert payload["can_create"] is False


@pytest.mark.integration
async def test_advanced_tool_handoff_succeeds_for_guild_admin_non_member(
    client: AsyncClient, session: AsyncSession, acting_user, monkeypatch
):
    """Guild admins can mint a token even if they aren't an initiative
    member — admin override is the existing pattern for guild-wide
    operational access."""
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "ADVANCED_TOOL_URL", "https://embed.example.com")

    admin = await acting_user(guild_role=GuildRole.admin, email="admin@example.com")
    pm = await acting_user(
        guild_role=GuildRole.member, guild=admin.guild, email="pm@example.com"
    )
    initiative = await create_initiative(
        session, admin.guild, pm.user, name="Init", advanced_tools_enabled=True
    )
    # Admin is intentionally NOT added as an initiative member

    response = await client.post(
        admin.g(f"/initiatives/{initiative.id}/advanced-tool/handoff"),
        headers=admin.headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "initiative"
    assert body["initiative_id"] == initiative.id


@pytest.mark.integration
async def test_advanced_tool_handoff_requires_authentication(
    client: AsyncClient, monkeypatch
):
    """Anonymous callers should never see the endpoint — the auth
    requirement comes before any other gate."""
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "ADVANCED_TOOL_URL", "https://embed.example.com")

    response = await client.post("/api/v1/g/1/initiatives/1/advanced-tool/handoff")

    assert response.status_code in (401, 403)
