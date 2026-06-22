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
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.guild import GuildRole
from app.models.resource_grant import ResourceAccessLevel, ResourceGrant
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_user,
    get_guild_headers,
)


async def _create_initiative_with_member(session, guild, user):
    """Helper to create an initiative and add the user as project manager."""
    from app.testing.factories import create_initiative as factory_create_initiative

    initiative = await factory_create_initiative(
        session, guild, user, name="Test Initiative"
    )
    # Factory already adds creator as project_manager
    return initiative


async def _create_project(session, initiative, owner):
    """Helper to create a project."""
    from app.testing.factories import create_project as factory_create_project

    project = await factory_create_project(
        session, initiative, owner, name="Test Project", description="Test description"
    )
    return project


@pytest.mark.integration
async def test_list_projects_as_admin_shows_all(
    client: AsyncClient, session: AsyncSession
):
    """Test that guild admin can see all projects."""
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )

    initiative = await _create_initiative_with_member(session, guild, admin)
    await _create_project(session, initiative, admin)
    project2 = await _create_project(session, initiative, admin)
    project2.name = "Project 2"
    session.add(project2)
    await session.commit()

    headers = await get_guild_headers(session, guild, admin)
    response = await client.get(f"/api/v1/g/{guild.id}/projects/", headers=headers)

    assert response.status_code == 200
    body = response.json()
    data = body["items"]
    assert len(data) >= 2
    assert body["page"] == 1
    assert body["page_size"] == 0
    assert body["has_next"] is False
    assert body["total_count"] >= 2


@pytest.mark.integration
async def test_list_projects_member_sees_initiative_projects(
    client: AsyncClient, session: AsyncSession
):
    """Test that initiative members see projects in their initiative."""
    admin = await create_user(session, email="admin@example.com")
    member = await create_user(session, email="member@example.com")
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    await create_guild_membership(session, user=member, guild=guild)

    initiative = await _create_initiative_with_member(session, guild, admin)

    # Add member to initiative
    from app.testing.factories import create_initiative_member

    await create_initiative_member(session, initiative, member, role_name="member")

    project = await _create_project(session, initiative, admin)

    # Give member read access to the project (pure DAC requires explicit permission)
    member_permission = ResourceGrant(
        resource_type="project",
        resource_id=project.id,
        user_id=member.id,
        level=ResourceAccessLevel.read,
        guild_id=project.guild_id,
        initiative_id=project.initiative_id,
    )
    session.add(member_permission)
    await session.commit()

    headers = await get_guild_headers(session, guild, member)
    response = await client.get(f"/api/v1/g/{guild.id}/projects/", headers=headers)

    assert response.status_code == 200
    data = response.json()["items"]
    project_ids = {p["id"] for p in data}
    assert project.id in project_ids


@pytest.mark.integration
async def test_list_projects_excludes_archived_by_default(
    client: AsyncClient, session: AsyncSession
):
    """Test that archived projects are excluded by default."""
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )

    initiative = await _create_initiative_with_member(session, guild, admin)
    project = await _create_project(session, initiative, admin)

    # Archive the project
    project.is_archived = True
    session.add(project)
    await session.commit()

    headers = await get_guild_headers(session, guild, admin)
    response = await client.get(f"/api/v1/g/{guild.id}/projects/", headers=headers)

    assert response.status_code == 200
    data = response.json()["items"]
    project_ids = {p["id"] for p in data}
    assert project.id not in project_ids


@pytest.mark.integration
async def test_list_projects_with_archived_filter(
    client: AsyncClient, session: AsyncSession
):
    """Test listing projects with archived filter."""
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )

    initiative = await _create_initiative_with_member(session, guild, admin)
    project = await _create_project(session, initiative, admin)
    project.is_archived = True
    session.add(project)
    await session.commit()

    headers = await get_guild_headers(session, guild, admin)
    response = await client.get(
        f"/api/v1/g/{guild.id}/projects/?archived=true", headers=headers
    )

    assert response.status_code == 200
    data = response.json()["items"]
    project_ids = {p["id"] for p in data}
    assert project.id in project_ids


