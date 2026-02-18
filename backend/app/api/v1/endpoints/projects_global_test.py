"""
Integration tests for the global projects endpoint.

Tests GET /api/v1/projects/global which returns projects across all guilds
the current user belongs to, filtered by DAC permissions.
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.guild import GuildRole
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_project,
    create_user,
    get_guild_headers,
)


async def _setup_guild_with_project(session, user, *, guild_name="Test Guild"):
    """Create a guild, membership, initiative, and project for the user."""
    guild = await create_guild(session, creator=user, name=guild_name)
    await create_guild_membership(
        session, user=user, guild=guild, role=GuildRole.admin
    )
    initiative = await create_initiative(session, guild, user, name="Initiative")
    project = await create_project(session, initiative, user, name="Project")
    return guild, initiative, project


@pytest.mark.integration
async def test_list_global_projects(client: AsyncClient, session: AsyncSession):
    """GET /projects/global should return projects from the user's guilds."""
    user = await create_user(session, email="user@example.com")
    guild, _, project = await _setup_guild_with_project(session, user)

    headers = get_guild_headers(guild, user)
    response = await client.get("/api/v1/projects/global", headers=headers)

    assert response.status_code == 200
    data = response.json()
    project_ids = {p["id"] for p in data["items"]}
    assert project.id in project_ids
    assert data["total_count"] >= 1


@pytest.mark.integration
async def test_list_global_projects_excludes_archived(
    client: AsyncClient, session: AsyncSession
):
    """Archived projects should not appear in global project list."""
    user = await create_user(session, email="user@example.com")
    guild, initiative, project = await _setup_guild_with_project(session, user)

    archived_project = await create_project(
        session, initiative, user, name="Archived Project"
    )
    archived_project.is_archived = True
    session.add(archived_project)
    await session.commit()

    headers = get_guild_headers(guild, user)
    response = await client.get("/api/v1/projects/global", headers=headers)

    assert response.status_code == 200
    project_ids = {p["id"] for p in response.json()["items"]}
    assert project.id in project_ids
    assert archived_project.id not in project_ids


@pytest.mark.integration
async def test_list_global_projects_excludes_templates(
    client: AsyncClient, session: AsyncSession
):
    """Template projects should not appear in global project list."""
    user = await create_user(session, email="user@example.com")
    guild, initiative, project = await _setup_guild_with_project(session, user)

    template_project = await create_project(
        session, initiative, user, name="Template Project"
    )
    template_project.is_template = True
    session.add(template_project)
    await session.commit()

    headers = get_guild_headers(guild, user)
    response = await client.get("/api/v1/projects/global", headers=headers)

    assert response.status_code == 200
    project_ids = {p["id"] for p in response.json()["items"]}
    assert project.id in project_ids
    assert template_project.id not in project_ids


@pytest.mark.integration
async def test_list_global_projects_respects_permissions(
    client: AsyncClient, session: AsyncSession
):
    """Users should only see projects they have DAC permissions for."""
    admin = await create_user(session, email="admin@example.com")
    member = await create_user(session, email="member@example.com")

    guild = await create_guild(session, creator=admin, name="Shared Guild")
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    await create_guild_membership(session, user=member, guild=guild)

    initiative = await create_initiative(session, guild, admin, name="Initiative")
    # Admin's project — member has no explicit permission
    admin_project = await create_project(
        session, initiative, admin, name="Admin Project"
    )

    # Member requests global projects — should NOT see admin_project
    headers = get_guild_headers(guild, member)
    response = await client.get("/api/v1/projects/global", headers=headers)

    assert response.status_code == 200
    project_ids = {p["id"] for p in response.json()["items"]}
    assert admin_project.id not in project_ids


@pytest.mark.integration
async def test_list_global_projects_guild_filter(
    client: AsyncClient, session: AsyncSession
):
    """guild_ids filter should restrict results to specific guilds."""
    user = await create_user(session, email="user@example.com")
    guild1, _, project1 = await _setup_guild_with_project(
        session, user, guild_name="Guild 1"
    )
    guild2, _, project2 = await _setup_guild_with_project(
        session, user, guild_name="Guild 2"
    )

    headers = get_guild_headers(guild1, user)
    response = await client.get(
        f"/api/v1/projects/global?guild_ids={guild1.id}", headers=headers
    )

    assert response.status_code == 200
    project_ids = {p["id"] for p in response.json()["items"]}
    assert project1.id in project_ids
    assert project2.id not in project_ids


@pytest.mark.integration
async def test_list_global_projects_search(
    client: AsyncClient, session: AsyncSession
):
    """search parameter should filter projects by name."""
    user = await create_user(session, email="user@example.com")
    guild, initiative, _ = await _setup_guild_with_project(session, user)

    alpha = await create_project(session, initiative, user, name="Alpha Project")
    beta = await create_project(session, initiative, user, name="Beta Project")

    headers = get_guild_headers(guild, user)
    response = await client.get(
        "/api/v1/projects/global?search=alpha", headers=headers
    )

    assert response.status_code == 200
    project_ids = {p["id"] for p in response.json()["items"]}
    assert alpha.id in project_ids
    assert beta.id not in project_ids


@pytest.mark.integration
async def test_list_global_projects_pagination(
    client: AsyncClient, session: AsyncSession
):
    """Global projects should support pagination."""
    user = await create_user(session, email="user@example.com")
    guild, initiative, _ = await _setup_guild_with_project(session, user)

    # Create additional projects (factory already created 1)
    for i in range(3):
        await create_project(session, initiative, user, name=f"Extra {i}")

    headers = get_guild_headers(guild, user)

    # Page 1 with page_size=2
    response = await client.get(
        "/api/v1/projects/global?page=1&page_size=2", headers=headers
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 2
    assert data["total_count"] >= 4  # 1 from setup + 3 extra
    assert data["has_next"] is True

    # Page 2
    response = await client.get(
        "/api/v1/projects/global?page=2&page_size=2", headers=headers
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 2
    assert data["page"] == 2
