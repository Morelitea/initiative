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
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.models.platform.notification import Notification, NotificationType
from app.models.platform.user import UserRole
from app.models.tenant.initiative import InitiativeJoinRequest, InitiativeMember
from app.services import email as email_service
from app.services.tenant import initiatives as initiatives_service
from app.testing import create_user, get_auth_headers
from app.testing.factories import create_guild_membership, create_initiative_member
from app.testing.factories import create_initiative


async def _live_grant(session: AsyncSession, *, user, guild, approver, level: str):
    """An approved, currently-live access grant — the PAM branch of GuildContext."""
    from datetime import datetime, timedelta, timezone

    from app.models.platform.access_grant import AccessGrant

    now = datetime.now(timezone.utc)
    session.add(
        AccessGrant(
            user_id=user.id,
            guild_id=guild.id,
            access_level=level,
            status="approved",
            reason="ticket",
            requested_duration_minutes=60,
            requested_by_id=user.id,
            approved_by_id=approver.id,
            decided_at=now,
            expires_at=now + timedelta(hours=1),
        )
    )
    await session.commit()


@pytest.mark.integration
async def test_list_initiatives_returns_own_memberships(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The default listing is the caller's own workspace."""
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
async def test_list_initiatives_omits_ones_admin_has_not_joined(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A guild admin's navigation is their memberships, not the whole guild."""
    admin = await acting_user(guild_role=GuildRole.admin)
    other = await acting_user(guild_role=GuildRole.member, guild=admin.guild)
    await create_initiative(session, admin.guild, other.user, name="Not Admin's")

    response = await client.get(admin.g("/initiatives/"), headers=admin.headers)

    assert response.status_code == 200
    assert "Not Admin's" not in {init["name"] for init in response.json()}


@pytest.mark.integration
async def test_list_initiatives_guild_scope_shows_all_for_admin(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """``scope=guild`` is the guild-settings management listing."""
    admin = await acting_user(guild_role=GuildRole.admin)
    other = await acting_user(guild_role=GuildRole.member, guild=admin.guild)
    await create_initiative(session, admin.guild, other.user, name="Not Admin's")

    response = await client.get(
        admin.g("/initiatives/?scope=guild"), headers=admin.headers
    )

    assert response.status_code == 200
    assert "Not Admin's" in {init["name"] for init in response.json()}


@pytest.mark.integration
async def test_list_initiatives_shows_whole_guild_to_a_scoped_grantee(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A grantee holds no membership in the guild — the grant is what they
    navigate by, so the default listing stays the whole guild for its window."""
    owner = await acting_user(guild_role=GuildRole.admin)
    await create_initiative(session, owner.guild, owner.user, name="Apollo")

    support = await create_user(session, role=UserRole.support)
    await _live_grant(
        session, user=support, guild=owner.guild, approver=owner.user, level="read"
    )

    response = await client.get(
        f"/api/v1/g/{owner.guild.id}/initiatives/", headers=get_auth_headers(support)
    )

    assert response.status_code == 200, response.text
    assert "Apollo" in {init["name"] for init in response.json()}


@pytest.mark.integration
async def test_list_initiatives_shows_whole_guild_to_break_glass(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Break-glass acts as a full guild admin for its window, in a guild the
    holder is not a member of."""
    owner = await acting_user(guild_role=GuildRole.admin)
    await create_initiative(session, owner.guild, owner.user, name="Apollo")

    operator = await create_user(session, role=UserRole.operator)
    await _live_grant(
        session,
        user=operator,
        guild=owner.guild,
        approver=owner.user,
        level="read_write",
    )

    response = await client.get(
        f"/api/v1/g/{owner.guild.id}/initiatives/", headers=get_auth_headers(operator)
    )

    assert response.status_code == 200, response.text
    assert "Apollo" in {init["name"] for init in response.json()}


@pytest.mark.integration
async def test_scoped_grantee_reads_an_initiative_it_holds_no_membership_in(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The initiative and its roles are addressable by id for a grantee — the
    pages that open one resolve it that way rather than from a roster."""
    owner = await acting_user(guild_role=GuildRole.admin)
    initiative = await create_initiative(
        session, owner.guild, owner.user, name="Apollo"
    )

    support = await create_user(session, role=UserRole.support)
    await _live_grant(
        session, user=support, guild=owner.guild, approver=owner.user, level="read"
    )
    headers = get_auth_headers(support)
    base = f"/api/v1/g/{owner.guild.id}/initiatives/{initiative.id}"

    detail = await client.get(base, headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["name"] == "Apollo"

    roles = await client.get(f"{base}/roles", headers=headers)
    assert roles.status_code == 200, roles.text
    assert "project_manager" in {role["name"] for role in roles.json()}


@pytest.mark.integration
async def test_guild_member_outside_an_initiative_still_cannot_read_it(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The grantee leg widened nothing for an ordinary member of the guild."""
    owner = await acting_user(guild_role=GuildRole.admin)
    initiative = await create_initiative(
        session, owner.guild, owner.user, name="Apollo"
    )
    outsider = await acting_user(guild_role=GuildRole.member, guild=owner.guild)

    response = await client.get(
        outsider.g(f"/initiatives/{initiative.id}"), headers=outsider.headers
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "INITIATIVE_NOT_A_MEMBER"


@pytest.mark.integration
async def test_list_initiatives_guild_scope_requires_guild_admin(
    client: AsyncClient, session: AsyncSession, acting_user
):
    member = await acting_user(guild_role=GuildRole.member)

    response = await client.get(
        member.g("/initiatives/?scope=guild"), headers=member.headers
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "GUILD_ADMIN_REQUIRED"


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
    listing = await client.get(
        admin.g("/initiatives/?scope=guild"), headers=admin.headers
    )
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
    # A roster names members by handle. An address is never a guild's to hand
    # out, so it is absent from the shape entirely.
    handles = {user["username"] for user in data}
    assert admin.user.username in handles
    assert member1.user.username in handles
    assert member2.user.username in handles
    assert all("email" not in user for user in data)


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
        username="wonderland",
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
        "username",
        "discriminator",
        "full_name",
        "avatar_url",
        "status",
        "profile_decorations",
        "guild_role",
    }

    # Filtered by handle, which every guild has for every member.
    response = await client.get(
        admin.g(f"/initiatives/{initiative.id}/members/search"),
        headers=admin.headers,
        params={"search": "wonder"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 1
    assert body["items"][0]["username"] == "wonderland"

    # This guild takes the default and shows names, so a term that appears
    # only in the real name finds her too.
    response = await client.get(
        admin.g(f"/initiatives/{initiative.id}/members/search"),
        headers=admin.headers,
        params={"search": "Alice"},
    )
    assert response.json()["total_count"] == 1

    # Turn names off and the same term matches nothing, which is the half that
    # matters: the search reaches exactly what the guild renders.
    admin.guild.show_member_names = False
    session.add(admin.guild)
    await session.commit()

    response = await client.get(
        admin.g(f"/initiatives/{initiative.id}/members/search"),
        headers=admin.headers,
        params={"search": "Alice"},
    )
    assert response.json()["total_count"] == 0


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
        username="alice-ids",
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
    assert [item["username"] for item in body["items"]] == ["alice-ids"]


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
    handles = {user["username"] for user in response.json()}
    assert creator.user.username in handles

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
async def test_inviting_a_guild_admin_lands_them_on_the_manager_role(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """An invite naming a standard role for a guild admin still succeeds.

    A guild admin's standing already reaches every initiative, so their row
    carries the manager role — the invite settles that rather than refusing,
    which is what lets a project manager add an admin without first checking
    who is one.
    """
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

    assert response.status_code == 200
    member_roles = {m["user"]["id"]: m["role_name"] for m in response.json()["members"]}
    assert member_roles[target_admin.user.id] == "project_manager"


@pytest.mark.integration
async def test_promotion_to_guild_admin_lifts_existing_initiative_roles(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A promotion reaches the rows the person already held.

    Their guild role changes underneath initiative memberships that already
    exist, and only this path can bring them up to the manager role an admin's
    row carries — everything that writes a row settles it for itself.
    """
    from app.testing.schema_harness import route_session_to_guild

    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    joiner = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )

    response = await client.patch(
        f"/api/v1/guilds/{admin.guild.id}/members/{joiner.user.id}",
        headers=admin.headers,
        json={"role": "admin"},
    )
    assert response.status_code == 204, response.text

    await route_session_to_guild(session, admin.guild.id)
    membership = (
        await session.exec(
            select(InitiativeMember).where(
                InitiativeMember.initiative_id == admin.initiative.id,
                InitiativeMember.user_id == joiner.user.id,
            )
        )
    ).one()
    role = await initiatives_service.get_role_by_id(session, role_id=membership.role_id)
    assert role is not None and role.is_manager


@pytest.mark.integration
async def test_the_queue_badge_survives_a_role_a_promotion_left_behind(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A guild admin inside an initiative reads its queue whatever their row says.

    Answering a request is authority they hold as admin, so the badge follows
    the standing rather than the role their membership row happens to carry.
    """
    manager = await acting_user(guild_role=GuildRole.member)
    initiative = await _requestable(session, manager, name="Knockable")
    admin = await acting_user(
        guild_role=GuildRole.admin,
        guild=manager.guild,
        initiative=initiative,
        initiative_role="member",
    )
    created = await client.post(
        manager.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=(
            await acting_user(guild_role=GuildRole.member, guild=manager.guild)
        ).headers,
        json={},
    )
    assert created.status_code == 201, created.text

    response = await client.get(
        admin.g("/initiatives/directory"), headers=admin.headers
    )

    assert response.status_code == 200
    entry = next(e for e in response.json() if e["id"] == initiative.id)
    assert entry["pending_join_request_count"] == 1


@pytest.mark.integration
async def test_a_project_manager_can_invite_a_guild_admin(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The invite is the project manager's to make, on their own initiative."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    manager = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="project_manager",
    )
    target_admin = await acting_user(
        guild_role=GuildRole.admin, guild=admin.guild, email="admin3@example.com"
    )

    response = await client.post(
        manager.g(f"/initiatives/{admin.initiative.id}/members"),
        headers=manager.headers,
        json={"user_id": target_admin.user.id},
    )

    assert response.status_code == 200
    member_roles = {m["user"]["id"]: m["role_name"] for m in response.json()["members"]}
    assert member_roles[target_admin.user.id] == "project_manager"


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
async def test_directory_reads_the_same_way_for_a_guild_admin(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A guild admin's directory is theirs plus what is on offer.

    Their authority over the guild is unchanged; the front page just stops
    standing in for it. A private initiative they are not in is not listed to
    them any more than to anyone else — ``scope=guild`` is where the whole
    guild is, and guild settings is where it is staffed.
    """
    owner = await acting_user(guild_role=GuildRole.admin)
    await create_initiative(
        session, owner.guild, owner.user, name="Hidden", join_policy="private"
    )
    await create_initiative(
        session, owner.guild, owner.user, name="Askable", join_policy="open"
    )

    other_admin = await acting_user(guild_role=GuildRole.admin, guild=owner.guild)
    response = await client.get(
        other_admin.g("/initiatives/directory"), headers=other_admin.headers
    )

    assert response.status_code == 200
    listed = {entry["name"] for entry in response.json()}
    assert "Hidden" not in listed
    assert "Askable" in listed


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
async def test_self_join_absorbs_a_lost_insert_race(
    session: AsyncSession, acting_user, monkeypatch
):
    """Losing the insert race returns the winner's row, not a 500.

    Two overlapping joins both clear the membership lookup before either
    inserts, and the composite primary key then rejects the loser. Simulated
    here by making that lookup miss once while the row already exists — the
    interleaving a live race produces, without racing the test.
    """
    admin = await acting_user(guild_role=GuildRole.admin)
    initiative = await create_initiative(
        session, admin.guild, admin.user, name="Anyone", join_policy="open"
    )
    member = await acting_user(guild_role=GuildRole.member, guild=admin.guild)

    # The row the winning request already committed.
    winner = await initiatives_service.self_join(
        session, initiative=initiative, user_id=member.user.id
    )
    assert winner is not None

    real_lookup = initiatives_service.get_initiative_membership
    calls = {"n": 0}

    async def lookup_misses_once(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return await real_lookup(*args, **kwargs)

    monkeypatch.setattr(
        initiatives_service, "get_initiative_membership", lookup_misses_once
    )

    membership = await initiatives_service.self_join(
        session, initiative=initiative, user_id=member.user.id
    )

    assert membership is not None
    assert membership.user_id == member.user.id
    rows = (
        await session.exec(
            select(InitiativeMember).where(
                InitiativeMember.initiative_id == initiative.id,
                InitiativeMember.user_id == member.user.id,
            )
        )
    ).all()
    assert len(rows) == 1


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
@pytest.mark.parametrize("policy", ["private", "request"])
async def test_a_guild_admin_walks_into_a_closed_initiative_as_manager(
    client: AsyncClient, session: AsyncSession, acting_user, policy: str
):
    """A guild admin joins whatever the policy says, on the manager role.

    Their sidebar is their memberships now, so this is how they put an
    initiative in it — the same act as ticking themselves in guild settings,
    and the reason they never have to knock at a queue they could answer.
    """
    owner = await acting_user(guild_role=GuildRole.admin)
    initiative = await create_initiative(
        session, owner.guild, owner.user, name=f"Closed {policy}", join_policy=policy
    )
    admin = await acting_user(guild_role=GuildRole.admin, guild=owner.guild)

    response = await client.post(
        admin.g(f"/initiatives/{initiative.id}/join"), headers=admin.headers
    )

    assert response.status_code == 200
    entry = next(
        m for m in response.json()["members"] if m["user"]["id"] == admin.user.id
    )
    assert entry["role_name"] == "project_manager"
    assert entry["is_manager"] is True


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


# ============================================================================
# Discovery: join requests
# ============================================================================


async def _notifications_for(
    session: AsyncSession, user_id: int, ntype: NotificationType
) -> list[Notification]:
    result = await session.exec(
        select(Notification).where(
            Notification.user_id == user_id,
            Notification.type == ntype,
        )
    )
    return list(result.all())


async def _requestable(session: AsyncSession, actor, **overrides):
    """A `request`-policy initiative managed by ``actor``."""
    return await create_initiative(
        session,
        actor.guild,
        actor.user,
        join_policy="request",
        **overrides,
    )


@pytest.mark.integration
async def test_join_request_created_on_request_policy(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The happy path: a guild member knocks and the row lands pending."""
    manager = await acting_user(guild_role=GuildRole.member)
    initiative = await _requestable(session, manager, name="Knockable")
    member = await acting_user(guild_role=GuildRole.member, guild=manager.guild)

    response = await client.post(
        member.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=member.headers,
        json={"message": "I'd like to help out"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"
    assert body["message"] == "I'd like to help out"
    assert body["user"]["id"] == member.user.id
    assert body["initiative_id"] == initiative.id
    assert body["resolved_at"] is None
    assert body["resolved_by"] is None
    assert body["prior_denials"] == 0

    # No membership row yet — the knock grants nothing.
    assert (
        await initiatives_service.get_initiative_membership(
            session, initiative_id=initiative.id, user_id=member.user.id
        )
    ) is None


@pytest.mark.integration
@pytest.mark.parametrize("policy", ["private", "open"])
async def test_join_request_rejected_for_non_request_policy(
    client: AsyncClient, session: AsyncSession, acting_user, policy: str
):
    """`private` and `open` answer identically — "not by this route" — so the
    refusal reveals no more about a private initiative than it did before."""
    manager = await acting_user(guild_role=GuildRole.member)
    initiative = await create_initiative(
        session,
        manager.guild,
        manager.user,
        name=f"Closed {policy}",
        join_policy=policy,
    )
    member = await acting_user(guild_role=GuildRole.member, guild=manager.guild)

    response = await client.post(
        member.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=member.headers,
        json={},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "INITIATIVE_NOT_REQUESTABLE"


@pytest.mark.integration
async def test_second_pending_join_request_conflicts(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """One live request per door."""
    manager = await acting_user(guild_role=GuildRole.member)
    initiative = await _requestable(session, manager, name="Knockable")
    member = await acting_user(guild_role=GuildRole.member, guild=manager.guild)

    first = await client.post(
        member.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=member.headers,
        json={},
    )
    assert first.status_code == 201

    second = await client.post(
        member.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=member.headers,
        json={},
    )

    assert second.status_code == 409
    assert second.json()["detail"] == "INITIATIVE_JOIN_REQUEST_ALREADY_PENDING"


@pytest.mark.integration
async def test_join_request_from_existing_member_conflicts(
    client: AsyncClient, session: AsyncSession, acting_user
):
    manager = await acting_user(guild_role=GuildRole.member)
    initiative = await _requestable(session, manager, name="Knockable")
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=manager.guild,
        initiative=initiative,
        initiative_role="member",
    )

    response = await client.post(
        member.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=member.headers,
        json={},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "INITIATIVE_ALREADY_A_MEMBER"


@pytest.mark.integration
async def test_guild_admin_cannot_request_to_join(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A guild admin already reaches every initiative in their guild, and must
    never hold a standard member role — so there is nothing to ask for, and no
    request that could later be approved into a forbidden row."""
    manager = await acting_user(guild_role=GuildRole.member)
    initiative = await _requestable(session, manager, name="Knockable")
    admin = await acting_user(guild_role=GuildRole.admin, guild=manager.guild)

    response = await client.post(
        admin.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=admin.headers,
        json={},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "INITIATIVE_GUILD_ADMIN_NEED_NOT_REQUEST"


@pytest.mark.integration
async def test_denied_requester_may_ask_again(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Only a *pending* row blocks: a refusal is history, not a ban, and the
    second ask carries the first refusal for the manager to see."""
    manager = await acting_user(guild_role=GuildRole.member)
    initiative = await _requestable(session, manager, name="Knockable")
    member = await acting_user(guild_role=GuildRole.member, guild=manager.guild)

    first = await client.post(
        member.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=member.headers,
        json={},
    )
    assert first.status_code == 201
    denied = await client.post(
        manager.g(
            f"/initiatives/{initiative.id}/join-requests/{first.json()['id']}/deny"
        ),
        headers=manager.headers,
    )
    assert denied.status_code == 200

    again = await client.post(
        member.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=member.headers,
        json={},
    )

    assert again.status_code == 201
    assert again.json()["status"] == "pending"
    assert again.json()["prior_denials"] == 1


@pytest.mark.integration
async def test_join_request_absorbs_a_lost_insert_race(
    session: AsyncSession, acting_user, monkeypatch
):
    """Losing the partial-unique race reads back the winner's row and reports the
    ordinary conflict, never a 500.

    Two overlapping knocks both clear the pending lookup before either inserts,
    and ``uq_initiative_join_requests_pending`` then rejects the loser.
    Simulated by making that lookup miss once while the row already exists — the
    interleaving a live race produces, without racing the test.
    """
    manager = await acting_user(guild_role=GuildRole.member)
    initiative = await _requestable(session, manager, name="Knockable")
    member = await acting_user(guild_role=GuildRole.member, guild=manager.guild)

    winner, created = await initiatives_service.create_join_request(
        session, initiative=initiative, user_id=member.user.id
    )
    assert created is True

    real_lookup = initiatives_service.get_pending_join_request
    calls = {"n": 0}

    async def lookup_misses_once(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return await real_lookup(*args, **kwargs)

    monkeypatch.setattr(
        initiatives_service, "get_pending_join_request", lookup_misses_once
    )

    loser, created_again = await initiatives_service.create_join_request(
        session, initiative=initiative, user_id=member.user.id
    )

    assert created_again is False
    assert loser.id == winner.id
    rows = (
        await session.exec(
            select(InitiativeJoinRequest).where(
                InitiativeJoinRequest.initiative_id == initiative.id,
                InitiativeJoinRequest.user_id == member.user.id,
            )
        )
    ).all()
    assert len(rows) == 1


@pytest.mark.integration
async def test_manager_reads_the_pending_queue(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The queue carries everything the decision needs: who, what they said, and
    whether this initiative has turned them down before."""
    manager = await acting_user(guild_role=GuildRole.member)
    initiative = await _requestable(session, manager, name="Knockable")
    member = await acting_user(
        guild_role=GuildRole.member, guild=manager.guild, full_name="Ada Lovelace"
    )

    first = await client.post(
        member.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=member.headers,
        json={"message": "first try"},
    )
    await client.post(
        manager.g(
            f"/initiatives/{initiative.id}/join-requests/{first.json()['id']}/deny"
        ),
        headers=manager.headers,
    )
    await client.post(
        member.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=member.headers,
        json={"message": "second try"},
    )

    response = await client.get(
        manager.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=manager.headers,
    )

    assert response.status_code == 200
    queue = response.json()
    # Pending only by default: the denied row is history, not a decision.
    assert len(queue) == 1
    assert queue[0]["status"] == "pending"
    assert queue[0]["message"] == "second try"
    assert queue[0]["user"]["id"] == member.user.id
    # The queue names who is asking the way this guild names anyone —
    # by handle, since it does not show real names.
    assert queue[0]["user"]["username"] == member.user.username
    assert queue[0]["prior_denials"] == 1

    history = await client.get(
        manager.g(f"/initiatives/{initiative.id}/join-requests?status=denied"),
        headers=manager.headers,
    )
    assert history.status_code == 200
    assert [row["status"] for row in history.json()] == ["denied"]


@pytest.mark.integration
async def test_plain_member_cannot_read_the_queue(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Who asked to get in is manager business — a non-manager member of the
    initiative has no more claim on it than an outsider."""
    manager = await acting_user(guild_role=GuildRole.member)
    initiative = await _requestable(session, manager, name="Knockable")
    insider = await acting_user(
        guild_role=GuildRole.member,
        guild=manager.guild,
        initiative=initiative,
        initiative_role="member",
    )

    response = await client.get(
        insider.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=insider.headers,
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "INITIATIVE_MANAGER_REQUIRED"


@pytest.mark.integration
async def test_guild_admin_can_read_the_queue(
    client: AsyncClient, session: AsyncSession, acting_user
):
    manager = await acting_user(guild_role=GuildRole.member)
    initiative = await _requestable(session, manager, name="Knockable")
    member = await acting_user(guild_role=GuildRole.member, guild=manager.guild)
    await client.post(
        member.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=member.headers,
        json={},
    )
    admin = await acting_user(guild_role=GuildRole.admin, guild=manager.guild)

    response = await client.get(
        admin.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=admin.headers,
    )

    assert response.status_code == 200
    assert [row["user"]["id"] for row in response.json()] == [member.user.id]


@pytest.mark.integration
async def test_requester_reads_only_their_own_request(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """``initiative_join_requests`` is guild-level: the schema boundary is its
    only DB gate, so row visibility is an app-layer contract — pinned here.

    A requester reaches their own row and no one else's; the queue itself stays
    shut to them.
    """
    manager = await acting_user(guild_role=GuildRole.member)
    initiative = await _requestable(session, manager, name="Knockable")
    alice = await acting_user(guild_role=GuildRole.member, guild=manager.guild)
    bob = await acting_user(guild_role=GuildRole.member, guild=manager.guild)

    for actor in (alice, bob):
        created = await client.post(
            actor.g(f"/initiatives/{initiative.id}/join-requests"),
            headers=actor.headers,
            json={"message": f"from {actor.user.id}"},
        )
        assert created.status_code == 201

    mine = await client.get(
        alice.g(f"/initiatives/{initiative.id}/join-requests/me"),
        headers=alice.headers,
    )
    assert mine.status_code == 200
    assert [row["user"]["id"] for row in mine.json()] == [alice.user.id]

    # And the full queue — Bob's row included — stays out of reach.
    queue = await client.get(
        alice.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=alice.headers,
    )
    assert queue.status_code == 403
    assert queue.json()["detail"] == "INITIATIVE_MANAGER_REQUIRED"


@pytest.mark.integration
async def test_approve_creates_membership_and_flips_content_visibility(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The point of the flow: approval writes the one membership row every join
    path produces, and ``initiative_access`` does the rest — content that 404'd
    before the approval resolves after it, with no RLS change at all."""
    from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
    from app.testing.factories import create_project
    from app.testing.schema_harness import route_session_to_guild

    manager = await acting_user(guild_role=GuildRole.member)
    initiative = await _requestable(session, manager, name="Knockable")
    project = await create_project(
        session, initiative, manager.user, name="Shared work"
    )
    # Shared with the whole initiative, so gate 4 is satisfied for any member and
    # the membership row is the only thing that changes across the approval.
    await route_session_to_guild(session, manager.guild.id)
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

    member = await acting_user(guild_role=GuildRole.member, guild=manager.guild)
    before = await client.get(
        member.g(f"/projects/{project.id}"), headers=member.headers
    )
    assert before.status_code == 404

    created = await client.post(
        member.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=member.headers,
        json={},
    )
    assert created.status_code == 201
    request_id = created.json()["id"]

    approved = await client.post(
        manager.g(f"/initiatives/{initiative.id}/join-requests/{request_id}/approve"),
        headers=manager.headers,
    )

    assert approved.status_code == 200
    body = approved.json()
    assert body["status"] == "approved"
    assert body["resolved_by"] == manager.user.id
    assert body["resolved_at"] is not None

    membership = await initiatives_service.get_initiative_membership_with_role(
        session, initiative_id=initiative.id, user_id=member.user.id
    )
    assert membership is not None
    assert membership.role_ref.name == "member"
    assert membership.role_ref.is_manager is False
    assert membership.oidc_managed is False

    after = await client.get(
        member.g(f"/projects/{project.id}"), headers=member.headers
    )
    assert after.status_code == 200
    assert after.json()["name"] == "Shared work"


@pytest.mark.integration
async def test_approving_an_already_resolved_request_conflicts(
    client: AsyncClient, session: AsyncSession, acting_user
):
    manager = await acting_user(guild_role=GuildRole.member)
    initiative = await _requestable(session, manager, name="Knockable")
    member = await acting_user(guild_role=GuildRole.member, guild=manager.guild)
    created = await client.post(
        member.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=member.headers,
        json={},
    )
    request_id = created.json()["id"]
    url = manager.g(f"/initiatives/{initiative.id}/join-requests/{request_id}/approve")
    assert (await client.post(url, headers=manager.headers)).status_code == 200

    again = await client.post(url, headers=manager.headers)

    assert again.status_code == 409
    assert again.json()["detail"] == "INITIATIVE_JOIN_REQUEST_ALREADY_RESOLVED"


@pytest.mark.integration
async def test_resolving_a_request_someone_else_answered_conflicts(
    session: AsyncSession, acting_user
):
    """A decision is claimed before it is granted.

    The guard is the ``WHERE status = 'pending'`` on the write, not the check
    the caller did first — so a second answer matches no row and is refused,
    and nothing is granted behind it. That is what stops an approval creating a
    member that a simultaneous denial then records as refused.

    This drives the two answers sequentially rather than truly concurrently.
    It doesn't need to interleave them: the claim never consults the caller's
    in-memory snapshot, only the row's committed state, so a stale pending
    snapshot and an already-settled row take the same path. Serializing the
    two writers is Postgres's row lock, not this code.
    """
    manager = await acting_user(guild_role=GuildRole.member)
    initiative = await _requestable(session, manager, name="Knockable")
    member = await acting_user(guild_role=GuildRole.member, guild=manager.guild)
    request, _ = await initiatives_service.create_join_request(
        session, initiative=initiative, user_id=member.user.id, message=None
    )
    await session.commit()

    # The first manager settles it.
    await initiatives_service.resolve_join_request(
        session, request=request, resolver_id=manager.user.id, approved=False
    )
    await session.commit()

    # The second still holds the row it read while the request was pending.
    with pytest.raises(initiatives_service.JoinRequestAlreadyResolved):
        await initiatives_service.resolve_join_request(
            session, request=request, resolver_id=manager.user.id, approved=True
        )

    # The denial stands, and no membership was written behind it.
    assert request.status == "denied"
    assert (
        await initiatives_service.get_initiative_membership(
            session, initiative_id=initiative.id, user_id=member.user.id
        )
        is None
    )


@pytest.mark.integration
async def test_approving_when_already_a_member_succeeds(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A requester who got in another way while the request sat in the queue is
    absorbed: the row resolves and the call succeeds instead of colliding with
    the membership primary key."""
    manager = await acting_user(guild_role=GuildRole.member)
    initiative = await _requestable(session, manager, name="Knockable")
    member = await acting_user(guild_role=GuildRole.member, guild=manager.guild)
    created = await client.post(
        member.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=member.headers,
        json={},
    )
    request_id = created.json()["id"]

    # Added by hand while the request waits.
    added = await client.post(
        manager.g(f"/initiatives/{initiative.id}/members"),
        headers=manager.headers,
        json={"user_id": member.user.id},
    )
    assert added.status_code == 200

    response = await client.post(
        manager.g(f"/initiatives/{initiative.id}/join-requests/{request_id}/approve"),
        headers=manager.headers,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    rows = (
        await session.exec(
            select(InitiativeMember).where(
                InitiativeMember.initiative_id == initiative.id,
                InitiativeMember.user_id == member.user.id,
            )
        )
    ).all()
    assert len(rows) == 1


@pytest.mark.integration
async def test_deny_resolves_without_membership(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A denial changes nothing about what the requester can see."""
    from app.testing.factories import create_project

    manager = await acting_user(guild_role=GuildRole.member)
    initiative = await _requestable(session, manager, name="Knockable")
    project = await create_project(
        session, initiative, manager.user, name="Shared work"
    )
    member = await acting_user(guild_role=GuildRole.member, guild=manager.guild)
    created = await client.post(
        member.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=member.headers,
        json={},
    )
    request_id = created.json()["id"]

    response = await client.post(
        manager.g(f"/initiatives/{initiative.id}/join-requests/{request_id}/deny"),
        headers=manager.headers,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "denied"
    assert response.json()["resolved_by"] == manager.user.id
    assert (
        await initiatives_service.get_initiative_membership(
            session, initiative_id=initiative.id, user_id=member.user.id
        )
    ) is None
    still_hidden = await client.get(
        member.g(f"/projects/{project.id}"), headers=member.headers
    )
    assert still_hidden.status_code == 404


@pytest.mark.integration
async def test_resolving_a_request_from_another_initiative_is_not_found(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The request id is only meaningful inside its own door."""
    manager = await acting_user(guild_role=GuildRole.member)
    initiative = await _requestable(session, manager, name="Knockable")
    other = await create_initiative(
        session, manager.guild, manager.user, name="Elsewhere", join_policy="request"
    )
    member = await acting_user(guild_role=GuildRole.member, guild=manager.guild)
    created = await client.post(
        member.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=member.headers,
        json={},
    )
    request_id = created.json()["id"]

    response = await client.post(
        manager.g(f"/initiatives/{other.id}/join-requests/{request_id}/approve"),
        headers=manager.headers,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "INITIATIVE_JOIN_REQUEST_NOT_FOUND"


@pytest.mark.integration
@pytest.mark.parametrize("action", ["approve", "deny"])
async def test_non_manager_member_cannot_resolve(
    client: AsyncClient, session: AsyncSession, acting_user, action: str
):
    """Answering a request grants access, so it takes exactly the authority that
    adding a member by hand takes."""
    manager = await acting_user(guild_role=GuildRole.member)
    initiative = await _requestable(session, manager, name="Knockable")
    requester = await acting_user(guild_role=GuildRole.member, guild=manager.guild)
    created = await client.post(
        requester.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=requester.headers,
        json={},
    )
    request_id = created.json()["id"]
    insider = await acting_user(
        guild_role=GuildRole.member,
        guild=manager.guild,
        initiative=initiative,
        initiative_role="member",
    )

    response = await client.post(
        insider.g(f"/initiatives/{initiative.id}/join-requests/{request_id}/{action}"),
        headers=insider.headers,
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "INITIATIVE_MANAGER_REQUIRED"


@pytest.mark.integration
@pytest.mark.parametrize("action", ["approve", "deny"])
async def test_scoped_grantee_cannot_resolve(
    client: AsyncClient, session: AsyncSession, acting_user, action: str
):
    """A grant reaches the guild for a window; the membership row an approval
    writes has no end date, so the two are never traded for each other."""
    manager = await acting_user(guild_role=GuildRole.admin)
    initiative = await _requestable(session, manager, name="Knockable")
    requester = await acting_user(guild_role=GuildRole.member, guild=manager.guild)
    created = await client.post(
        requester.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=requester.headers,
        json={},
    )
    request_id = created.json()["id"]

    grantee = await acting_user("support")
    await _live_grant(
        session,
        user=grantee.user,
        guild=manager.guild,
        approver=manager.user,
        level="read_write",
    )

    response = await client.post(
        f"/api/v1/g/{manager.guild.id}/initiatives/{initiative.id}"
        f"/join-requests/{request_id}/{action}",
        headers=grantee.headers,
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "INITIATIVE_GRANT_CANNOT_MANAGE_MEMBERS"


@pytest.mark.integration
async def test_break_glass_can_approve(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Break-glass is routed as a full guild admin for its window, which is the
    same authority a guild admin already exercises over its members."""
    from app.models.platform.user import UserRole

    manager = await acting_user(guild_role=GuildRole.admin)
    initiative = await _requestable(session, manager, name="Knockable")
    requester = await acting_user(guild_role=GuildRole.member, guild=manager.guild)
    created = await client.post(
        requester.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=requester.headers,
        json={},
    )
    request_id = created.json()["id"]

    # data.bypass platform admin, deliberately NOT a guild member.
    bg_admin = await acting_user(UserRole.operator)
    await _live_grant(
        session,
        user=bg_admin.user,
        guild=manager.guild,
        approver=manager.user,
        level="read_write",
    )

    response = await client.post(
        f"/api/v1/g/{manager.guild.id}/initiatives/{initiative.id}"
        f"/join-requests/{request_id}/approve",
        headers=bg_admin.headers,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    assert (
        await initiatives_service.get_initiative_membership(
            session, initiative_id=initiative.id, user_id=requester.user.id
        )
    ) is not None


@pytest.mark.integration
async def test_scoped_grantee_cannot_request_to_join(
    client: AsyncClient, session: AsyncSession, acting_user
):
    manager = await acting_user(guild_role=GuildRole.admin)
    initiative = await _requestable(session, manager, name="Knockable")

    grantee = await acting_user("support")
    await _live_grant(
        session,
        user=grantee.user,
        guild=manager.guild,
        approver=manager.user,
        level="read_write",
    )

    response = await client.post(
        f"/api/v1/g/{manager.guild.id}/initiatives/{initiative.id}/join-requests",
        headers=grantee.headers,
        json={},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "INITIATIVE_GRANT_CANNOT_MANAGE_MEMBERS"


@pytest.mark.integration
async def test_join_request_notifies_managers(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Addressed to the people who can answer it, and carrying who asked —
    never any of the initiative's content."""
    manager = await acting_user(guild_role=GuildRole.member)
    initiative = await _requestable(session, manager, name="Knockable")
    bystander = await acting_user(
        guild_role=GuildRole.member,
        guild=manager.guild,
        initiative=initiative,
        initiative_role="member",
    )
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=manager.guild,
        full_name="Ada Lovelace",
        username="ada",
        discriminator=1815,
    )

    response = await client.post(
        member.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=member.headers,
        json={},
    )
    assert response.status_code == 201

    notes = await _notifications_for(
        session, manager.user.id, NotificationType.initiative_join_requested
    )
    assert len(notes) == 1
    assert notes[0].data["initiative_id"] == initiative.id
    assert notes[0].data["requester_id"] == member.user.id
    # A notification is read on the cross-guild list, away from the guild it
    # was written in, so it names her by handle whatever this guild renders.
    assert notes[0].data["requester_name"] == "ada#1815"
    assert notes[0].data["request_id"] == response.json()["id"]
    # It was sent to be acted on, so it opens the queue rather than the
    # initiative's front page. Only managers ever receive one.
    assert notes[0].data["target_path"] == f"/i/{initiative.id}/settings/members"

    # A non-manager member of the initiative is not on the hook for answering it.
    assert (
        await _notifications_for(
            session, bystander.user.id, NotificationType.initiative_join_requested
        )
        == []
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    ("action", "expected_type"),
    [
        ("approve", NotificationType.initiative_join_approved),
        ("deny", NotificationType.initiative_join_denied),
    ],
)
async def test_resolution_notifies_the_requester(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    action: str,
    expected_type: NotificationType,
):
    manager = await acting_user(guild_role=GuildRole.member)
    initiative = await _requestable(session, manager, name="Knockable")
    member = await acting_user(guild_role=GuildRole.member, guild=manager.guild)
    created = await client.post(
        member.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=member.headers,
        json={},
    )
    request_id = created.json()["id"]

    resolved = await client.post(
        manager.g(f"/initiatives/{initiative.id}/join-requests/{request_id}/{action}"),
        headers=manager.headers,
    )
    assert resolved.status_code == 200

    notes = await _notifications_for(session, member.user.id, expected_type)
    assert len(notes) == 1
    assert notes[0].data["initiative_id"] == initiative.id
    assert notes[0].data["initiative_name"] == "Knockable"
    assert notes[0].data["request_id"] == request_id


@pytest.mark.integration
async def test_directory_badges_the_queue_for_managers_only(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The pending count rides the directory the guild home already loads, and
    only for whoever could open the queue — a bystander reads a flat zero rather
    than a headcount of their peers' knocking."""
    manager = await acting_user(guild_role=GuildRole.member)
    initiative = await _requestable(session, manager, name="Knockable")
    insider = await acting_user(
        guild_role=GuildRole.member,
        guild=manager.guild,
        initiative=initiative,
        initiative_role="member",
    )
    requester = await acting_user(guild_role=GuildRole.member, guild=manager.guild)
    created = await client.post(
        requester.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=requester.headers,
        json={},
    )
    assert created.status_code == 201

    as_manager = await client.get(
        manager.g("/initiatives/directory"), headers=manager.headers
    )
    assert as_manager.status_code == 200
    entry = next(e for e in as_manager.json() if e["id"] == initiative.id)
    assert entry["pending_join_request_count"] == 1

    as_insider = await client.get(
        insider.g("/initiatives/directory"), headers=insider.headers
    )
    entry = next(e for e in as_insider.json() if e["id"] == initiative.id)
    assert entry["pending_join_request_count"] == 0

    as_requester = await client.get(
        requester.g("/initiatives/directory"), headers=requester.headers
    )
    entry = next(e for e in as_requester.json() if e["id"] == initiative.id)
    assert entry["pending_join_request_count"] == 0
    assert entry["has_pending_request"] is True

    # A guild admin outside the initiative is a bystander here like anyone
    # else: they staff themselves onto it to take the queue.
    admin = await acting_user(guild_role=GuildRole.admin, guild=manager.guild)
    as_admin = await client.get(
        admin.g("/initiatives/directory"), headers=admin.headers
    )
    entry = next(e for e in as_admin.json() if e["id"] == initiative.id)
    assert entry["pending_join_request_count"] == 0


def _capture_join_request_emails(monkeypatch) -> list[dict]:
    """Record every join-request email instead of reaching SMTP."""
    sent: list[dict] = []

    async def _fake_email(
        _session,
        recipient,
        *,
        event,
        initiative_name,
        link,
        requester=None,
        message=None,
    ):
        sent.append(
            {
                "recipient_id": recipient.id,
                "event": event,
                "initiative_name": initiative_name,
                "link": link,
                "requester": requester,
                "message": message,
            }
        )

    monkeypatch.setattr(
        email_service, "send_initiative_join_request_email", _fake_email
    )
    return sent


@pytest.mark.integration
async def test_join_request_emails_the_managers(
    client: AsyncClient, session: AsyncSession, acting_user, monkeypatch
):
    """Managers get the mail, with who asked and what they wrote — the two
    things the decision rests on. A non-manager member of the initiative is not
    on the hook for answering, so nothing reaches them."""
    sent = _capture_join_request_emails(monkeypatch)

    manager = await acting_user(guild_role=GuildRole.member)
    initiative = await _requestable(session, manager, name="Knockable")
    bystander = await acting_user(
        guild_role=GuildRole.member,
        guild=manager.guild,
        initiative=initiative,
        initiative_role="member",
    )
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=manager.guild,
        full_name="Ada Lovelace",
        username="ada",
        discriminator=1815,
    )

    response = await client.post(
        member.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=member.headers,
        json={"message": "I maintain the parser"},
    )
    assert response.status_code == 201

    assert [m["recipient_id"] for m in sent] == [manager.user.id]
    assert sent[0]["event"] == "requested"
    assert sent[0]["initiative_name"] == "Knockable"
    # Mail is read outside the guild too, so the handle names her there as well.
    assert sent[0]["requester"] == "ada#1815"
    assert sent[0]["message"] == "I maintain the parser"
    # Guild-scoped news, so the link carries the guild rather than being a bare
    # frontend path.
    assert f"guild_id={manager.guild.id}" in sent[0]["link"]
    assert bystander.user.id not in {m["recipient_id"] for m in sent}


@pytest.mark.integration
@pytest.mark.parametrize(
    ("action", "event"), [("approve", "approved"), ("deny", "denied")]
)
async def test_resolution_emails_the_requester(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    monkeypatch,
    action: str,
    event: str,
):
    """The outcome goes back to the person who asked — and only to them."""
    manager = await acting_user(guild_role=GuildRole.member)
    initiative = await _requestable(session, manager, name="Knockable")
    member = await acting_user(guild_role=GuildRole.member, guild=manager.guild)
    created = await client.post(
        member.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=member.headers,
        json={},
    )
    request_id = created.json()["id"]

    # Capture only after the request lands, so the queue mail is out of the way.
    sent = _capture_join_request_emails(monkeypatch)

    resolved = await client.post(
        manager.g(f"/initiatives/{initiative.id}/join-requests/{request_id}/{action}"),
        headers=manager.headers,
    )
    assert resolved.status_code == 200

    assert [m["recipient_id"] for m in sent] == [member.user.id]
    assert sent[0]["event"] == event
    assert sent[0]["initiative_name"] == "Knockable"
    assert sent[0]["requester"] is None
    assert f"guild_id={manager.guild.id}" in sent[0]["link"]


@pytest.mark.integration
async def test_join_request_email_honours_the_initiative_preference(
    client: AsyncClient, session: AsyncSession, acting_user, monkeypatch
):
    """These are initiative-membership news, so they ride the preference that
    already governs that topic — no second toggle for the same idea."""
    sent = _capture_join_request_emails(monkeypatch)

    manager = await acting_user(
        guild_role=GuildRole.member, email_initiative_addition=False
    )
    initiative = await _requestable(session, manager, name="Knockable")
    member = await acting_user(guild_role=GuildRole.member, guild=manager.guild)

    response = await client.post(
        member.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=member.headers,
        json={},
    )

    assert response.status_code == 201
    assert sent == []
    # The in-app notification still lands: the preference governs email, not the
    # bell.
    assert (
        len(
            await _notifications_for(
                session, manager.user.id, NotificationType.initiative_join_requested
            )
        )
        == 1
    )


@pytest.mark.integration
async def test_unconfigured_smtp_does_not_break_the_request(
    client: AsyncClient, session: AsyncSession, acting_user, monkeypatch
):
    """Email is best effort: with no SMTP configured the knock still lands."""

    async def _unconfigured(*args, **kwargs):
        raise email_service.EmailNotConfiguredError("no smtp")

    monkeypatch.setattr(
        email_service, "send_initiative_join_request_email", _unconfigured
    )

    manager = await acting_user(guild_role=GuildRole.member)
    initiative = await _requestable(session, manager, name="Knockable")
    member = await acting_user(guild_role=GuildRole.member, guild=manager.guild)

    response = await client.post(
        member.g(f"/initiatives/{initiative.id}/join-requests"),
        headers=member.headers,
        json={},
    )

    assert response.status_code == 201
    assert (
        len(
            await _notifications_for(
                session, manager.user.id, NotificationType.initiative_join_requested
            )
        )
        == 1
    )


@pytest.mark.integration
async def test_initiative_member_search_finds_a_misspelled_name(
    client, session, acting_user
):
    """One rule for looking people up, wherever the picker is. An initiative's
    roster matches a near miss exactly as the guild's does."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    member = await create_user(session, username="moonwhisper")
    await create_guild_membership(session, user=member, guild=a.guild)
    await create_initiative_member(session, a.initiative, member)

    response = await client.get(
        a.g(f"/initiatives/{a.initiative.id}/members/search"),
        headers=a.headers,
        params={"search": "moonwhsiper"},
    )
    assert response.status_code == 200, response.text
    assert member.username in {u["username"] for u in response.json()["items"]}