@pytest.mark.integration
async def test_create_project(client: AsyncClient, session: AsyncSession):
    """Test creating a new project."""
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )

    initiative = await _create_initiative_with_member(session, guild, admin)

    headers = await get_guild_headers(session, guild, admin)
    payload = {
        "name": "New Project",
        "description": "Project description",
        "initiative_id": initiative.id,
    }

    response = await client.post(
        f"/api/v1/g/{guild.id}/projects/", headers=headers, json=payload
    )

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

    initiative = await _create_initiative_with_member(session, guild, member)

    headers = await get_guild_headers(session, guild, member)
    payload = {
        "name": "Member Project",
        "initiative_id": initiative.id,
    }

    response = await client.post(
        f"/api/v1/g/{guild.id}/projects/", headers=headers, json=payload
    )

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
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    await create_guild_membership(session, user=outsider, guild=guild)

    initiative = await _create_initiative_with_member(session, guild, admin)

    headers = await get_guild_headers(session, guild, outsider)
    payload = {
        "name": "Forbidden Project",
        "initiative_id": initiative.id,
    }

    response = await client.post(
        f"/api/v1/g/{guild.id}/projects/", headers=headers, json=payload
    )

    assert response.status_code == 403


@pytest.mark.integration
async def test_get_project_by_id(client: AsyncClient, session: AsyncSession):
    """Test getting a project by ID."""
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )

    initiative = await _create_initiative_with_member(session, guild, admin)
    project = await _create_project(session, initiative, admin)

    headers = await get_guild_headers(session, guild, admin)
    response = await client.get(
        f"/api/v1/g/{guild.id}/projects/{project.id}", headers=headers
    )

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == project.id
    assert data["name"] == project.name


@pytest.mark.integration
async def test_get_project_not_found(client: AsyncClient, session: AsyncSession):
    """Test getting non-existent project."""
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )

    headers = await get_guild_headers(session, guild, admin)
    response = await client.get(f"/api/v1/g/{guild.id}/projects/99999", headers=headers)

    assert response.status_code == 404


