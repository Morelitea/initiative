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

from app.models.guild import GuildRole
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_initiative_member,
    create_user,
    get_auth_headers,
    get_guild_headers,
)


@pytest.mark.integration
async def test_list_initiatives_requires_guild_context(
    client: AsyncClient, session: AsyncSession
):
    """A user with no guild memberships should be 403 when listing initiatives."""
    user = await create_user(session, email="test@example.com")

    headers = get_auth_headers(user)
    response = await client.get("/api/v1/initiatives/", headers=headers)

    assert response.status_code == 403


@pytest.mark.integration
async def test_list_initiatives_as_admin_shows_all(
    client: AsyncClient, session: AsyncSession
):
    """Test that guild admin can see all initiatives."""
    from app.testing.factories import create_initiative

    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)

    # Create multiple initiatives (factory creates builtin roles + PM membership)
    await create_initiative(session, guild, admin, name="Initiative 1")
    await create_initiative(session, guild, admin, name="Initiative 2")

    headers = get_guild_headers(guild, admin)
    response = await client.get("/api/v1/initiatives/", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 2
    initiative_names = {init["name"] for init in data}
    assert "Initiative 1" in initiative_names
    assert "Initiative 2" in initiative_names


@pytest.mark.integration
async def test_list_initiatives_as_member_shows_only_membership(
    client: AsyncClient, session: AsyncSession
):
    """Test that regular members only see initiatives they're part of."""
    from app.testing.factories import create_initiative

    admin = await create_user(session, email="admin@example.com")
    member = await create_user(session, email="member@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(
        session, user=member, guild=guild, role=GuildRole.member
    )

    # Create two initiatives
    initiative1 = await create_initiative(
        session, guild, admin, name="Member's Initiative"
    )
    await create_initiative(
        session, guild, admin, name="Other Initiative"
    )

    # Add member to only initiative1
    await create_initiative_member(session, initiative1, member, role_name="member")

    headers = get_guild_headers(guild, member)
    response = await client.get("/api/v1/initiatives/", headers=headers)

    assert response.status_code == 200
    data = response.json()
    initiative_names = {init["name"] for init in data}
    assert "Member's Initiative" in initiative_names
    assert "Other Initiative" not in initiative_names


@pytest.mark.integration
async def test_create_initiative_as_admin(client: AsyncClient, session: AsyncSession):
    """Test that guild admin can create initiatives."""
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)

    headers = get_guild_headers(guild, admin)
    payload = {
        "name": "New Initiative",
        "description": "A test initiative",
        "color": "#FF0000",
    }

    response = await client.post("/api/v1/initiatives/", headers=headers, json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "New Initiative"
    assert data["description"] == "A test initiative"
    assert data["color"] == "#FF0000"


@pytest.mark.integration
async def test_create_initiative_as_member_forbidden(
    client: AsyncClient, session: AsyncSession
):
    """Test that regular members cannot create initiatives."""
    member = await create_user(session, email="member@example.com")
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=member, guild=guild, role=GuildRole.member
    )

    headers = get_guild_headers(guild, member)
    payload = {"name": "New Initiative"}

    response = await client.post("/api/v1/initiatives/", headers=headers, json=payload)

    assert response.status_code == 403


@pytest.mark.integration
async def test_create_initiative_duplicate_name_fails(
    client: AsyncClient, session: AsyncSession
):
    """Test that duplicate initiative names are rejected."""
    from app.testing.factories import create_initiative

    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)

    # Create first initiative
    await create_initiative(
        session, guild, admin, name="Existing Initiative"
    )

    headers = get_guild_headers(guild, admin)
    payload = {"name": "Existing Initiative"}

    response = await client.post("/api/v1/initiatives/", headers=headers, json=payload)

    assert response.status_code == 409
    assert response.json()["detail"] == "INITIATIVE_NAME_EXISTS"


@pytest.mark.integration
async def test_create_initiative_makes_creator_manager(
    client: AsyncClient, session: AsyncSession
):
    """Test that creating an initiative makes the creator a manager."""
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)

    headers = get_guild_headers(guild, admin)
    payload = {"name": "New Initiative"}

    response = await client.post("/api/v1/initiatives/", headers=headers, json=payload)

    assert response.status_code == 201
    data = response.json()
    assert len(data["members"]) == 1
    assert data["members"][0]["user"]["id"] == admin.id
    assert data["members"][0]["role"] == "project_manager"


