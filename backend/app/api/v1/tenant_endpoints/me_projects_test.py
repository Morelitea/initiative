"""
Integration tests for the global projects endpoint.

Tests GET /api/v1/me/projects which returns projects across all guilds
the current user belongs to, filtered by DAC permissions.
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_project,
    create_user,
    get_auth_headers,
)


async def _setup_guild_with_project(session, user, *, guild_name="Test Guild"):
    """Create a guild, membership, initiative, and project for the user."""
    guild = await create_guild(session, creator=user, name=guild_name)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, user, name="Initiative")
    project = await create_project(session, initiative, user, name="Project")
    return guild, initiative, project


@pytest.mark.integration
async def test_list_global_projects(client: AsyncClient, session: AsyncSession):
    """GET /me/projects should return projects from the user's guilds."""
    user = await create_user(session, email="user@example.com")
    guild, _, project = await _setup_guild_with_project(session, user)

    headers = get_auth_headers(user)
    response = await client.get("/api/v1/me/projects", headers=headers)

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

    headers = get_auth_headers(user)
    response = await client.get("/api/v1/me/projects", headers=headers)

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

    headers = get_auth_headers(user)
    response = await client.get("/api/v1/me/projects", headers=headers)

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
    headers = get_auth_headers(member)
    response = await client.get("/api/v1/me/projects", headers=headers)

    assert response.status_code == 200
    project_ids = {p["id"] for p in response.json()["items"]}
    assert admin_project.id not in project_ids


@pytest.mark.integration
async def test_my_projects_follows_grants_not_guild_admin_standing(
    client: AsyncClient, session: AsyncSession
):
    """A guild admin's My Projects is what has been shared with them.

    Their authority still reaches every project in the community — asking for
    the initiative by name still answers with all of it. A list that spans
    initiatives answers a different question: what reaches the reader.
    """
    owner = await create_user(session, email="owner@example.com")
    admin = await create_user(session, email="otheradmin@example.com")

    guild = await create_guild(session, creator=owner, name="Shared Guild")
    await create_guild_membership(
        session, user=owner, guild=guild, role=GuildRole.admin
    )
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )

    elsewhere = await create_initiative(session, guild, owner, name="Not Theirs")
    unshared = await create_project(session, elsewhere, owner, name="Someone Else's")

    mine = await create_initiative(session, guild, admin, name="Theirs")
    shared = await create_project(session, mine, admin, name="Their Own")

    response = await client.get("/api/v1/me/projects", headers=get_auth_headers(admin))

    assert response.status_code == 200
    project_ids = {p["id"] for p in response.json()["items"]}
    assert shared.id in project_ids
    assert unshared.id not in project_ids


@pytest.mark.integration
async def test_an_initiative_listing_still_answers_a_guild_admin_in_full(
    client: AsyncClient, session: AsyncSession
):
    """Naming one initiative asks about standing, and an admin's reaches it all.

    The companion to the test above: the same project the cross-initiative list
    withholds is returned the moment the admin asks for its initiative, which is
    what keeps this a change to navigation rather than to authority.
    """
    owner = await create_user(session, email="owner2@example.com")
    admin = await create_user(session, email="otheradmin2@example.com")

    guild = await create_guild(session, creator=owner, name="Shared Guild")
    await create_guild_membership(
        session, user=owner, guild=guild, role=GuildRole.admin
    )
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )

    elsewhere = await create_initiative(session, guild, owner, name="Not Theirs")
    unshared = await create_project(session, elsewhere, owner, name="Someone Else's")

    headers = get_auth_headers(admin)
    across = await client.get(f"/api/v1/g/{guild.id}/projects/", headers=headers)
    assert across.status_code == 200
    assert unshared.id not in {p["id"] for p in across.json()["items"]}

    within = await client.get(
        f"/api/v1/g/{guild.id}/projects/?initiative_id={elsewhere.id}",
        headers=headers,
    )
    assert within.status_code == 200
    assert unshared.id in {p["id"] for p in within.json()["items"]}


@pytest.mark.integration
async def test_list_global_projects_guild_filter(
    client: AsyncClient, session: AsyncSession
):
    """The global list spans every guild the user belongs to; guild_ids narrows it.

    Project ids are per-guild (per-schema), so two guilds' projects can share an
    id — items are keyed by (guild_id, id), which is what callers must use too.
    """
    user = await create_user(session, email="user@example.com")
    guild1, _, project1 = await _setup_guild_with_project(
        session, user, guild_name="Guild 1"
    )
    guild2, _, project2 = await _setup_guild_with_project(
        session, user, guild_name="Guild 2"
    )
    headers = get_auth_headers(user)

    def keyed(resp):
        return {(p["initiative"]["guild_id"], p["id"]) for p in resp.json()["items"]}

    # No filter: projects from BOTH guilds are aggregated.
    response = await client.get("/api/v1/me/projects", headers=headers)
    assert response.status_code == 200
    found = keyed(response)
    assert (guild1.id, project1.id) in found
    assert (guild2.id, project2.id) in found

    # Filtered to guild1: only guild1's project.
    response = await client.get(
        f"/api/v1/me/projects?guild_ids={guild1.id}", headers=headers
    )
    assert response.status_code == 200
    found = keyed(response)
    assert (guild1.id, project1.id) in found
    assert (guild2.id, project2.id) not in found


@pytest.mark.integration
async def test_list_global_projects_search(client: AsyncClient, session: AsyncSession):
    """search parameter should filter projects by name."""
    user = await create_user(session, email="user@example.com")
    guild, initiative, _ = await _setup_guild_with_project(session, user)

    alpha = await create_project(session, initiative, user, name="Alpha Project")
    beta = await create_project(session, initiative, user, name="Beta Project")

    headers = get_auth_headers(user)
    response = await client.get("/api/v1/me/projects?search=alpha", headers=headers)

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

    headers = get_auth_headers(user)

    # Page 1 with page_size=2
    response = await client.get(
        "/api/v1/me/projects?page=1&page_size=2", headers=headers
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 2
    assert data["total_count"] >= 4  # 1 from setup + 3 extra
    assert data["has_next"] is True

    # Page 2
    response = await client.get(
        "/api/v1/me/projects?page=2&page_size=2", headers=headers
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 2
    assert data["page"] == 2
