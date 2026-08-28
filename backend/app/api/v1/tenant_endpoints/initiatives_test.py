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
    assert data["join_policy"] == "private"


@pytest.mark.integration
async def test_create_initiative_with_join_policy(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The creation payload may set the join policy directly."""
    admin = await acting_user(guild_role=GuildRole.admin)

    response = await client.post(
        admin.g("/initiatives/"),
        headers=admin.headers,
        json={"name": "Open Initiative", "join_policy": "open"},
    )

    assert response.status_code == 201
    assert response.json()["join_policy"] == "open"


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
    assert data["members"][0]["role_name"] == "project_manager"


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
async def test_search_initiative_members_slim_and_filtered(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The slim members search returns a UserSummary envelope and filters by
    name, with the same membership gate as the full roster."""
    admin = await acting_user(guild_role=GuildRole.admin, full_name="Zed Admin")
    initiative = await create_initiative(
        session, admin.guild, admin.user, name="Search Initiative"
    )
    await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=initiative,
        initiative_role="member",
        email="alice@example.com",
        full_name="Alice Wonderland",
    )
    await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=initiative,
        initiative_role="member",
        email="bob@example.com",
        full_name="Bob Builder",
    )

    # Unfiltered: slim envelope over every member (creator + 2).
    response = await client.get(
        admin.g(f"/initiatives/{initiative.id}/members/search"),
        headers=admin.headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 3
    assert set(body["items"][0].keys()) == {
        "id",
        "full_name",
        "avatar_base64",
        "avatar_url",
        "status",
    }

    # Filtered by name.
    response = await client.get(
        admin.g(f"/initiatives/{initiative.id}/members/search"),
        headers=admin.headers,
        params={"search": "wonder"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 1
    assert body["items"][0]["full_name"] == "Alice Wonderland"


@pytest.mark.integration
async def test_search_initiative_members_filters_by_user_id(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """`user_id` resolves a known selection, narrowing the same member set —
    a guild member outside the initiative is never resolved through it."""
    admin = await acting_user(guild_role=GuildRole.admin, full_name="Zed Admin")
    initiative = await create_initiative(
        session, admin.guild, admin.user, name="Id Filter Initiative"
    )
    alice = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=initiative,
        initiative_role="member",
        email="alice-ids@example.com",
        full_name="Alice Wonderland",
    )
    outsider = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        email="outsider-ids@example.com",
        full_name="Olive Outsider",
    )

    response = await client.get(
        admin.g(f"/initiatives/{initiative.id}/members/search"),
        headers=admin.headers,
        params={"user_id": [alice.user.id, outsider.user.id]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 1
    assert [item["full_name"] for item in body["items"]] == ["Alice Wonderland"]


@pytest.mark.integration
async def test_search_initiative_members_as_nonmember_forbidden(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A plain guild member outside the initiative is locked out of the slim
    roster, mirroring the full members endpoint."""
    creator = await acting_user(guild_role=GuildRole.member, initiative=True)
    outsider = await acting_user(guild_role=GuildRole.member, guild=creator.guild)

    response = await client.get(
        outsider.g(f"/initiatives/{creator.initiative.id}/members/search"),
        headers=outsider.headers,
    )
    assert response.status_code == 403


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
    member_roles = {m["user"]["id"]: m["role_name"] for m in data["members"]}
    assert member_roles[member.user.id] == "project_manager"


@pytest.mark.integration
async def test_member_roster_reports_a_custom_role_as_itself(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A member's row carries the role they actually hold — its own name,
    display name, and manager standing — for custom roles too."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )

    role_response = await client.post(
        admin.g(f"/initiatives/{admin.initiative.id}/roles"),
        headers=admin.headers,
        json={"name": "leads", "display_name": "Leads", "is_manager": True},
    )
    assert role_response.status_code == 201, role_response.text

    response = await client.patch(
        admin.g(f"/initiatives/{admin.initiative.id}/members/{member.user.id}"),
        headers=admin.headers,
        json={"role_id": role_response.json()["id"]},
    )

    assert response.status_code == 200
    row = next(
        m for m in response.json()["members"] if m["user"]["id"] == member.user.id
    )
    assert row["role_name"] == "leads"
    assert row["role_display_name"] == "Leads"
    assert row["is_manager"] is True


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
    member_roles = {m["user"]["id"]: m["role_name"] for m in data["members"]}
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
async def test_removing_the_last_manager_is_allowed(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """An initiative may be left with no manager until an admin appoints one.

    Ending a membership is not blocked by it being the last manager's;
    ``test_cannot_demote_last_manager`` covers the case that still is, which
    edits a live membership rather than ending it.
    """
    manager = await acting_user(guild_role=GuildRole.member, initiative=True)

    response = await client.delete(
        manager.g(f"/initiatives/{manager.initiative.id}/members/{manager.user.id}"),
        headers=manager.headers,
    )

    assert response.status_code == 200
    assert response.json()["members"] == []


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


# ============================================================================
# Discovery: directory, self-join, join settings
# ============================================================================


@pytest.mark.integration
async def test_directory_lists_only_joinable_initiatives(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Listing is opt-in: `private` appears only to its own members, archived
    never appears.

    RLS *would* permit listing a private initiative to any guild member (the
    `initiatives` table is structural), so this exclusion is an app-layer
    promise — pinned here rather than assumed.
    """
    admin = await acting_user(guild_role=GuildRole.admin)

    await create_initiative(
        session, admin.guild, admin.user, name="Secret", join_policy="private"
    )
    await create_initiative(
        session, admin.guild, admin.user, name="Knockable", join_policy="request"
    )
    await create_initiative(
        session, admin.guild, admin.user, name="Anyone", join_policy="open"
    )
    await create_initiative(
        session,
        admin.guild,
        admin.user,
        name="Retired",
        join_policy="open",
        is_archived=True,
    )

    member = await acting_user(guild_role=GuildRole.member, guild=admin.guild)
    response = await client.get(
        member.g("/initiatives/directory"), headers=member.headers
    )

    assert response.status_code == 200
    listed = {entry["name"]: entry for entry in response.json()}
    assert set(listed) == {"Knockable", "Anyone"}
    assert listed["Knockable"]["join_policy"] == "request"
    assert listed["Anyone"]["join_policy"] == "open"


@pytest.mark.integration
async def test_directory_lists_private_initiatives_to_their_members(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The directory doubles as the caller's own initiative list.

    A private initiative appears to its own members (their sidebar already
    shows it), listed ahead of the joinable ones — and stays invisible to
    everyone else.
    """
    admin = await acting_user(guild_role=GuildRole.admin)
    mine = await create_initiative(
        session, admin.guild, admin.user, name="Zebra Ours", join_policy="private"
    )
    await create_initiative(
        session, admin.guild, admin.user, name="Askable", join_policy="open"
    )

    member = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=mine,
        initiative_role="member",
    )

    response = await client.get(
        member.g("/initiatives/directory"), headers=member.headers
    )

    assert response.status_code == 200
    entries = response.json()
    # Membership outranks the alphabet: "Zebra Ours" leads despite sorting last.
    assert [entry["name"] for entry in entries] == ["Zebra Ours", "Askable"]
    assert entries[0]["join_policy"] == "private"
    assert entries[0]["is_member"] is True


@pytest.mark.integration
async def test_directory_lists_everything_to_a_guild_admin(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A guild admin's directory is the whole guild.

    Their standing already reaches every initiative (the `current_guild_role=
    'admin'` RLS leg), and the deprecated initiatives page showed them all —
    so the directory does too, membership still ordered first.
    """
    owner = await acting_user(guild_role=GuildRole.admin)
    await create_initiative(
        session, owner.guild, owner.user, name="Hidden", join_policy="private"
    )

    other_admin = await acting_user(guild_role=GuildRole.admin, guild=owner.guild)
    response = await client.get(
        other_admin.g("/initiatives/directory"), headers=other_admin.headers
    )

    assert response.status_code == 200
    listed = {entry["name"]: entry for entry in response.json()}
    assert "Hidden" in listed
    assert listed["Hidden"]["is_member"] is False


@pytest.mark.integration
async def test_directory_reports_caller_state(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Each card carries the roster size and the caller's own state."""
    admin = await acting_user(guild_role=GuildRole.admin)
    joined = await create_initiative(
        session, admin.guild, admin.user, name="Joined", join_policy="open"
    )
    await create_initiative(
        session, admin.guild, admin.user, name="Unjoined", join_policy="open"
    )

    member = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=joined,
        initiative_role="member",
    )

    response = await client.get(
        member.g("/initiatives/directory"), headers=member.headers
    )

    assert response.status_code == 200
    listed = {entry["name"]: entry for entry in response.json()}
    # The creator (PM) plus the member who joined.
    assert listed["Joined"]["member_count"] == 2
    assert listed["Joined"]["is_member"] is True
    assert listed["Joined"]["has_pending_request"] is False
    assert listed["Unjoined"]["member_count"] == 1
    assert listed["Unjoined"]["is_member"] is False
    assert listed["Unjoined"]["has_pending_request"] is False


@pytest.mark.integration
async def test_directory_rejects_non_guild_member(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The directory is guild-scoped: an outsider never reaches it."""
    admin = await acting_user(guild_role=GuildRole.admin)
    await create_initiative(
        session, admin.guild, admin.user, name="Anyone", join_policy="open"
    )
    outsider = await acting_user(guild_role=GuildRole.member)

    response = await client.get(
        f"/api/v1/g/{admin.guild.id}/initiatives/directory", headers=outsider.headers
    )

    assert response.status_code == 403


@pytest.mark.integration
async def test_self_join_open_initiative_grants_member_role(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Self-join hands out the floor: the built-in member role, not managed by OIDC."""
    admin = await acting_user(guild_role=GuildRole.admin)
    initiative = await create_initiative(
        session, admin.guild, admin.user, name="Anyone", join_policy="open"
    )
    member = await acting_user(guild_role=GuildRole.member, guild=admin.guild)

    response = await client.post(
        member.g(f"/initiatives/{initiative.id}/join"), headers=member.headers
    )

    assert response.status_code == 200
    entry = next(
        m for m in response.json()["members"] if m["user"]["id"] == member.user.id
    )
    assert entry["role_name"] == "member"
    assert entry["is_manager"] is False
    assert entry["oidc_managed"] is False


@pytest.mark.integration
@pytest.mark.parametrize("policy", ["private", "request"])
async def test_self_join_rejected_for_non_open_policy(
    client: AsyncClient, session: AsyncSession, acting_user, policy: str
):
    """Private and request answer identically — "not by this route"."""
    admin = await acting_user(guild_role=GuildRole.admin)
    initiative = await create_initiative(
        session, admin.guild, admin.user, name=f"Closed {policy}", join_policy=policy
    )
    member = await acting_user(guild_role=GuildRole.member, guild=admin.guild)

    response = await client.post(
        member.g(f"/initiatives/{initiative.id}/join"), headers=member.headers
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "INITIATIVE_NOT_JOINABLE"


@pytest.mark.integration
async def test_self_join_is_idempotent(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Joining twice is a success, not a conflict, and adds no second row."""
    admin = await acting_user(guild_role=GuildRole.admin)
    initiative = await create_initiative(
        session, admin.guild, admin.user, name="Anyone", join_policy="open"
    )
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=initiative,
        initiative_role="member",
    )

    response = await client.post(
        member.g(f"/initiatives/{initiative.id}/join"), headers=member.headers
    )

    assert response.status_code == 200
    rows = [m for m in response.json()["members"] if m["user"]["id"] == member.user.id]
    assert len(rows) == 1
    assert rows[0]["role_name"] == "member"


@pytest.mark.integration
async def test_self_join_flips_content_visibility(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The point of the feature: content is hidden by RLS before the membership
    row exists and reachable the moment it does — with no RLS change at all."""
    from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
    from app.testing.factories import create_project
    from app.testing.schema_harness import route_session_to_guild

    admin = await acting_user(guild_role=GuildRole.admin)
    initiative = await create_initiative(
        session, admin.guild, admin.user, name="Anyone", join_policy="open"
    )
    project = await create_project(session, initiative, admin.user, name="Shared work")
    # Shared with the whole initiative, so gate 4 is satisfied for any member and
    # initiative membership is the only thing that changes across the join.
    await route_session_to_guild(session, admin.guild.id)
    session.add(
        ResourceGrant(
            resource_type="project",
            resource_id=project.id,
            all_initiative_members=True,
            level=ResourceAccessLevel.read,
            guild_id=initiative.guild_id,
            initiative_id=initiative.id,
        )
    )
    await session.commit()

    member = await acting_user(guild_role=GuildRole.member, guild=admin.guild)

    before = await client.get(
        member.g(f"/projects/{project.id}"), headers=member.headers
    )
    assert before.status_code == 404

    joined = await client.post(
        member.g(f"/initiatives/{initiative.id}/join"), headers=member.headers
    )
    assert joined.status_code == 200

    after = await client.get(
        member.g(f"/projects/{project.id}"), headers=member.headers
    )
    assert after.status_code == 200
    assert after.json()["name"] == "Shared work"


@pytest.mark.integration
async def test_manager_can_set_join_policy(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """join_policy travels with the existing update permission."""
    manager = await acting_user(guild_role=GuildRole.member, initiative=True)

    response = await client.patch(
        manager.g(f"/initiatives/{manager.initiative.id}"),
        headers=manager.headers,
        json={"join_policy": "open"},
    )

    assert response.status_code == 200
    assert response.json()["join_policy"] == "open"
    assert response.json()["auto_join"] is False


@pytest.mark.integration
async def test_plain_member_cannot_set_join_policy(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A non-manager member of the initiative may not open it."""
    manager = await acting_user(guild_role=GuildRole.member, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=manager.guild,
        initiative=manager.initiative,
        initiative_role="member",
    )

    response = await client.patch(
        member.g(f"/initiatives/{manager.initiative.id}"),
        headers=member.headers,
        json={"join_policy": "open"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "INITIATIVE_MANAGER_REQUIRED"


@pytest.mark.integration
async def test_guild_admin_can_set_auto_join_on_open_initiative(
    client: AsyncClient, session: AsyncSession, acting_user
):
    admin = await acting_user(guild_role=GuildRole.admin)
    initiative = await create_initiative(
        session, admin.guild, admin.user, name="Welcome", join_policy="open"
    )

    response = await client.patch(
        admin.g(f"/initiatives/{initiative.id}"),
        headers=admin.headers,
        json={"auto_join": True},
    )

    assert response.status_code == 200
    assert response.json()["auto_join"] is True
    assert response.json()["join_policy"] == "open"


@pytest.mark.integration
async def test_non_admin_manager_cannot_set_auto_join(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Auto-join shapes onboarding for the whole guild — guild admins only."""
    admin = await acting_user(guild_role=GuildRole.admin)
    initiative = await create_initiative(
        session, admin.guild, admin.user, name="Welcome", join_policy="open"
    )
    manager = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=initiative,
        initiative_role="project_manager",
    )

    response = await client.patch(
        manager.g(f"/initiatives/{initiative.id}"),
        headers=manager.headers,
        json={"auto_join": True},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "INITIATIVE_AUTO_JOIN_ADMIN_ONLY"


@pytest.mark.integration
async def test_auto_join_requires_open_policy(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """An auto-enrolled-but-private initiative would be incoherent: leavers
    could never rejoin it."""
    admin = await acting_user(guild_role=GuildRole.admin)
    initiative = await create_initiative(
        session, admin.guild, admin.user, name="Secret", join_policy="private"
    )

    response = await client.patch(
        admin.g(f"/initiatives/{initiative.id}"),
        headers=admin.headers,
        json={"auto_join": True},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "INITIATIVE_AUTO_JOIN_REQUIRES_OPEN"


@pytest.mark.integration
async def test_closing_policy_while_auto_join_on_is_rejected(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Explicit beats silent: the pair is refused rather than auto-join being
    dropped as a side effect of an unrelated edit."""
    admin = await acting_user(guild_role=GuildRole.admin)
    initiative = await create_initiative(
        session,
        admin.guild,
        admin.user,
        name="Welcome",
        join_policy="open",
        auto_join=True,
    )

    response = await client.patch(
        admin.g(f"/initiatives/{initiative.id}"),
        headers=admin.headers,
        json={"join_policy": "request"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "INITIATIVE_AUTO_JOIN_REQUIRES_OPEN"

    # Both fields moved together is fine.
    ok = await client.patch(
        admin.g(f"/initiatives/{initiative.id}"),
        headers=admin.headers,
        json={"join_policy": "request", "auto_join": False},
    )
    assert ok.status_code == 200
    assert ok.json()["join_policy"] == "request"
    assert ok.json()["auto_join"] is False


@pytest.mark.integration
async def test_self_join_refused_to_scoped_grantee(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A time-bound grant reaches the guild for a window; the membership row a
    join creates has no end date, so the two must not be traded for each other."""
    from datetime import datetime, timedelta, timezone

    from app.models.platform.access_grant import AccessGrant

    admin = await acting_user(guild_role=GuildRole.admin)
    initiative = await create_initiative(
        session, admin.guild, admin.user, name="Anyone", join_policy="open"
    )

    grantee = await acting_user("support")
    now = datetime.now(timezone.utc)
    session.add(
        AccessGrant(
            user_id=grantee.user.id,
            guild_id=admin.guild.id,
            access_level="read_write",
            status="approved",
            reason="ticket",
            requested_duration_minutes=60,
            requested_by_id=grantee.user.id,
            approved_by_id=admin.user.id,
            decided_at=now,
            expires_at=now + timedelta(hours=1),
        )
    )
    await session.commit()

    response = await client.post(
        f"/api/v1/g/{admin.guild.id}/initiatives/{initiative.id}/join",
        headers=grantee.headers,
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "INITIATIVE_GRANT_CANNOT_MANAGE_MEMBERS"