@pytest.mark.integration
async def test_update_initiative_as_manager(
    client: AsyncClient, session: AsyncSession
):
    """Test that initiative manager can update initiative."""
    from app.testing.factories import create_initiative

    manager = await create_user(session, email="manager@example.com")
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=manager, guild=guild, role=GuildRole.member
    )

    initiative = await create_initiative(
        session, guild, manager, name="Test Initiative"
    )

    headers = get_guild_headers(guild, manager)
    payload = {"name": "Updated Initiative", "description": "Updated description"}

    response = await client.patch(
        f"/api/v1/initiatives/{initiative.id}", headers=headers, json=payload
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Initiative"
    assert data["description"] == "Updated description"


@pytest.mark.integration
async def test_update_initiative_as_admin(client: AsyncClient, session: AsyncSession):
    """Test that guild admin can update any initiative."""
    from app.testing.factories import create_initiative

    admin = await create_user(session, email="admin@example.com")
    manager = await create_user(session, email="manager@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(
        session, user=manager, guild=guild, role=GuildRole.member
    )

    initiative = await create_initiative(
        session, guild, manager, name="Manager's Initiative"
    )

    headers = get_guild_headers(guild, admin)
    payload = {"name": "Admin Updated"}

    response = await client.patch(
        f"/api/v1/initiatives/{initiative.id}", headers=headers, json=payload
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Admin Updated"


@pytest.mark.integration
async def test_update_initiative_as_regular_member_forbidden(
    client: AsyncClient, session: AsyncSession
):
    """Test that regular members cannot update initiatives."""
    from app.testing.factories import create_initiative

    admin = await create_user(session, email="admin@example.com")
    member = await create_user(session, email="member@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(
        session, user=member, guild=guild, role=GuildRole.member
    )

    initiative = await create_initiative(
        session, guild, admin, name="Test Initiative"
    )
    await create_initiative_member(session, initiative, member, role_name="member")

    headers = get_guild_headers(guild, member)
    payload = {"name": "Hacked Name"}

    response = await client.patch(
        f"/api/v1/initiatives/{initiative.id}", headers=headers, json=payload
    )

    assert response.status_code == 403


@pytest.mark.integration
async def test_update_initiative_duplicate_name_fails(
    client: AsyncClient, session: AsyncSession
):
    """Test that renaming to existing name fails."""
    from app.testing.factories import create_initiative

    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)

    initiative1 = await create_initiative(
        session, guild, admin, name="Initiative 1"
    )
    await create_initiative(
        session, guild, admin, name="Initiative 2"
    )

    headers = get_guild_headers(guild, admin)
    payload = {"name": "Initiative 2"}

    response = await client.patch(
        f"/api/v1/initiatives/{initiative1.id}", headers=headers, json=payload
    )

    assert response.status_code == 409


@pytest.mark.integration
async def test_delete_initiative_as_admin(client: AsyncClient, session: AsyncSession):
    """Test that guild admin can delete initiatives."""
    from app.testing.factories import create_initiative

    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)

    initiative = await create_initiative(
        session, guild, admin, name="To Delete"
    )

    headers = get_guild_headers(guild, admin)
    response = await client.delete(f"/api/v1/initiatives/{initiative.id}", headers=headers)

    assert response.status_code == 204


@pytest.mark.integration
async def test_delete_initiative_as_manager_forbidden(
    client: AsyncClient, session: AsyncSession
):
    """Test that initiative manager cannot delete initiatives."""
    from app.testing.factories import create_initiative

    manager = await create_user(session, email="manager@example.com")
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=manager, guild=guild, role=GuildRole.member
    )

    initiative = await create_initiative(
        session, guild, manager, name="Test Initiative"
    )

    headers = get_guild_headers(guild, manager)
    response = await client.delete(f"/api/v1/initiatives/{initiative.id}", headers=headers)

    assert response.status_code == 403


@pytest.mark.integration
async def test_delete_default_initiative_forbidden(
    client: AsyncClient, session: AsyncSession
):
    """Test that default initiative cannot be deleted."""
    from app.testing.factories import create_initiative

    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)

    # Create and mark as default
    initiative = await create_initiative(
        session, guild, admin, name="Default Initiative", is_default=True
    )

    headers = get_guild_headers(guild, admin)
    response = await client.delete(f"/api/v1/initiatives/{initiative.id}", headers=headers)

    assert response.status_code == 400
    assert response.json()["detail"] == "INITIATIVE_CANNOT_DELETE_DEFAULT"


