"""
Integration tests for project endpoints.

Tests the project API endpoints at /api/v1/projects including:
- Listing projects
- Creating projects
- Updating projects
- Deleting projects
- Archiving/unarchiving
- Managing project permissions
- Favorites and recent views
- Project duplication
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.guild import GuildRole
from app.models.initiative import InitiativeRole
from app.models.project import ProjectPermissionLevel
from tests.factories import (
    create_guild,
    create_guild_membership,
    create_user,
    get_guild_headers,
)


async def _create_initiative_with_member(session, guild, user, role=InitiativeRole.member):
    """Helper to create an initiative with a member."""
    from tests.factories import create_initiative as factory_create_initiative

    initiative = await factory_create_initiative(
        session, guild, user, name="Test Initiative"
    )
    # Factory already adds creator as project_manager
    return initiative


async def _create_project(session, initiative, owner):
    """Helper to create a project."""
    from tests.factories import create_project as factory_create_project

    project = await factory_create_project(
        session, initiative, owner, name="Test Project", description="Test description"
    )
    return project


@pytest.mark.integration
async def test_list_projects_requires_guild_context(
    client: AsyncClient, session: AsyncSession
):
    """Test that listing projects requires guild context."""
    user = await create_user(session)
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild)

    # Request without X-Guild-ID header
    headers = {"Authorization": f"Bearer fake_token_{user.id}"}
    response = await client.get("/api/v1/projects/", headers=headers)

    assert response.status_code == 403


@pytest.mark.integration
async def test_list_projects_as_admin_shows_all(
    client: AsyncClient, session: AsyncSession
):
    """Test that guild admin can see all projects."""
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)

    initiative = await _create_initiative_with_member(session, guild, admin)
    project1 = await _create_project(session, initiative, admin)
    project2 = await _create_project(session, initiative, admin)
    project2.name = "Project 2"
    session.add(project2)
    await session.commit()

    headers = get_guild_headers(guild, admin)
    response = await client.get("/api/v1/projects/", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 2


@pytest.mark.integration
async def test_list_projects_member_sees_initiative_projects(
    client: AsyncClient, session: AsyncSession
):
    """Test that initiative members see projects in their initiative."""
    admin = await create_user(session, email="admin@example.com")
    member = await create_user(session, email="member@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=member, guild=guild)

    initiative = await _create_initiative_with_member(session, guild, admin)

    # Add member to initiative
    from app.models.initiative import InitiativeMember
    session.add(InitiativeMember(
        initiative_id=initiative.id,
        user_id=member.id,
        role=InitiativeRole.member,
    ))
    await session.commit()

    project = await _create_project(session, initiative, admin)

    headers = get_guild_headers(guild, member)
    response = await client.get("/api/v1/projects/", headers=headers)

    assert response.status_code == 200
    data = response.json()
    project_ids = {p["id"] for p in data}
    assert project.id in project_ids


@pytest.mark.integration
async def test_list_projects_excludes_archived_by_default(
    client: AsyncClient, session: AsyncSession
):
    """Test that archived projects are excluded by default."""
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)

    initiative = await _create_initiative_with_member(session, guild, admin)
    project = await _create_project(session, initiative, admin)

    # Archive the project
    project.is_archived = True
    session.add(project)
    await session.commit()

    headers = get_guild_headers(guild, admin)
    response = await client.get("/api/v1/projects/", headers=headers)

    assert response.status_code == 200
    data = response.json()
    project_ids = {p["id"] for p in data}
    assert project.id not in project_ids


@pytest.mark.integration
async def test_list_projects_with_archived_filter(
    client: AsyncClient, session: AsyncSession
):
    """Test listing projects with archived filter."""
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)

    initiative = await _create_initiative_with_member(session, guild, admin)
    project = await _create_project(session, initiative, admin)
    project.is_archived = True
    session.add(project)
    await session.commit()

    headers = get_guild_headers(guild, admin)
    response = await client.get("/api/v1/projects/?archived=true", headers=headers)

    assert response.status_code == 200
    data = response.json()
    project_ids = {p["id"] for p in data}
    assert project.id in project_ids


@pytest.mark.integration
async def test_create_project(client: AsyncClient, session: AsyncSession):
    """Test creating a new project."""
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)

    initiative = await _create_initiative_with_member(session, guild, admin)

    headers = get_guild_headers(guild, admin)
    payload = {
        "name": "New Project",
        "description": "Project description",
        "initiative_id": initiative.id,
    }

    response = await client.post("/api/v1/projects/", headers=headers, json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "New Project"
    assert data["description"] == "Project description"
    assert data["initiative"]["id"] == initiative.id


@pytest.mark.integration
async def test_create_project_as_member(client: AsyncClient, session: AsyncSession):
    """Test that initiative members can create projects."""
    member = await create_user(session, email="member@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=member, guild=guild)

    initiative = await _create_initiative_with_member(
        session, guild, member, role=InitiativeRole.member
    )

    headers = get_guild_headers(guild, member)
    payload = {
        "name": "Member Project",
        "initiative_id": initiative.id,
    }

    response = await client.post("/api/v1/projects/", headers=headers, json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Member Project"


@pytest.mark.integration
async def test_create_project_not_in_initiative_forbidden(
    client: AsyncClient, session: AsyncSession
):
    """Test that users not in initiative cannot create projects."""
    admin = await create_user(session, email="admin@example.com")
    outsider = await create_user(session, email="outsider@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=outsider, guild=guild)

    initiative = await _create_initiative_with_member(session, guild, admin)

    headers = get_guild_headers(guild, outsider)
    payload = {
        "name": "Forbidden Project",
        "initiative_id": initiative.id,
    }

    response = await client.post("/api/v1/projects/", headers=headers, json=payload)

    assert response.status_code == 403


@pytest.mark.integration
async def test_get_project_by_id(client: AsyncClient, session: AsyncSession):
    """Test getting a project by ID."""
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)

    initiative = await _create_initiative_with_member(session, guild, admin)
    project = await _create_project(session, initiative, admin)

    headers = get_guild_headers(guild, admin)
    response = await client.get(f"/api/v1/projects/{project.id}", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == project.id
    assert data["name"] == project.name


@pytest.mark.integration
async def test_get_project_not_found(client: AsyncClient, session: AsyncSession):
    """Test getting non-existent project."""
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)

    headers = get_guild_headers(guild, admin)
    response = await client.get("/api/v1/projects/99999", headers=headers)

    assert response.status_code == 404


@pytest.mark.integration
async def test_update_project_as_owner(client: AsyncClient, session: AsyncSession):
    """Test that project owner can update project."""
    owner = await create_user(session, email="owner@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=owner, guild=guild)

    initiative = await _create_initiative_with_member(session, guild, owner)
    project = await _create_project(session, initiative, owner)

    headers = get_guild_headers(guild, owner)
    payload = {"name": "Updated Name", "description": "Updated description"}

    response = await client.patch(
        f"/api/v1/projects/{project.id}", headers=headers, json=payload
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Name"
    assert data["description"] == "Updated description"


@pytest.mark.integration
async def test_update_project_as_admin(client: AsyncClient, session: AsyncSession):
    """Test that guild admin can update any project."""
    admin = await create_user(session, email="admin@example.com")
    owner = await create_user(session, email="owner@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=owner, guild=guild)

    initiative = await _create_initiative_with_member(session, guild, owner)
    project = await _create_project(session, initiative, owner)

    headers = get_guild_headers(guild, admin)
    payload = {"name": "Admin Updated"}

    response = await client.patch(
        f"/api/v1/projects/{project.id}", headers=headers, json=payload
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Admin Updated"


@pytest.mark.integration
async def test_update_project_without_permission_forbidden(
    client: AsyncClient, session: AsyncSession
):
    """Test that users without permission cannot update project."""
    owner = await create_user(session, email="owner@example.com")
    outsider = await create_user(session, email="outsider@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=owner, guild=guild)
    await create_guild_membership(session, user=outsider, guild=guild)

    initiative = await _create_initiative_with_member(session, guild, owner)
    project = await _create_project(session, initiative, owner)

    headers = get_guild_headers(guild, outsider)
    payload = {"name": "Hacked Name"}

    response = await client.patch(
        f"/api/v1/projects/{project.id}", headers=headers, json=payload
    )

    assert response.status_code == 403


@pytest.mark.integration
async def test_delete_project_as_owner(client: AsyncClient, session: AsyncSession):
    """Test that project owner can delete project."""
    owner = await create_user(session, email="owner@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=owner, guild=guild)

    initiative = await _create_initiative_with_member(session, guild, owner)
    project = await _create_project(session, initiative, owner)

    headers = get_guild_headers(guild, owner)
    response = await client.delete(f"/api/v1/projects/{project.id}", headers=headers)

    assert response.status_code == 204


@pytest.mark.integration
async def test_delete_project_as_admin(client: AsyncClient, session: AsyncSession):
    """Test that guild admin can delete any project."""
    admin = await create_user(session, email="admin@example.com")
    owner = await create_user(session, email="owner@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=owner, guild=guild)

    initiative = await _create_initiative_with_member(session, guild, owner)
    project = await _create_project(session, initiative, owner)

    headers = get_guild_headers(guild, admin)
    response = await client.delete(f"/api/v1/projects/{project.id}", headers=headers)

    assert response.status_code == 204


@pytest.mark.integration
async def test_delete_project_without_permission_forbidden(
    client: AsyncClient, session: AsyncSession
):
    """Test that users without permission cannot delete project."""
    owner = await create_user(session, email="owner@example.com")
    outsider = await create_user(session, email="outsider@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=owner, guild=guild)
    await create_guild_membership(session, user=outsider, guild=guild)

    initiative = await _create_initiative_with_member(session, guild, owner)
    project = await _create_project(session, initiative, owner)

    headers = get_guild_headers(guild, outsider)
    response = await client.delete(f"/api/v1/projects/{project.id}", headers=headers)

    assert response.status_code == 403


@pytest.mark.integration
async def test_archive_project(client: AsyncClient, session: AsyncSession):
    """Test archiving a project."""
    owner = await create_user(session, email="owner@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=owner, guild=guild)

    initiative = await _create_initiative_with_member(session, guild, owner)
    project = await _create_project(session, initiative, owner)

    headers = get_guild_headers(guild, owner)
    response = await client.post(f"/api/v1/projects/{project.id}/archive", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert data["is_archived"] is True


@pytest.mark.integration
async def test_unarchive_project(client: AsyncClient, session: AsyncSession):
    """Test unarchiving a project."""
    owner = await create_user(session, email="owner@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=owner, guild=guild)

    initiative = await _create_initiative_with_member(session, guild, owner)
    project = await _create_project(session, initiative, owner)
    project.is_archived = True
    session.add(project)
    await session.commit()

    headers = get_guild_headers(guild, owner)
    response = await client.post(f"/api/v1/projects/{project.id}/unarchive", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert data["is_archived"] is False


@pytest.mark.integration
async def test_add_project_favorite(client: AsyncClient, session: AsyncSession):
    """Test adding a project to favorites."""
    user = await create_user(session, email="user@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild)

    initiative = await _create_initiative_with_member(session, guild, user)
    project = await _create_project(session, initiative, user)

    headers = get_guild_headers(guild, user)
    response = await client.post(f"/api/v1/projects/{project.id}/favorite", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert data["is_favorited"] is True


@pytest.mark.integration
async def test_remove_project_favorite(client: AsyncClient, session: AsyncSession):
    """Test removing a project from favorites."""
    from app.models.project_activity import ProjectFavorite

    user = await create_user(session, email="user@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild)

    initiative = await _create_initiative_with_member(session, guild, user)
    project = await _create_project(session, initiative, user)

    # Add to favorites first
    favorite = ProjectFavorite(user_id=user.id, project_id=project.id)
    session.add(favorite)
    await session.commit()

    headers = get_guild_headers(guild, user)
    response = await client.delete(f"/api/v1/projects/{project.id}/favorite", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert data["is_favorited"] is False


@pytest.mark.integration
async def test_list_favorite_projects(client: AsyncClient, session: AsyncSession):
    """Test listing favorite projects."""
    from app.models.project_activity import ProjectFavorite

    user = await create_user(session, email="user@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild)

    initiative = await _create_initiative_with_member(session, guild, user)
    project = await _create_project(session, initiative, user)

    # Add to favorites
    favorite = ProjectFavorite(user_id=user.id, project_id=project.id)
    session.add(favorite)
    await session.commit()

    headers = get_guild_headers(guild, user)
    response = await client.get("/api/v1/projects/favorites", headers=headers)

    assert response.status_code == 200
    data = response.json()
    project_ids = {p["id"] for p in data}
    assert project.id in project_ids


@pytest.mark.integration
async def test_mark_project_as_viewed(client: AsyncClient, session: AsyncSession):
    """Test marking a project as recently viewed."""
    user = await create_user(session, email="user@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild)

    initiative = await _create_initiative_with_member(session, guild, user)
    project = await _create_project(session, initiative, user)

    headers = get_guild_headers(guild, user)
    response = await client.post(f"/api/v1/projects/{project.id}/view", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert data["project_id"] == project.id


@pytest.mark.integration
async def test_list_recent_projects(client: AsyncClient, session: AsyncSession):
    """Test listing recently viewed projects."""
    from app.models.project_activity import RecentProjectView
    from datetime import datetime, timezone

    user = await create_user(session, email="user@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild)

    initiative = await _create_initiative_with_member(session, guild, user)
    project = await _create_project(session, initiative, user)

    # Mark as viewed
    view = RecentProjectView(
        user_id=user.id,
        project_id=project.id,
        viewed_at=datetime.now(timezone.utc),
    )
    session.add(view)
    await session.commit()

    headers = get_guild_headers(guild, user)
    response = await client.get("/api/v1/projects/recent", headers=headers)

    assert response.status_code == 200
    data = response.json()
    project_ids = {p["id"] for p in data}
    assert project.id in project_ids


@pytest.mark.integration
async def test_add_project_member(client: AsyncClient, session: AsyncSession):
    """Test adding a member to a project."""
    owner = await create_user(session, email="owner@example.com")
    new_member = await create_user(session, email="member@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=owner, guild=guild)
    await create_guild_membership(session, user=new_member, guild=guild)

    initiative = await _create_initiative_with_member(session, guild, owner)

    # Add new_member to initiative
    from app.models.initiative import InitiativeMember
    session.add(InitiativeMember(
        initiative_id=initiative.id,
        user_id=new_member.id,
        role=InitiativeRole.member,
    ))
    await session.commit()

    project = await _create_project(session, initiative, owner)

    headers = get_guild_headers(guild, owner)
    payload = {"user_id": new_member.id, "level": "write"}

    response = await client.post(
        f"/api/v1/projects/{project.id}/members", headers=headers, json=payload
    )

    assert response.status_code == 201
    data = response.json()
    assert data["user_id"] == new_member.id
    assert data["level"] == "write"


@pytest.mark.integration
async def test_remove_project_member(client: AsyncClient, session: AsyncSession):
    """Test removing a member from a project."""
    from app.models.project import ProjectPermission

    owner = await create_user(session, email="owner@example.com")
    member = await create_user(session, email="member@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=owner, guild=guild)
    await create_guild_membership(session, user=member, guild=guild)

    initiative = await _create_initiative_with_member(session, guild, owner)
    project = await _create_project(session, initiative, owner)

    # Add member permission
    permission = ProjectPermission(
        project_id=project.id,
        user_id=member.id,
        level=ProjectPermissionLevel.write,
    )
    session.add(permission)
    await session.commit()

    headers = get_guild_headers(guild, owner)
    response = await client.delete(
        f"/api/v1/projects/{project.id}/members/{member.id}", headers=headers
    )

    assert response.status_code == 204


@pytest.mark.integration
async def test_project_guild_isolation(client: AsyncClient, session: AsyncSession):
    """Test that projects are isolated by guild."""
    user = await create_user(session, email="user@example.com")
    guild1 = await create_guild(session, name="Guild 1")
    guild2 = await create_guild(session, name="Guild 2")
    await create_guild_membership(session, user=user, guild=guild1, role=GuildRole.admin)
    await create_guild_membership(session, user=user, guild=guild2, role=GuildRole.admin)

    initiative1 = await _create_initiative_with_member(session, guild1, user)
    initiative2 = await _create_initiative_with_member(session, guild2, user)

    project1 = await _create_project(session, initiative1, user)
    await _create_project(session, initiative2, user)

    # Request with guild1 context
    headers1 = get_guild_headers(guild1, user)
    response1 = await client.get("/api/v1/projects/", headers=headers1)

    assert response1.status_code == 200
    data1 = response1.json()
    project_ids1 = {p["id"] for p in data1}
    assert project1.id in project_ids1

    # Cannot access guild1 project with guild2 context
    headers2 = get_guild_headers(guild2, user)
    response2 = await client.get(f"/api/v1/projects/{project1.id}", headers=headers2)

    assert response2.status_code == 404
