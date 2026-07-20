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

from app.models.platform.guild import GuildRole
from app.models.tenant.document import Document, DocumentType, ProjectDocument
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_project,
)


@pytest.mark.integration
async def test_list_projects_as_admin_shows_all(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that guild admin can see all projects."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await create_project(session, admin.initiative, admin.user, name="Test Project")
    project2 = await create_project(
        session, admin.initiative, admin.user, name="Project 2"
    )
    session.add(project2)
    await session.commit()

    response = await client.get(admin.g("/projects/"), headers=admin.headers)

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
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that initiative members see projects in their initiative."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )

    project = await create_project(session, admin.initiative, admin.user)

    # Give member read access to the project (pure DAC requires explicit permission)
    member_permission = ResourceGrant(
        resource_type="project",
        resource_id=project.id,
        user_id=member.user.id,
        level=ResourceAccessLevel.read,
        guild_id=project.guild_id,
        initiative_id=project.initiative_id,
    )
    session.add(member_permission)
    await session.commit()

    response = await client.get(member.g("/projects/"), headers=member.headers)

    assert response.status_code == 200
    data = response.json()["items"]
    project_ids = {p["id"] for p in data}
    assert project.id in project_ids


@pytest.mark.integration
async def test_search_project_members_returns_write_access_set(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The assignable roster is the project's write/owner DAC set: the owner
    and write-granted members, but not read-only members nor members with no
    grant. Returns the slim UserSummary envelope."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    project = await create_project(
        session, admin.initiative, admin.user, name="Assignable Project"
    )

    writer = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
        full_name="Wanda Writer",
    )
    reader = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
        full_name="Rob Reader",
    )
    # A member of the initiative with no grant at all.
    await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
        full_name="Nora None",
    )

    session.add(
        ResourceGrant(
            resource_type="project",
            resource_id=project.id,
            user_id=writer.user.id,
            level=ResourceAccessLevel.write,
            guild_id=project.guild_id,
            initiative_id=project.initiative_id,
        )
    )
    session.add(
        ResourceGrant(
            resource_type="project",
            resource_id=project.id,
            user_id=reader.user.id,
            level=ResourceAccessLevel.read,
            guild_id=project.guild_id,
            initiative_id=project.initiative_id,
        )
    )
    await session.commit()

    response = await client.get(
        admin.g(f"/projects/{project.id}/members/search"), headers=admin.headers
    )

    assert response.status_code == 200
    body = response.json()
    names = {item["full_name"] for item in body["items"]}
    # Owner (admin) + write-granted member are assignable.
    assert admin.user.full_name in names
    assert "Wanda Writer" in names
    # Read-only and no-grant members are not.
    assert "Rob Reader" not in names
    assert "Nora None" not in names
    # Slim projection shape.
    assert set(body["items"][0].keys()) == {
        "id",
        "full_name",
        "avatar_base64",
        "avatar_url",
        "status",
    }

    # Name filter.
    response = await client.get(
        admin.g(f"/projects/{project.id}/members/search"),
        headers=admin.headers,
        params={"search": "wanda"},
    )
    assert response.status_code == 200
    body = response.json()
    assert [item["full_name"] for item in body["items"]] == ["Wanda Writer"]