@pytest.mark.integration
async def test_get_initiative_members(client: AsyncClient, session: AsyncSession):
    """Test getting all members of an initiative."""
    from app.testing.factories import create_initiative

    admin = await create_user(session, email="admin@example.com")
    member1 = await create_user(session, email="member1@example.com", full_name="Member One")
    member2 = await create_user(session, email="member2@example.com", full_name="Member Two")
    guild = await create_guild(session)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=member1, guild=guild)
    await create_guild_membership(session, user=member2, guild=guild)

    initiative = await create_initiative(
        session, guild, admin, name="Test Initiative"
    )
    await create_initiative_member(session, initiative, member1, role_name="member")
    await create_initiative_member(session, initiative, member2, role_name="member")

    headers = get_guild_headers(guild, admin)
    response = await client.get(
        f"/api/v1/initiatives/{initiative.id}/members", headers=headers
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 3
    emails = {user["email"] for user in data}
    assert "admin@example.com" in emails
    assert "member1@example.com" in emails
    assert "member2@example.com" in emails


@pytest.mark.integration
async def test_add_initiative_member_as_manager(
    client: AsyncClient, session: AsyncSession
):
    """Test that manager can add members to initiative."""
    from app.testing.factories import create_initiative

    manager = await create_user(session, email="manager@example.com")
    new_member = await create_user(session, email="newmember@example.com")
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=manager, guild=guild, role=GuildRole.member
    )
    await create_guild_membership(session, user=new_member, guild=guild)

    initiative = await create_initiative(
        session, guild, manager, name="Test Initiative"
    )

    headers = get_guild_headers(guild, manager)
    payload = {"user_id": new_member.id, "role": "member"}

    response = await client.post(
        f"/api/v1/initiatives/{initiative.id}/members", headers=headers, json=payload
    )

    assert response.status_code == 200
    data = response.json()
    member_ids = {m["user"]["id"] for m in data["members"]}
    assert new_member.id in member_ids


