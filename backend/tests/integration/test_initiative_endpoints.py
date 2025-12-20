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
from app.models.initiative import InitiativeMember, InitiativeRole
from tests.factories import (
    create_guild,
    create_guild_membership,
    create_user,
    get_guild_headers,
)


@pytest.mark.integration
async def test_list_initiatives_requires_guild_context(
    client: AsyncClient, session: AsyncSession
):
    """Test that listing initiatives requires guild context."""
    user = await create_user(session, email="test@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild)

    # Request without X-Guild-ID header
    headers = {"Authorization": f"Bearer fake_token_{user.id}"}
    response = await client.get("/api/v1/initiatives/", headers=headers)

    assert response.status_code == 403


@pytest.mark.integration
async def test_list_initiatives_as_admin_shows_all(
    client: AsyncClient, session: AsyncSession
):
    """Test that guild admin can see all initiatives."""
    from app.models.initiative import Initiative, InitiativeMember, InitiativeRole

    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)

    # Create multiple initiatives
    initiative1 = Initiative(name="Initiative 1", guild_id=guild.id)
    initiative2 = Initiative(name="Initiative 2", guild_id=guild.id)
    session.add(initiative1)
    session.add(initiative2)
    await session.commit()
    await session.refresh(initiative1)
    await session.refresh(initiative2)

    # Add admin as manager
    session.add(InitiativeMember(initiative_id=initiative1.id, user_id=admin.id, role=InitiativeRole.project_manager))
    session.add(InitiativeMember(initiative_id=initiative2.id, user_id=admin.id, role=InitiativeRole.project_manager))
    await session.commit()

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
    from tests.factories import create_initiative, create_project

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
    initiative2 = await create_initiative(
        session, guild, admin, name="Other Initiative"
    )

    # Add member to only initiative1
    session.add(InitiativeMember(
        initiative_id=initiative1.id,
        user_id=member.id,
        role=InitiativeRole.member,
    ))
    await session.commit()

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
    from tests.factories import create_initiative, create_project

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
    assert "already exists" in response.json()["detail"].lower()


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
    assert data["members"][0]["user_id"] == admin.id
    assert data["members"][0]["role"] == "project_manager"


@pytest.mark.integration
async def test_update_initiative_as_manager(
    client: AsyncClient, session: AsyncSession
):
    """Test that initiative manager can update initiative."""
    from tests.factories import create_initiative, create_project

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
    from tests.factories import create_initiative, create_project

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
    from tests.factories import create_initiative, create_project

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
    session.add(InitiativeMember(
        initiative_id=initiative.id,
        user_id=member.id,
        role=InitiativeRole.member,
    ))
    await session.commit()

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
    from tests.factories import create_initiative, create_project

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
    from tests.factories import create_initiative, create_project

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
    from tests.factories import create_initiative, create_project

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
    from tests.factories import create_initiative, create_project

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
    assert "default" in response.json()["detail"].lower()


@pytest.mark.integration
async def test_get_initiative_members(client: AsyncClient, session: AsyncSession):
    """Test getting all members of an initiative."""
    from tests.factories import create_initiative, create_project

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
    session.add(InitiativeMember(
        initiative_id=initiative.id,
        user_id=member1.id,
        role=InitiativeRole.member,
    ))
    session.add(InitiativeMember(
        initiative_id=initiative.id,
        user_id=member2.id,
        role=InitiativeRole.member,
    ))
    await session.commit()

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
    from tests.factories import create_initiative, create_project

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
    member_ids = {m["user_id"] for m in data["members"]}
    assert new_member.id in member_ids


@pytest.mark.integration
async def test_add_initiative_member_as_regular_member_forbidden(
    client: AsyncClient, session: AsyncSession
):
    """Test that regular members cannot add members."""
    from tests.factories import create_initiative, create_project

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
    session.add(InitiativeMember(
        initiative_id=initiative.id,
        user_id=member.id,
        role=InitiativeRole.member,
    ))
    await session.commit()

    headers = get_guild_headers(guild, member)
    payload = {"user_id": new_member.id, "role": "member"}

    response = await client.post(
        f"/api/v1/initiatives/{initiative.id}/members", headers=headers, json=payload
    )

    assert response.status_code == 403


@pytest.mark.integration
async def test_add_user_not_in_guild_fails(client: AsyncClient, session: AsyncSession):
    """Test that adding a user not in the guild fails."""
    from tests.factories import create_initiative, create_project

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
    assert "guild" in response.json()["detail"].lower()


@pytest.mark.integration
async def test_update_initiative_member_role(
    client: AsyncClient, session: AsyncSession
):
    """Test updating an initiative member's role."""
    from tests.factories import create_initiative, create_project

    admin = await create_user(session, email="admin@example.com")
    member = await create_user(session, email="member@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=member, guild=guild)

    initiative = await create_initiative(
        session, guild, admin, name="Test Initiative"
    )
    session.add(InitiativeMember(
        initiative_id=initiative.id,
        user_id=member.id,
        role=InitiativeRole.member,
    ))
    await session.commit()

    headers = get_guild_headers(guild, admin)
    payload = {"role": "project_manager"}

    response = await client.patch(
        f"/api/v1/initiatives/{initiative.id}/members/{member.id}",
        headers=headers,
        json=payload,
    )

    assert response.status_code == 200
    data = response.json()
    member_roles = {m["user_id"]: m["role"] for m in data["members"]}
    assert member_roles[member.id] == "project_manager"


@pytest.mark.integration
async def test_remove_initiative_member(client: AsyncClient, session: AsyncSession):
    """Test removing an initiative member."""
    from tests.factories import create_initiative, create_project

    admin = await create_user(session, email="admin@example.com")
    member = await create_user(session, email="member@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=member, guild=guild)

    initiative = await create_initiative(
        session, guild, admin, name="Test Initiative"
    )
    session.add(InitiativeMember(
        initiative_id=initiative.id,
        user_id=member.id,
        role=InitiativeRole.member,
    ))

    headers = get_guild_headers(guild, admin)
    response = await client.delete(
        f"/api/v1/initiatives/{initiative.id}/members/{member.id}", headers=headers
    )

    assert response.status_code == 200
    data = response.json()
    member_ids = {m["user_id"] for m in data["members"]}
    assert member.id not in member_ids


@pytest.mark.integration
async def test_cannot_remove_last_manager(client: AsyncClient, session: AsyncSession):
    """Test that removing the last manager fails."""
    from tests.factories import create_initiative, create_project

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
    assert "manager" in response.json()["detail"].lower()


@pytest.mark.integration
async def test_cannot_demote_last_manager(client: AsyncClient, session: AsyncSession):
    """Test that demoting the last manager fails."""
    from tests.factories import create_initiative, create_project

    manager = await create_user(session, email="manager@example.com")
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=manager, guild=guild, role=GuildRole.member
    )

    initiative = await create_initiative(
        session, guild, manager, name="Test Initiative"
    )

    headers = get_guild_headers(guild, manager)
    payload = {"role": "member"}

    response = await client.patch(
        f"/api/v1/initiatives/{initiative.id}/members/{manager.id}",
        headers=headers,
        json=payload,
    )

    assert response.status_code == 400
    assert "manager" in response.json()["detail"].lower()


@pytest.mark.integration
async def test_initiative_guild_isolation(client: AsyncClient, session: AsyncSession):
    """Test that initiatives are isolated by guild."""
    from tests.factories import create_initiative, create_project

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