@pytest.mark.integration
async def test_search_project_members_requires_read_access(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A guild member with no access to the project (not in its initiative)
    cannot read its assignable roster."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    project = await create_project(session, admin.initiative, admin.user)
    outsider = await acting_user(guild_role=GuildRole.member, guild=admin.guild)

    response = await client.get(
        outsider.g(f"/projects/{project.id}/members/search"), headers=outsider.headers
    )
    # RLS hides the initiative's content from a non-member → 404.
    assert response.status_code in (403, 404)


@pytest.mark.integration
async def test_list_projects_excludes_archived_by_default(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that archived projects are excluded by default."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    project = await create_project(session, admin.initiative, admin.user)

    # Archive the project
    project.is_archived = True
    session.add(project)
    await session.commit()

    response = await client.get(admin.g("/projects/"), headers=admin.headers)

    assert response.status_code == 200
    data = response.json()["items"]
    project_ids = {p["id"] for p in data}
    assert project.id not in project_ids


@pytest.mark.integration
async def test_list_projects_with_archived_filter(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test listing projects with archived filter."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    project = await create_project(session, admin.initiative, admin.user)
    project.is_archived = True
    session.add(project)
    await session.commit()

    response = await client.get(
        admin.g("/projects/?archived=true"), headers=admin.headers
    )

    assert response.status_code == 200
    data = response.json()["items"]
    project_ids = {p["id"] for p in data}
    assert project.id in project_ids


@pytest.mark.integration
async def test_list_projects_search_filters_by_name(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The ``search`` param does a case-insensitive substring match on name."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    alpha = await create_project(session, admin.initiative, admin.user, name="Alpha")
    await create_project(session, admin.initiative, admin.user, name="Beta")

    response = await client.get(
        admin.g("/projects/?search=alph"), headers=admin.headers
    )

    assert response.status_code == 200
    data = response.json()["items"]
    names = {p["name"] for p in data}
    assert names == {"Alpha"}
    assert data[0]["id"] == alpha.id


@pytest.mark.integration
async def test_list_projects_paginates_in_sql(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """total_count reflects the full matching set even when a page truncates it."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    for i in range(3):
        await create_project(session, admin.initiative, admin.user, name=f"P{i}")

    response = await client.get(
        admin.g("/projects/?page=1&page_size=2"), headers=admin.headers
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 2
    assert body["total_count"] >= 3
    assert body["has_next"] is True

    page2 = await client.get(
        admin.g("/projects/?page=2&page_size=2"), headers=admin.headers
    )
    assert page2.status_code == 200
    # Pages don't overlap.
    ids_p1 = {p["id"] for p in body["items"]}
    ids_p2 = {p["id"] for p in page2.json()["items"]}
    assert ids_p1.isdisjoint(ids_p2)


@pytest.mark.integration
async def test_list_projects_slim_projection(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """slim=true keeps id/name/initiative/my_permission_level but drops the
    heavy relationships (documents, grants, nested initiative)."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    project = await create_project(
        session, admin.initiative, admin.user, name="Slim One"
    )

    response = await client.get(admin.g("/projects/?slim=true"), headers=admin.headers)

    assert response.status_code == 200
    item = next(p for p in response.json()["items"] if p["id"] == project.id)
    assert item["name"] == "Slim One"
    assert item["initiative_id"] == admin.initiative.id
    # Guild admin resolves to owner-level on every project.
    assert item["my_permission_level"] == "owner"
    # Heavy fields collapse to their empty defaults in slim mode.
    assert item["documents"] == []
    assert item["grants"] == []
    assert item["tags"] == []
    assert item["initiative"] is None


@pytest.mark.integration
async def test_list_projects_slim_permission_for_member(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Slim projection computes my_permission_level from DAC grants, not just
    the guild-admin shortcut."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    project = await create_project(session, admin.initiative, admin.user)
    session.add(
        ResourceGrant(
            resource_type="project",
            resource_id=project.id,
            user_id=member.user.id,
            level=ResourceAccessLevel.write,
            guild_id=project.guild_id,
            initiative_id=project.initiative_id,
        )
    )
    await session.commit()

    response = await client.get(
        member.g("/projects/?slim=true"), headers=member.headers
    )

    assert response.status_code == 200
    item = next(p for p in response.json()["items"] if p["id"] == project.id)
    assert item["my_permission_level"] == "write"


@pytest.mark.integration
async def test_create_project(client: AsyncClient, acting_user):
    """Test creating a new project."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)

    payload = {
        "name": "New Project",
        "description": "Project description",
        "initiative_id": admin.initiative.id,
    }

    response = await client.post(
        admin.g("/projects/"), headers=admin.headers, json=payload
    )

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "New Project"
    assert data["description"] == "Project description"
    assert data["initiative"]["id"] == admin.initiative.id


@pytest.mark.integration
async def test_create_project_as_member(client: AsyncClient, acting_user):
    """Test that initiative members can create projects."""
    member = await acting_user(guild_role=GuildRole.member, initiative=True)

    payload = {
        "name": "Member Project",
        "initiative_id": member.initiative.id,
    }

    response = await client.post(
        member.g("/projects/"), headers=member.headers, json=payload
    )

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Member Project"


@pytest.mark.integration
async def test_create_project_not_in_initiative_forbidden(
    client: AsyncClient, acting_user
):
    """Test that users not in initiative cannot create projects."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    outsider = await acting_user(guild_role=GuildRole.member, guild=admin.guild)

    payload = {
        "name": "Forbidden Project",
        "initiative_id": admin.initiative.id,
    }

    response = await client.post(
        outsider.g("/projects/"), headers=outsider.headers, json=payload
    )

    assert response.status_code == 403


@pytest.mark.integration
async def test_get_project_by_id(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test getting a project by ID."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    project = await create_project(session, admin.initiative, admin.user)

    response = await client.get(
        admin.g(f"/projects/{project.id}"), headers=admin.headers
    )

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == project.id
    assert data["name"] == project.name


@pytest.mark.integration
async def test_get_project_not_found(client: AsyncClient, acting_user):
    """Test getting non-existent project."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)

    response = await client.get(admin.g("/projects/99999"), headers=admin.headers)

    assert response.status_code == 404


@pytest.mark.integration
async def test_update_project_as_owner(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that project owner can update project."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    project = await create_project(session, owner.initiative, owner.user)

    payload = {"name": "Updated Name", "description": "Updated description"}

    response = await client.patch(
        owner.g(f"/projects/{project.id}"), headers=owner.headers, json=payload
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Name"
    assert data["description"] == "Updated description"


@pytest.mark.integration
async def test_update_project_as_admin(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that guild admin can update any project."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    owner = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    project = await create_project(session, admin.initiative, owner.user)

    # Give admin write access to the project (pure DAC requires explicit permission)
    admin_permission = ResourceGrant(
        resource_type="project",
        resource_id=project.id,
        user_id=admin.user.id,
        level=ResourceAccessLevel.owner,
        guild_id=project.guild_id,
        initiative_id=project.initiative_id,
    )
    session.add(admin_permission)
    await session.commit()

    payload = {"name": "Admin Updated"}

    response = await client.patch(
        admin.g(f"/projects/{project.id}"), headers=admin.headers, json=payload
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Admin Updated"


@pytest.mark.integration
async def test_update_project_without_permission_forbidden(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that users without permission cannot update project."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    outsider = await acting_user(guild_role=GuildRole.member, guild=owner.guild)
    project = await create_project(session, owner.initiative, owner.user)

    payload = {"name": "Hacked Name"}

    response = await client.patch(
        outsider.g(f"/projects/{project.id}"), headers=outsider.headers, json=payload
    )

    assert (
        response.status_code == 404
    )  # RLS hides the content resource from a non-initiative-member (404, not 403)


@pytest.mark.integration
async def test_delete_project_as_owner(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that project owner can delete project."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    project = await create_project(session, owner.initiative, owner.user)

    response = await client.delete(
        owner.g(f"/projects/{project.id}"), headers=owner.headers
    )

    assert response.status_code == 204


@pytest.mark.integration
async def test_delete_project_as_admin(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that guild admin can delete any project."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    owner = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    project = await create_project(session, admin.initiative, owner.user)

    # Give admin owner access to the project (pure DAC requires explicit permission)
    admin_permission = ResourceGrant(
        resource_type="project",
        resource_id=project.id,
        user_id=admin.user.id,
        level=ResourceAccessLevel.owner,
        guild_id=project.guild_id,
        initiative_id=project.initiative_id,
    )
    session.add(admin_permission)
    await session.commit()

    response = await client.delete(
        admin.g(f"/projects/{project.id}"), headers=admin.headers
    )

    assert response.status_code == 204


@pytest.mark.integration
async def test_delete_project_without_permission_forbidden(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that users without permission cannot delete project."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    outsider = await acting_user(guild_role=GuildRole.member, guild=owner.guild)
    project = await create_project(session, owner.initiative, owner.user)

    response = await client.delete(
        outsider.g(f"/projects/{project.id}"), headers=outsider.headers
    )

    assert (
        response.status_code == 404
    )  # RLS hides the content resource from a non-initiative-member (404, not 403)


@pytest.mark.integration
async def test_archive_project(client: AsyncClient, session: AsyncSession, acting_user):
    """Test archiving a project."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    project = await create_project(session, owner.initiative, owner.user)

    response = await client.post(
        owner.g(f"/projects/{project.id}/archive"), headers=owner.headers
    )

    assert response.status_code == 200
    data = response.json()
    assert data["is_archived"] is True


@pytest.mark.integration
async def test_unarchive_project(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test unarchiving a project."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    project = await create_project(session, owner.initiative, owner.user)
    project.is_archived = True
    session.add(project)
    await session.commit()

    response = await client.post(
        owner.g(f"/projects/{project.id}/unarchive"), headers=owner.headers
    )

    assert response.status_code == 200
    data = response.json()
    assert data["is_archived"] is False


@pytest.mark.integration
async def test_add_project_favorite(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test adding a project to favorites."""
    user = await acting_user(guild_role=GuildRole.member, initiative=True)
    project = await create_project(session, user.initiative, user.user)

    response = await client.post(
        user.g(f"/projects/{project.id}/favorite"), headers=user.headers
    )

    assert response.status_code == 200
    data = response.json()
    assert data["is_favorited"] is True


@pytest.mark.integration
async def test_remove_project_favorite(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test removing a project from favorites."""
    from app.models.tenant.project_activity import ProjectFavorite

    user = await acting_user(guild_role=GuildRole.member, initiative=True)
    project = await create_project(session, user.initiative, user.user)

    # Add to favorites first
    favorite = ProjectFavorite(user_id=user.user.id, project_id=project.id)
    session.add(favorite)
    await session.commit()

    response = await client.delete(
        user.g(f"/projects/{project.id}/favorite"), headers=user.headers
    )

    assert response.status_code == 200
    data = response.json()
    assert data["is_favorited"] is False


@pytest.mark.integration
async def test_list_favorite_projects(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test listing favorite projects."""
    from app.models.tenant.project_activity import ProjectFavorite

    user = await acting_user(guild_role=GuildRole.member, initiative=True)
    project = await create_project(session, user.initiative, user.user)

    # Add to favorites
    favorite = ProjectFavorite(user_id=user.user.id, project_id=project.id)
    session.add(favorite)
    await session.commit()

    response = await client.get(user.g("/projects/favorites"), headers=user.headers)

    assert response.status_code == 200
    data = response.json()
    project_ids = {p["id"] for p in data}
    assert project.id in project_ids


@pytest.mark.integration
async def test_mark_project_as_viewed(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test marking a project as recently viewed."""
    user = await acting_user(guild_role=GuildRole.member, initiative=True)
    project = await create_project(session, user.initiative, user.user)

    response = await client.post(
        user.g(f"/projects/{project.id}/view"), headers=user.headers
    )

    assert response.status_code == 200
    data = response.json()
    assert data["entity_type"] == "project"
    assert data["entity_id"] == project.id
    assert "last_viewed_at" in data


@pytest.mark.integration
async def test_set_project_access_grants_user(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """PUT /access grants an individual user (Restrict-by-user)."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    new_member = await acting_user(
        guild_role=GuildRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    project = await create_project(session, owner.initiative, owner.user)

    response = await client.put(
        owner.g(f"/projects/{project.id}/grants"),
        headers=owner.headers,
        json=[{"user_id": new_member.user.id, "level": "write"}],
    )

    assert response.status_code == 200
    grants = {
        g["user_id"]: g["level"]
        for g in response.json()["grants"]
        if g["user_id"] is not None
    }
    assert grants.get(new_member.user.id) == "write"


@pytest.mark.integration
async def test_set_project_access_replaces_grants(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """PUT /access replaces the full non-owner grant set; the owner is preserved."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    member = await acting_user(guild_role=GuildRole.member, guild=owner.guild)
    project = await create_project(session, owner.initiative, owner.user)

    session.add(
        ResourceGrant(
            resource_type="project",
            resource_id=project.id,
            user_id=member.user.id,
            level=ResourceAccessLevel.write,
            guild_id=project.guild_id,
            initiative_id=project.initiative_id,
        )
    )
    await session.commit()

    response = await client.put(
        owner.g(f"/projects/{project.id}/grants"),
        headers=owner.headers,
        json=[],
    )

    assert response.status_code == 200
    user_ids = {
        g["user_id"] for g in response.json()["grants"] if g["user_id"] is not None
    }
    assert member.user.id not in user_ids  # grant removed
    assert owner.user.id in user_ids  # owner preserved


@pytest.mark.integration
async def test_set_project_access_all_members(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """all_initiative_members grants every member access with no personal grant."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    project = await create_project(session, owner.initiative, owner.user)

    # Restricted: a member with no grant is denied (the row is RLS-visible to a
    # member, so DAC denies with 403 rather than hiding it as 404).
    r = await client.get(member.g(f"/projects/{project.id}"), headers=member.headers)
    assert r.status_code == 403

    r = await client.put(
        owner.g(f"/projects/{project.id}/grants"),
        headers=owner.headers,
        json=[{"all_initiative_members": True, "level": "read"}],
    )
    assert r.status_code == 200
    assert any(
        g["all_initiative_members"] and g["level"] == "read" for g in r.json()["grants"]
    )

    # Now the member can read it via all-initiative-members access alone.
    r = await client.get(member.g(f"/projects/{project.id}"), headers=member.headers)
    assert r.status_code == 200
    assert r.json()["my_permission_level"] == "read"


async def _task_assignee_ids(session, guild_id: int, task_id: int) -> set[int]:
    """Read task_assignees straight from the guild schema (superuser session)."""
    await session.commit()
    await session.exec(text(f'SET search_path TO "guild_{guild_id}", public'))
    return set(
        (
            await session.exec(
                text("SELECT user_id FROM task_assignees WHERE task_id = :tid"),
                params={"tid": task_id},
            )
        ).scalars()
    )


@pytest.mark.integration
async def test_set_project_grants_unassigns_demoted_user(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A user dropped below write by a grant change is unassigned from the
    project's tasks (you can't be assigned to tasks you can't edit)."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    from app.testing.factories import create_task

    project = await create_project(session, owner.initiative, owner.user)

    # Grant the member write, then assign them to a task.
    r = await client.put(
        owner.g(f"/projects/{project.id}/grants"),
        headers=owner.headers,
        json=[{"user_id": member.user.id, "level": "write"}],
    )
    assert r.status_code == 200
    task = await create_task(session, project, assignees=[member.user])
    assert member.user.id in await _task_assignee_ids(session, owner.guild.id, task.id)

    # Remove the member's grant entirely -> they lose write -> get unassigned.
    r = await client.put(
        owner.g(f"/projects/{project.id}/grants"),
        headers=owner.headers,
        json=[],
    )
    assert r.status_code == 200
    assert member.user.id not in await _task_assignee_ids(
        session, owner.guild.id, task.id
    )


@pytest.mark.integration
async def test_set_project_grants_keeps_assignment_when_still_writable(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A user who keeps write via another grant (all-members write) stays assigned —
    the cleanup is effective-access based, not a blunt per-user wipe."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    from app.testing.factories import create_task

    project = await create_project(session, owner.initiative, owner.user)

    r = await client.put(
        owner.g(f"/projects/{project.id}/grants"),
        headers=owner.headers,
        json=[{"user_id": member.user.id, "level": "write"}],
    )
    assert r.status_code == 200
    task = await create_task(session, project, assignees=[member.user])

    # Swap the per-user grant for an all-members WRITE grant: the member still has
    # write, so the assignment must survive.
    r = await client.put(
        owner.g(f"/projects/{project.id}/grants"),
        headers=owner.headers,
        json=[{"all_initiative_members": True, "level": "write"}],
    )
    assert r.status_code == 200
    assert member.user.id in await _task_assignee_ids(session, owner.guild.id, task.id)


@pytest.mark.integration
async def test_project_guild_isolation(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that projects are isolated by guild."""
    # Same user is a guild admin in two separate guilds/initiatives.
    a1 = await acting_user(
        guild_role=GuildRole.admin, initiative=True, email="user@example.com"
    )
    user = a1.user
    initiative1 = a1.initiative

    guild2 = await create_guild(session, name="Guild 2")
    await create_guild_membership(
        session, user=user, guild=guild2, role=GuildRole.admin
    )
    initiative2 = await create_initiative(session, guild2, user)

    # Distinct names so the cross-guild check below can tell them apart even when
    # their per-schema ids collide.
    project1 = await create_project(session, initiative1, user, name="Guild 1 Project")
    await create_project(session, initiative2, user, name="Guild 2 Project")

    # Request with guild1 context
    response1 = await client.get(a1.g("/projects/"), headers=a1.headers)

    assert response1.status_code == 200
    data1 = response1.json()["items"]
    project_names1 = {p["name"] for p in data1}
    assert "Guild 1 Project" in project_names1
    assert "Guild 2 Project" not in project_names1

    # Cannot access guild1's project with guild2 context. Under schema-per-guild
    # ids are per-schema (not globally unique), so project1.id may collide with a
    # guild2 project — but it must never resolve to guild1's project.
    response2 = await client.get(
        f"/api/v1/g/{guild2.id}/projects/{project1.id}", headers=a1.headers
    )

    if response2.status_code == 200:
        assert response2.json()["name"] != "Guild 1 Project"
    else:
        assert response2.status_code == 404


@pytest.mark.integration
async def test_create_project_with_user_permissions(client: AsyncClient, acting_user):
    """Test creating a project with explicit user permissions."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )

    payload = {
        "name": "Project With Permissions",
        "initiative_id": admin.initiative.id,
        "grants": [
            {"user_id": member.user.id, "level": "write"},
        ],
    }

    response = await client.post(
        admin.g("/projects/"), headers=admin.headers, json=payload
    )

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Project With Permissions"
    # Owner grant + explicitly granted member (no all-members grant was sent)
    user_grants = {g["user_id"]: g["level"] for g in data["grants"] if g["user_id"]}
    assert user_grants.get(admin.user.id) == "owner"
    assert user_grants.get(member.user.id) == "write"


@pytest.mark.integration
async def test_create_project_with_role_permissions(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test creating a project with role-based permissions."""
    from sqlmodel import select
    from app.models.tenant.initiative import InitiativeRoleModel

    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)

    # Find the member role
    result = await session.exec(
        select(InitiativeRoleModel).where(
            InitiativeRoleModel.initiative_id == admin.initiative.id,
            InitiativeRoleModel.name == "member",
        )
    )
    member_role = result.one()

    payload = {
        "name": "Project With Role Perms",
        "initiative_id": admin.initiative.id,
        "grants": [
            {"role_id": member_role.id, "level": "read"},
        ],
    }

    response = await client.post(
        admin.g("/projects/"), headers=admin.headers, json=payload
    )

    assert response.status_code == 201
    data = response.json()
    role_grants = [g for g in data["grants"] if g["role_id"] is not None]
    assert len(role_grants) == 1
    assert role_grants[0]["role_id"] == member_role.id
    assert role_grants[0]["level"] == "read"


@pytest.mark.integration
async def test_create_project_defaults_to_all_members_viewer(
    client: AsyncClient, acting_user
):
    """Omitting `grants` defaults to Viewer for all initiative members (+ owner)."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)

    payload = {
        "name": "Project Default Share",
        "initiative_id": admin.initiative.id,
    }

    response = await client.post(
        admin.g("/projects/"), headers=admin.headers, json=payload
    )

    assert response.status_code == 201
    data = response.json()
    # Owner grant + an all-initiative-members Viewer (read) grant.
    assert any(
        g["user_id"] == admin.user.id and g["level"] == "owner" for g in data["grants"]
    )
    assert any(
        g["all_initiative_members"] and g["level"] == "read" for g in data["grants"]
    )
    assert data["my_permission_level"] == "owner"


@pytest.mark.integration
async def test_create_project_skips_owner_level_grants(
    client: AsyncClient, acting_user
):
    """Test that owner-level grants in user_permissions are silently ignored."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )

    payload = {
        "name": "Project Owner Skip",
        "initiative_id": admin.initiative.id,
        "grants": [
            {"user_id": member.user.id, "level": "owner"},
        ],
    }

    response = await client.post(
        admin.g("/projects/"), headers=admin.headers, json=payload
    )

    assert response.status_code == 201
    data = response.json()
    # Member should NOT have been granted owner
    member_grants = [g for g in data["grants"] if g["user_id"] == member.user.id]
    assert len(member_grants) == 0


@pytest.mark.integration
async def test_create_project_rejects_foreign_initiative_role(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Role from a different initiative must be silently dropped."""
    from sqlmodel import select
    from app.models.tenant.initiative import InitiativeRoleModel

    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    initiative_a = admin.initiative
    initiative_b = await create_initiative(
        session, admin.guild, admin.user, name="Other Initiative"
    )

    # Get a role that belongs to initiative_b, not initiative_a
    result = await session.exec(
        select(InitiativeRoleModel).where(
            InitiativeRoleModel.initiative_id == initiative_b.id,
            InitiativeRoleModel.name == "member",
        )
    )
    foreign_role = result.one()

    payload = {
        "name": "Project Cross Initiative",
        "initiative_id": initiative_a.id,
        "grants": [
            {"role_id": foreign_role.id, "level": "read"},
        ],
    }

    response = await client.post(
        admin.g("/projects/"), headers=admin.headers, json=payload
    )

    assert response.status_code == 201
    data = response.json()
    # Foreign role must have been silently dropped
    assert len([g for g in data["grants"] if g["role_id"] is not None]) == 0


@pytest.mark.integration
async def test_set_project_access_change_all_members_level(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Changing an EXISTING all-initiative-members grant's level (read -> write)
    must not trip ``resource_grants_unique_grantee``.

    replace_resource_grants deletes the old grant and inserts the new one; without
    flushing the delete first, SQLAlchemy's unit of work emits the INSERT before
    the DELETE and the new (user_id NULL, role_id NULL) row collides with the old
    one under the UNIQUE NULLS NOT DISTINCT constraint. This is the production 500
    a member hit switching a project's "all initiative members" share from Viewer
    to Editor.
    """
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    project = await create_project(session, owner.initiative, owner.user)
    url = owner.g(f"/projects/{project.id}/grants")

    # 1) create the all-members grant at read (Viewer)
    r = await client.put(
        url,
        headers=owner.headers,
        json=[{"all_initiative_members": True, "level": "read"}],
    )
    assert r.status_code == 200, r.text

    # 2) change it to write (Editor) — the delete-then-reinsert collision path
    r = await client.put(
        url,
        headers=owner.headers,
        json=[{"all_initiative_members": True, "level": "write"}],
    )
    assert r.status_code == 200, r.text
    members = [g for g in r.json()["grants"] if g["all_initiative_members"]]
    assert len(members) == 1  # exactly one all-members grant...
    assert members[0]["level"] == "write"  # ...now at write


@pytest.mark.integration
async def test_set_project_access_remove_grant_keeps_all_members(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Removing a per-user grant while keeping the all-members grant must not trip
    the unique constraint either — replace_resource_grants deletes ALL non-owner
    grants and re-inserts the kept set, so the all-members grant is deleted and
    re-inserted in the same flush. ("I also cannot remove access" — same cause.)
    """
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    project = await create_project(session, owner.initiative, owner.user)
    url = owner.g(f"/projects/{project.id}/grants")

    # all-members read + a per-user write grant
    r = await client.put(
        url,
        headers=owner.headers,
        json=[
            {"all_initiative_members": True, "level": "read"},
            {"user_id": member.user.id, "level": "write"},
        ],
    )
    assert r.status_code == 200, r.text

    # remove the per-user grant, keep all-members
    r = await client.put(
        url,
        headers=owner.headers,
        json=[{"all_initiative_members": True, "level": "read"}],
    )
    assert r.status_code == 200, r.text
    assert [g for g in r.json()["grants"] if g["user_id"] == member.user.id] == []
    assert any(g["all_initiative_members"] for g in r.json()["grants"])


@pytest.mark.integration
async def test_project_shows_all_members_document_to_member(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A document attached to a project and shared with *all initiative members*
    is visible to a plain member on the project view. Regression: the linked-doc
    filter used to ignore all-members grants, so such docs vanished for anyone
    without a personal/role grant."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    guild = owner.guild
    initiative = owner.initiative
    project = await create_project(session, initiative, owner.user)

    doc = Document(
        title="Shared with everyone",
        initiative_id=initiative.id,
        guild_id=guild.id,
        created_by_id=owner.user.id,
        updated_by_id=owner.user.id,
        document_type=DocumentType.native,
    )
    session.add(doc)
    await session.flush()
    session.add_all(
        [
            # Project shared with all members so the member can open it at all.
            ResourceGrant(
                resource_type="project",
                resource_id=project.id,
                all_initiative_members=True,
                level=ResourceAccessLevel.read,
                guild_id=guild.id,
                initiative_id=initiative.id,
            ),
            ResourceGrant(
                resource_type="document",
                resource_id=doc.id,
                user_id=owner.user.id,
                level=ResourceAccessLevel.owner,
                guild_id=guild.id,
                initiative_id=initiative.id,
            ),
            ResourceGrant(
                resource_type="document",
                resource_id=doc.id,
                all_initiative_members=True,
                level=ResourceAccessLevel.read,
                guild_id=guild.id,
                initiative_id=initiative.id,
            ),
            ProjectDocument(
                project_id=project.id,
                document_id=doc.id,
                guild_id=guild.id,
                attached_by_id=owner.user.id,
            ),
        ]
    )
    await session.commit()

    r = await client.get(member.g(f"/projects/{project.id}"), headers=member.headers)
    assert r.status_code == 200, r.text
    doc_ids = [d["document_id"] for d in r.json()["documents"]]
    assert doc.id in doc_ids


@pytest.mark.integration
async def test_project_counts_by_initiative(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Grouped counts mirror the default list: visible, non-archived,
    non-template projects only, with no entry for unjoined initiatives."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    other_initiative = await create_initiative(session, admin.guild, admin.user)

    await create_project(session, admin.initiative, member.user, name="Member project")
    await create_project(session, admin.initiative, admin.user, name="Admin project")
    await create_project(
        session, admin.initiative, admin.user, name="Archived", is_archived=True
    )
    await create_project(
        session, admin.initiative, admin.user, name="Template", is_template=True
    )
    await create_project(session, other_initiative, admin.user, name="Other project")

    # Guild admin: every non-archived, non-template project, grouped.
    response = await client.get(
        admin.g("/projects/counts/by-initiative"), headers=admin.headers
    )
    assert response.status_code == 200
    assert response.json()["counts"] == {
        str(admin.initiative.id): 2,
        str(other_initiative.id): 1,
    }

    # Member: only projects shared with them, and no entry for
    # initiatives they are not in.
    response = await client.get(
        member.g("/projects/counts/by-initiative"), headers=member.headers
    )
    assert response.status_code == 200
    assert response.json()["counts"] == {str(admin.initiative.id): 1}