@pytest.mark.integration
async def test_add_initiative_member_as_regular_member_forbidden(
    client: AsyncClient, session: AsyncSession
):
    """Test that regular members cannot add members."""
    from app.testing.factories import create_initiative

    admin = await create_user(session, email="admin@example.com")
    member = await create_user(session, email="member@example.com")
    new_member = await create_user(session, email="newmember@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=member, guild=guild)
    await create_guild_membership(session, user=new_member, guild=guild)

    initiative = await create_initiative(
        session, guild, admin, name="Test Initiative"
    )
    await create_initiative_member(session, initiative, member, role_name="member")

    headers = get_guild_headers(guild, member)
    payload = {"user_id": new_member.id, "role": "member"}

    response = await client.post(
        f"/api/v1/initiatives/{initiative.id}/members", headers=headers, json=payload
    )

    assert response.status_code == 403


@pytest.mark.integration
async def test_add_user_not_in_guild_fails(client: AsyncClient, session: AsyncSession):
    """Test that adding a user not in the guild fails."""
    from app.testing.factories import create_initiative

    admin = await create_user(session, email="admin@example.com")
    outsider = await create_user(session, email="outsider@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)

    initiative = await create_initiative(
        session, guild, admin, name="Test Initiative"
    )

    headers = get_guild_headers(guild, admin)
    payload = {"user_id": outsider.id, "role": "member"}

    response = await client.post(
        f"/api/v1/initiatives/{initiative.id}/members", headers=headers, json=payload
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "INITIATIVE_USER_NOT_IN_GUILD"


@pytest.mark.integration
async def test_update_initiative_member_role(
    client: AsyncClient, session: AsyncSession
):
    """Test updating an initiative member's role."""
    from app.testing.factories import create_initiative

    admin = await create_user(session, email="admin@example.com")
    member = await create_user(session, email="member@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=member, guild=guild)

    initiative = await create_initiative(
        session, guild, admin, name="Test Initiative"
    )
    await create_initiative_member(session, initiative, member, role_name="member")

    # Look up the PM role ID for this initiative
    from app.models.initiative import InitiativeRoleModel
    from sqlmodel import select

    pm_role_stmt = select(InitiativeRoleModel).where(
        InitiativeRoleModel.initiative_id == initiative.id,
        InitiativeRoleModel.name == "project_manager",
    )
    pm_role = (await session.exec(pm_role_stmt)).one()

    headers = get_guild_headers(guild, admin)
    payload = {"role_id": pm_role.id}

    response = await client.patch(
        f"/api/v1/initiatives/{initiative.id}/members/{member.id}",
        headers=headers,
        json=payload,
    )

    assert response.status_code == 200
    data = response.json()
    member_roles = {m["user"]["id"]: m["role"] for m in data["members"]}
    assert member_roles[member.id] == "project_manager"


@pytest.mark.integration
async def test_remove_initiative_member(client: AsyncClient, session: AsyncSession):
    """Test removing an initiative member."""
    from app.testing.factories import create_initiative

    admin = await create_user(session, email="admin@example.com")
    member = await create_user(session, email="member@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=member, guild=guild)

    initiative = await create_initiative(
        session, guild, admin, name="Test Initiative"
    )
    await create_initiative_member(session, initiative, member, role_name="member")

    headers = get_guild_headers(guild, admin)
    response = await client.delete(
        f"/api/v1/initiatives/{initiative.id}/members/{member.id}", headers=headers
    )

    assert response.status_code == 200
    data = response.json()
    member_ids = {m["user"]["id"] for m in data["members"]}
    assert member.id not in member_ids


@pytest.mark.integration
async def test_cannot_remove_last_manager(client: AsyncClient, session: AsyncSession):
    """Test that removing the last manager fails."""
    from app.testing.factories import create_initiative

    manager = await create_user(session, email="manager@example.com")
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=manager, guild=guild, role=GuildRole.member
    )

    initiative = await create_initiative(
        session, guild, manager, name="Test Initiative"
    )

    headers = get_guild_headers(guild, manager)
    response = await client.delete(
        f"/api/v1/initiatives/{initiative.id}/members/{manager.id}", headers=headers
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "INITIATIVE_MUST_HAVE_PM"


@pytest.mark.integration
async def test_cannot_demote_last_manager(client: AsyncClient, session: AsyncSession):
    """Test that demoting the last manager fails."""
    from app.testing.factories import create_initiative

    manager = await create_user(session, email="manager@example.com")
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=manager, guild=guild, role=GuildRole.member
    )

    initiative = await create_initiative(
        session, guild, manager, name="Test Initiative"
    )

    # Look up the member role ID for this initiative
    from app.models.initiative import InitiativeRoleModel
    from sqlmodel import select

    member_role_stmt = select(InitiativeRoleModel).where(
        InitiativeRoleModel.initiative_id == initiative.id,
        InitiativeRoleModel.name == "member",
    )
    member_role = (await session.exec(member_role_stmt)).one()

    headers = get_guild_headers(guild, manager)
    payload = {"role_id": member_role.id}

    response = await client.patch(
        f"/api/v1/initiatives/{initiative.id}/members/{manager.id}",
        headers=headers,
        json=payload,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "INITIATIVE_MUST_HAVE_PM"


@pytest.mark.integration
async def test_initiative_guild_isolation(client: AsyncClient, session: AsyncSession):
    """Test that initiatives are isolated by guild."""
    from app.testing.factories import create_initiative

    user = await create_user(session, email="user@example.com")
    guild1 = await create_guild(session, name="Guild 1")
    guild2 = await create_guild(session, name="Guild 2")
    await create_guild_membership(session, user=user, guild=guild1, role=GuildRole.admin)
    await create_guild_membership(session, user=user, guild=guild2, role=GuildRole.admin)

    initiative1 = await create_initiative(
        session, guild1, user, name="Guild 1 Initiative"
    )
    await create_initiative(
        session, guild2, user, name="Guild 2 Initiative"
    )

    # Request with guild1 context
    headers1 = get_guild_headers(guild1, user)
    response1 = await client.get("/api/v1/initiatives/", headers=headers1)

    assert response1.status_code == 200
    data1 = response1.json()
    initiative_names1 = {init["name"] for init in data1}
    assert "Guild 1 Initiative" in initiative_names1
    assert "Guild 2 Initiative" not in initiative_names1

    # Cannot access guild1 initiative with guild2 context
    headers2 = get_guild_headers(guild2, user)
    response2 = await client.get(f"/api/v1/initiatives/{initiative1.id}", headers=headers2)

    assert response2.status_code == 404


# ---------------------------------------------------------------------------
# Advanced-tool handoff endpoint
#
# All five gates must hold before a token is minted:
#   1. ADVANCED_TOOL_URL configured
#   2. Initiative exists in the active guild
#   3. User is guild admin OR initiative member
#   4. initiative.advanced_tool_enabled = true
#   5. User's role grants advanced_tool_enabled (managers bypass)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_advanced_tool_handoff_returns_404_when_url_unset(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """Without ADVANCED_TOOL_URL the embed isn't deployed, so the
    endpoint must look like it doesn't exist — not even an authorized
    user should be able to mint a token that has nowhere to go."""
    from app.core.config import settings as app_settings
    from app.testing.factories import create_initiative

    monkeypatch.setattr(app_settings, "ADVANCED_TOOL_URL", None)

    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(
        session, guild, admin, name="Init", advanced_tool_enabled=True
    )

    headers = get_guild_headers(guild, admin)
    response = await client.post(
        f"/api/v1/initiatives/{initiative.id}/advanced-tool/handoff", headers=headers
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "ADVANCED_TOOL_NOT_CONFIGURED"


@pytest.mark.integration
async def test_advanced_tool_handoff_returns_403_when_master_switch_off(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """The per-initiative master switch is the manager's opt-in. Even a
    guild admin can't bypass it — the embed's data plane likely doesn't
    have the initiative provisioned yet."""
    from app.core.config import settings as app_settings
    from app.testing.factories import create_initiative

    monkeypatch.setattr(app_settings, "ADVANCED_TOOL_URL", "https://embed.example.com")

    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(
        session, guild, admin, name="Init", advanced_tool_enabled=False
    )

    headers = get_guild_headers(guild, admin)
    response = await client.post(
        f"/api/v1/initiatives/{initiative.id}/advanced-tool/handoff", headers=headers
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "ADVANCED_TOOL_NOT_ENABLED"


@pytest.mark.integration
async def test_advanced_tool_handoff_returns_403_for_non_member(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """Members of the guild who aren't members of the initiative get
    rejected — view access is initiative-scoped, not guild-scoped (for
    non-admins)."""
    from app.core.config import settings as app_settings
    from app.testing.factories import create_initiative

    monkeypatch.setattr(app_settings, "ADVANCED_TOOL_URL", "https://embed.example.com")

    admin = await create_user(session, email="admin@example.com")
    outsider = await create_user(session, email="outsider@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(
        session, user=outsider, guild=guild, role=GuildRole.member
    )
    initiative = await create_initiative(
        session, guild, admin, name="Init", advanced_tool_enabled=True
    )

    headers = get_guild_headers(guild, outsider)
    response = await client.post(
        f"/api/v1/initiatives/{initiative.id}/advanced-tool/handoff", headers=headers
    )

    assert response.status_code == 403


@pytest.mark.integration
async def test_advanced_tool_handoff_returns_403_when_role_lacks_view_permission(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """An initiative member whose role does NOT grant
    ``advanced_tool_enabled`` must be refused. The default ``member``
    role is exactly this case — view permission is opt-in per role.
    Without this gate, role-level access control would be a no-op."""
    from app.core.config import settings as app_settings
    from app.testing.factories import create_initiative, create_initiative_member

    monkeypatch.setattr(app_settings, "ADVANCED_TOOL_URL", "https://embed.example.com")

    pm = await create_user(session, email="pm@example.com")
    member = await create_user(session, email="member@example.com")
    guild = await create_guild(session)
    # Both users are guild members (not admins) so guild-admin bypass doesn't apply
    await create_guild_membership(
        session, user=pm, guild=guild, role=GuildRole.member
    )
    await create_guild_membership(
        session, user=member, guild=guild, role=GuildRole.member
    )
    initiative = await create_initiative(
        session, guild, pm, name="Init", advanced_tool_enabled=True
    )
    # pm is auto-added as project_manager by the factory; add member with the
    # default member role (which has advanced_tool_enabled=False)
    await create_initiative_member(session, initiative, member, role_name="member")

    headers = get_guild_headers(guild, member)
    response = await client.post(
        f"/api/v1/initiatives/{initiative.id}/advanced-tool/handoff", headers=headers
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "ADVANCED_TOOL_NOT_ENABLED"


@pytest.mark.integration
async def test_advanced_tool_handoff_succeeds_for_initiative_manager(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """The happy path: manager opens the panel, gets a token with
    ``scope=initiative``, the right initiative_id, and ``can_create``
    set so the embed can show edit affordances."""
    from app.core.config import settings as app_settings
    from app.core.security import ADVANCED_TOOL_AUDIENCE
    from app.testing.factories import create_initiative
    import jwt

    monkeypatch.setattr(app_settings, "ADVANCED_TOOL_URL", "https://embed.example.com")

    pm = await create_user(session, email="pm@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=pm, guild=guild, role=GuildRole.member)
    initiative = await create_initiative(
        session, guild, pm, name="Init", advanced_tool_enabled=True
    )

    headers = get_guild_headers(guild, pm)
    response = await client.post(
        f"/api/v1/initiatives/{initiative.id}/advanced-tool/handoff", headers=headers
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
        algorithms=[app_settings.ALGORITHM],
        audience=ADVANCED_TOOL_AUDIENCE,
    )
    assert payload["sub"] == str(pm.id)
    assert payload["scope"] == "initiative"
    assert payload["initiative_id"] == initiative.id
    assert payload["is_manager"] is True
    assert payload["can_create"] is True


@pytest.mark.integration
async def test_advanced_tool_handoff_can_create_false_for_view_only_role(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """A custom role that grants view but not create gets a token with
    ``can_create=false`` so the embed hides creation UI. The token is
    still issued — view access is enough to load the panel."""
    from app.core.config import settings as app_settings
    from app.core.security import ADVANCED_TOOL_AUDIENCE
    from app.models.initiative import (
        InitiativeRoleModel,
        InitiativeRolePermission,
        PermissionKey,
    )
    from app.testing.factories import (
        create_initiative,
        create_initiative_member,
    )
    import jwt
    from sqlmodel import select

    monkeypatch.setattr(app_settings, "ADVANCED_TOOL_URL", "https://embed.example.com")

    pm = await create_user(session, email="pm@example.com")
    viewer = await create_user(session, email="viewer@example.com")
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=pm, guild=guild, role=GuildRole.member
    )
    await create_guild_membership(
        session, user=viewer, guild=guild, role=GuildRole.member
    )
    initiative = await create_initiative(
        session, guild, pm, name="Init", advanced_tool_enabled=True
    )

    # Flip the default member role to grant view but not create
    member_role = (
        await session.exec(
            select(InitiativeRoleModel).where(
                InitiativeRoleModel.initiative_id == initiative.id,
                InitiativeRoleModel.name == "member",
            )
        )
    ).one()
    view_perm = (
        await session.exec(
            select(InitiativeRolePermission).where(
                InitiativeRolePermission.initiative_role_id == member_role.id,
                InitiativeRolePermission.permission_key
                == PermissionKey.advanced_tool_enabled,
            )
        )
    ).one()
    view_perm.enabled = True
    session.add(view_perm)
    await session.commit()

    await create_initiative_member(session, initiative, viewer, role_name="member")

    headers = get_guild_headers(guild, viewer)
    response = await client.post(
        f"/api/v1/initiatives/{initiative.id}/advanced-tool/handoff", headers=headers
    )

    assert response.status_code == 200
    payload = jwt.decode(
        response.json()["handoff_token"],
        app_settings.SECRET_KEY,
        algorithms=[app_settings.ALGORITHM],
        audience=ADVANCED_TOOL_AUDIENCE,
    )
    assert payload["is_manager"] is False
    assert payload["can_create"] is False


@pytest.mark.integration
async def test_advanced_tool_handoff_succeeds_for_guild_admin_non_member(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """Guild admins can mint a token even if they aren't an initiative
    member — admin override is the existing pattern for guild-wide
    operational access."""
    from app.core.config import settings as app_settings
    from app.testing.factories import create_initiative

    monkeypatch.setattr(app_settings, "ADVANCED_TOOL_URL", "https://embed.example.com")

    admin = await create_user(session, email="admin@example.com")
    pm = await create_user(session, email="pm@example.com")
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    await create_guild_membership(session, user=pm, guild=guild, role=GuildRole.member)
    initiative = await create_initiative(
        session, guild, pm, name="Init", advanced_tool_enabled=True
    )
    # Admin is intentionally NOT added as an initiative member

    headers = get_guild_headers(guild, admin)
    response = await client.post(
        f"/api/v1/initiatives/{initiative.id}/advanced-tool/handoff", headers=headers
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

    response = await client.post("/api/v1/initiatives/1/advanced-tool/handoff")

    assert response.status_code in (401, 403)