@pytest.mark.integration
async def test_update_project_as_owner(client: AsyncClient, session: AsyncSession):
    """Test that project owner can update project."""
    owner = await create_user(session, email="owner@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=owner, guild=guild)

    initiative = await _create_initiative_with_member(session, guild, owner)
    project = await _create_project(session, initiative, owner)

    headers = await get_guild_headers(session, guild, owner)
    payload = {"name": "Updated Name", "description": "Updated description"}

    response = await client.patch(
        f"/api/v1/g/{guild.id}/projects/{project.id}", headers=headers, json=payload
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
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    await create_guild_membership(session, user=owner, guild=guild)

    initiative = await _create_initiative_with_member(session, guild, owner)
    project = await _create_project(session, initiative, owner)

    # Give admin write access to the project (pure DAC requires explicit permission)
    admin_permission = ResourceGrant(
        resource_type="project",
        resource_id=project.id,
        user_id=admin.id,
        level=ResourceAccessLevel.owner,
        guild_id=project.guild_id,
        initiative_id=project.initiative_id,
    )
    session.add(admin_permission)
    await session.commit()

    headers = await get_guild_headers(session, guild, admin)
    payload = {"name": "Admin Updated"}

    response = await client.patch(
        f"/api/v1/g/{guild.id}/projects/{project.id}", headers=headers, json=payload
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

    headers = await get_guild_headers(session, guild, outsider)
    payload = {"name": "Hacked Name"}

    response = await client.patch(
        f"/api/v1/g/{guild.id}/projects/{project.id}", headers=headers, json=payload
    )

    assert (
        response.status_code == 404
    )  # RLS hides the content resource from a non-initiative-member (404, not 403)


@pytest.mark.integration
async def test_delete_project_as_owner(client: AsyncClient, session: AsyncSession):
    """Test that project owner can delete project."""
    owner = await create_user(session, email="owner@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=owner, guild=guild)

    initiative = await _create_initiative_with_member(session, guild, owner)
    project = await _create_project(session, initiative, owner)

    headers = await get_guild_headers(session, guild, owner)
    response = await client.delete(
        f"/api/v1/g/{guild.id}/projects/{project.id}", headers=headers
    )

    assert response.status_code == 204


@pytest.mark.integration
async def test_delete_project_as_admin(client: AsyncClient, session: AsyncSession):
    """Test that guild admin can delete any project."""
    admin = await create_user(session, email="admin@example.com")
    owner = await create_user(session, email="owner@example.com")
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    await create_guild_membership(session, user=owner, guild=guild)

    initiative = await _create_initiative_with_member(session, guild, owner)
    project = await _create_project(session, initiative, owner)

    # Give admin owner access to the project (pure DAC requires explicit permission)
    admin_permission = ResourceGrant(
        resource_type="project",
        resource_id=project.id,
        user_id=admin.id,
        level=ResourceAccessLevel.owner,
        guild_id=project.guild_id,
        initiative_id=project.initiative_id,
    )
    session.add(admin_permission)
    await session.commit()

    headers = await get_guild_headers(session, guild, admin)
    response = await client.delete(
        f"/api/v1/g/{guild.id}/projects/{project.id}", headers=headers
    )

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

    headers = await get_guild_headers(session, guild, outsider)
    response = await client.delete(
        f"/api/v1/g/{guild.id}/projects/{project.id}", headers=headers
    )

    assert (
        response.status_code == 404
    )  # RLS hides the content resource from a non-initiative-member (404, not 403)


@pytest.mark.integration
async def test_archive_project(client: AsyncClient, session: AsyncSession):
    """Test archiving a project."""
    owner = await create_user(session, email="owner@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=owner, guild=guild)

    initiative = await _create_initiative_with_member(session, guild, owner)
    project = await _create_project(session, initiative, owner)

    headers = await get_guild_headers(session, guild, owner)
    response = await client.post(
        f"/api/v1/g/{guild.id}/projects/{project.id}/archive", headers=headers
    )

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

    headers = await get_guild_headers(session, guild, owner)
    response = await client.post(
        f"/api/v1/g/{guild.id}/projects/{project.id}/unarchive", headers=headers
    )

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

    headers = await get_guild_headers(session, guild, user)
    response = await client.post(
        f"/api/v1/g/{guild.id}/projects/{project.id}/favorite", headers=headers
    )

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

    headers = await get_guild_headers(session, guild, user)
    response = await client.delete(
        f"/api/v1/g/{guild.id}/projects/{project.id}/favorite", headers=headers
    )

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

    headers = await get_guild_headers(session, guild, user)
    response = await client.get(
        f"/api/v1/g/{guild.id}/projects/favorites", headers=headers
    )

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

    headers = await get_guild_headers(session, guild, user)
    response = await client.post(
        f"/api/v1/g/{guild.id}/projects/{project.id}/view", headers=headers
    )

    assert response.status_code == 200
    data = response.json()
    assert data["entity_type"] == "project"
    assert data["entity_id"] == project.id
    assert "last_viewed_at" in data


@pytest.mark.integration
async def test_set_project_access_grants_user(
    client: AsyncClient, session: AsyncSession
):
    """PUT /access grants an individual user (Restrict-by-user)."""
    owner = await create_user(session, email="owner@example.com")
    new_member = await create_user(session, email="member@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=owner, guild=guild)
    await create_guild_membership(session, user=new_member, guild=guild)

    initiative = await _create_initiative_with_member(session, guild, owner)
    from app.testing.factories import create_initiative_member

    await create_initiative_member(session, initiative, new_member, role_name="member")
    project = await _create_project(session, initiative, owner)

    headers = await get_guild_headers(session, guild, owner)
    response = await client.put(
        f"/api/v1/g/{guild.id}/projects/{project.id}/grants",
        headers=headers,
        json=[{"user_id": new_member.id, "level": "write"}],
    )

    assert response.status_code == 200
    grants = {
        g["user_id"]: g["level"]
        for g in response.json()["grants"]
        if g["user_id"] is not None
    }
    assert grants.get(new_member.id) == "write"


@pytest.mark.integration
async def test_set_project_access_replaces_grants(
    client: AsyncClient, session: AsyncSession
):
    """PUT /access replaces the full non-owner grant set; the owner is preserved."""
    owner = await create_user(session, email="owner@example.com")
    member = await create_user(session, email="member@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=owner, guild=guild)
    await create_guild_membership(session, user=member, guild=guild)

    initiative = await _create_initiative_with_member(session, guild, owner)
    project = await _create_project(session, initiative, owner)

    session.add(
        ResourceGrant(
            resource_type="project",
            resource_id=project.id,
            user_id=member.id,
            level=ResourceAccessLevel.write,
            guild_id=project.guild_id,
            initiative_id=project.initiative_id,
        )
    )
    await session.commit()

    headers = await get_guild_headers(session, guild, owner)
    response = await client.put(
        f"/api/v1/g/{guild.id}/projects/{project.id}/grants",
        headers=headers,
        json=[],
    )

    assert response.status_code == 200
    user_ids = {
        g["user_id"] for g in response.json()["grants"] if g["user_id"] is not None
    }
    assert member.id not in user_ids  # grant removed
    assert owner.id in user_ids  # owner preserved


@pytest.mark.integration
async def test_set_project_access_all_members(
    client: AsyncClient, session: AsyncSession
):
    """all_initiative_members grants every member access with no personal grant."""
    owner = await create_user(session, email="owner@example.com")
    member = await create_user(session, email="member@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=owner, guild=guild)
    await create_guild_membership(session, user=member, guild=guild)

    initiative = await _create_initiative_with_member(session, guild, owner)
    from app.testing.factories import create_initiative_member

    await create_initiative_member(session, initiative, member, role_name="member")
    project = await _create_project(session, initiative, owner)

    member_headers = await get_guild_headers(session, guild, member)
    # Restricted: a member with no grant is denied (the row is RLS-visible to a
    # member, so DAC denies with 403 rather than hiding it as 404).
    r = await client.get(
        f"/api/v1/g/{guild.id}/projects/{project.id}", headers=member_headers
    )
    assert r.status_code == 403

    owner_headers = await get_guild_headers(session, guild, owner)
    r = await client.put(
        f"/api/v1/g/{guild.id}/projects/{project.id}/grants",
        headers=owner_headers,
        json=[{"all_initiative_members": True, "level": "read"}],
    )
    assert r.status_code == 200
    assert any(
        g["all_initiative_members"] and g["level"] == "read" for g in r.json()["grants"]
    )

    # Now the member can read it via all-initiative-members access alone.
    r = await client.get(
        f"/api/v1/g/{guild.id}/projects/{project.id}", headers=member_headers
    )
    assert r.status_code == 200
    assert r.json()["my_permission_level"] == "read"


async def _task_assignee_ids(session, guild_id: int, task_id: int) -> set[int]:
    """Read task_assignees straight from the guild schema (superuser session)."""
    await session.commit()
    await session.execute(text(f'SET search_path TO "guild_{guild_id}", public'))
    return set(
        (
            await session.execute(
                text("SELECT user_id FROM task_assignees WHERE task_id = :tid"),
                {"tid": task_id},
            )
        ).scalars()
    )


@pytest.mark.integration
async def test_set_project_grants_unassigns_demoted_user(
    client: AsyncClient, session: AsyncSession
):
    """A user dropped below write by a grant change is unassigned from the
    project's tasks (you can't be assigned to tasks you can't edit)."""
    owner = await create_user(session, email="owner@example.com")
    member = await create_user(session, email="member@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=owner, guild=guild)
    await create_guild_membership(session, user=member, guild=guild)

    initiative = await _create_initiative_with_member(session, guild, owner)
    from app.testing.factories import create_initiative_member, create_task

    await create_initiative_member(session, initiative, member, role_name="member")
    project = await _create_project(session, initiative, owner)

    owner_headers = await get_guild_headers(session, guild, owner)
    # Grant the member write, then assign them to a task.
    r = await client.put(
        f"/api/v1/g/{guild.id}/projects/{project.id}/grants",
        headers=owner_headers,
        json=[{"user_id": member.id, "level": "write"}],
    )
    assert r.status_code == 200
    task = await create_task(session, project, assignees=[member])
    assert member.id in await _task_assignee_ids(session, guild.id, task.id)

    # Remove the member's grant entirely -> they lose write -> get unassigned.
    r = await client.put(
        f"/api/v1/g/{guild.id}/projects/{project.id}/grants",
        headers=owner_headers,
        json=[],
    )
    assert r.status_code == 200
    assert member.id not in await _task_assignee_ids(session, guild.id, task.id)


@pytest.mark.integration
async def test_set_project_grants_keeps_assignment_when_still_writable(
    client: AsyncClient, session: AsyncSession
):
    """A user who keeps write via another grant (all-members write) stays assigned —
    the cleanup is effective-access based, not a blunt per-user wipe."""
    owner = await create_user(session, email="owner@example.com")
    member = await create_user(session, email="member@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=owner, guild=guild)
    await create_guild_membership(session, user=member, guild=guild)

    initiative = await _create_initiative_with_member(session, guild, owner)
    from app.testing.factories import create_initiative_member, create_task

    await create_initiative_member(session, initiative, member, role_name="member")
    project = await _create_project(session, initiative, owner)

    owner_headers = await get_guild_headers(session, guild, owner)
    r = await client.put(
        f"/api/v1/g/{guild.id}/projects/{project.id}/grants",
        headers=owner_headers,
        json=[{"user_id": member.id, "level": "write"}],
    )
    assert r.status_code == 200
    task = await create_task(session, project, assignees=[member])

    # Swap the per-user grant for an all-members WRITE grant: the member still has
    # write, so the assignment must survive.
    r = await client.put(
        f"/api/v1/g/{guild.id}/projects/{project.id}/grants",
        headers=owner_headers,
        json=[{"all_initiative_members": True, "level": "write"}],
    )
    assert r.status_code == 200
    assert member.id in await _task_assignee_ids(session, guild.id, task.id)


@pytest.mark.integration
async def test_project_guild_isolation(client: AsyncClient, session: AsyncSession):
    """Test that projects are isolated by guild."""
    user = await create_user(session, email="user@example.com")
    guild1 = await create_guild(session, name="Guild 1")
    guild2 = await create_guild(session, name="Guild 2")
    await create_guild_membership(
        session, user=user, guild=guild1, role=GuildRole.admin
    )
    await create_guild_membership(
        session, user=user, guild=guild2, role=GuildRole.admin
    )

    from app.testing.factories import create_project as factory_create_project

    initiative1 = await _create_initiative_with_member(session, guild1, user)
    initiative2 = await _create_initiative_with_member(session, guild2, user)

    # Distinct names so the cross-guild check below can tell them apart even when
    # their per-schema ids collide.
    project1 = await factory_create_project(
        session, initiative1, user, name="Guild 1 Project"
    )
    await factory_create_project(session, initiative2, user, name="Guild 2 Project")

    # Request with guild1 context
    headers1 = await get_guild_headers(session, guild1, user)
    response1 = await client.get(f"/api/v1/g/{guild1.id}/projects/", headers=headers1)

    assert response1.status_code == 200
    data1 = response1.json()["items"]
    project_names1 = {p["name"] for p in data1}
    assert "Guild 1 Project" in project_names1
    assert "Guild 2 Project" not in project_names1

    # Cannot access guild1's project with guild2 context. Under schema-per-guild
    # ids are per-schema (not globally unique), so project1.id may collide with a
    # guild2 project — but it must never resolve to guild1's project.
    headers2 = await get_guild_headers(session, guild2, user)
    response2 = await client.get(
        f"/api/v1/g/{guild2.id}/projects/{project1.id}", headers=headers2
    )

    if response2.status_code == 200:
        assert response2.json()["name"] != "Guild 1 Project"
    else:
        assert response2.status_code == 404


@pytest.mark.integration
async def test_create_project_with_user_permissions(
    client: AsyncClient, session: AsyncSession
):
    """Test creating a project with explicit user permissions."""
    from app.testing.factories import create_initiative_member

    admin = await create_user(session, email="admin@example.com")
    member = await create_user(session, email="member@example.com")
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    await create_guild_membership(session, user=member, guild=guild)

    initiative = await _create_initiative_with_member(session, guild, admin)
    await create_initiative_member(session, initiative, member, role_name="member")

    headers = await get_guild_headers(session, guild, admin)
    payload = {
        "name": "Project With Permissions",
        "initiative_id": initiative.id,
        "grants": [
            {"user_id": member.id, "level": "write"},
        ],
    }

    response = await client.post(
        f"/api/v1/g/{guild.id}/projects/", headers=headers, json=payload
    )

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Project With Permissions"
    # Owner grant + explicitly granted member (no all-members grant was sent)
    user_grants = {g["user_id"]: g["level"] for g in data["grants"] if g["user_id"]}
    assert user_grants.get(admin.id) == "owner"
    assert user_grants.get(member.id) == "write"


@pytest.mark.integration
async def test_create_project_with_role_permissions(
    client: AsyncClient, session: AsyncSession
):
    """Test creating a project with role-based permissions."""
    from sqlmodel import select
    from app.models.initiative import InitiativeRoleModel

    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )

    initiative = await _create_initiative_with_member(session, guild, admin)

    # Find the member role
    result = await session.exec(
        select(InitiativeRoleModel).where(
            InitiativeRoleModel.initiative_id == initiative.id,
            InitiativeRoleModel.name == "member",
        )
    )
    member_role = result.one()

    headers = await get_guild_headers(session, guild, admin)
    payload = {
        "name": "Project With Role Perms",
        "initiative_id": initiative.id,
        "grants": [
            {"role_id": member_role.id, "level": "read"},
        ],
    }

    response = await client.post(
        f"/api/v1/g/{guild.id}/projects/", headers=headers, json=payload
    )

    assert response.status_code == 201
    data = response.json()
    role_grants = [g for g in data["grants"] if g["role_id"] is not None]
    assert len(role_grants) == 1
    assert role_grants[0]["role_id"] == member_role.id
    assert role_grants[0]["level"] == "read"


@pytest.mark.integration
async def test_create_project_defaults_to_all_members_viewer(
    client: AsyncClient, session: AsyncSession
):
    """Omitting `grants` defaults to Viewer for all initiative members (+ owner)."""
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )

    initiative = await _create_initiative_with_member(session, guild, admin)

    headers = await get_guild_headers(session, guild, admin)
    payload = {
        "name": "Project Default Share",
        "initiative_id": initiative.id,
    }

    response = await client.post(
        f"/api/v1/g/{guild.id}/projects/", headers=headers, json=payload
    )

    assert response.status_code == 201
    data = response.json()
    # Owner grant + an all-initiative-members Viewer (read) grant.
    assert any(
        g["user_id"] == admin.id and g["level"] == "owner" for g in data["grants"]
    )
    assert any(
        g["all_initiative_members"] and g["level"] == "read" for g in data["grants"]
    )
    assert data["my_permission_level"] == "owner"


@pytest.mark.integration
async def test_create_project_skips_owner_level_grants(
    client: AsyncClient, session: AsyncSession
):
    """Test that owner-level grants in user_permissions are silently ignored."""
    from app.testing.factories import create_initiative_member

    admin = await create_user(session, email="admin@example.com")
    member = await create_user(session, email="member@example.com")
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    await create_guild_membership(session, user=member, guild=guild)

    initiative = await _create_initiative_with_member(session, guild, admin)
    await create_initiative_member(session, initiative, member, role_name="member")

    headers = await get_guild_headers(session, guild, admin)
    payload = {
        "name": "Project Owner Skip",
        "initiative_id": initiative.id,
        "grants": [
            {"user_id": member.id, "level": "owner"},
        ],
    }

    response = await client.post(
        f"/api/v1/g/{guild.id}/projects/", headers=headers, json=payload
    )

    assert response.status_code == 201
    data = response.json()
    # Member should NOT have been granted owner
    member_grants = [g for g in data["grants"] if g["user_id"] == member.id]
    assert len(member_grants) == 0


@pytest.mark.integration
async def test_create_project_rejects_foreign_initiative_role(
    client: AsyncClient, session: AsyncSession
):
    """Role from a different initiative must be silently dropped."""
    from sqlmodel import select
    from app.models.initiative import InitiativeRoleModel
    from app.testing.factories import create_initiative

    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )

    initiative_a = await _create_initiative_with_member(session, guild, admin)
    initiative_b = await create_initiative(
        session, guild, admin, name="Other Initiative"
    )

    # Get a role that belongs to initiative_b, not initiative_a
    result = await session.exec(
        select(InitiativeRoleModel).where(
            InitiativeRoleModel.initiative_id == initiative_b.id,
            InitiativeRoleModel.name == "member",
        )
    )
    foreign_role = result.one()

    headers = await get_guild_headers(session, guild, admin)
    payload = {
        "name": "Project Cross Initiative",
        "initiative_id": initiative_a.id,
        "grants": [
            {"role_id": foreign_role.id, "level": "read"},
        ],
    }

    response = await client.post(
        f"/api/v1/g/{guild.id}/projects/", headers=headers, json=payload
    )

    assert response.status_code == 201
    data = response.json()
    # Foreign role must have been silently dropped
    assert len([g for g in data["grants"] if g["role_id"] is not None]) == 0
