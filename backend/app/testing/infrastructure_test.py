"""
Smoke tests to verify test infrastructure is working correctly.

These tests validate that the test database, fixtures, and basic
testing setup are functioning properly.
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.user import UserStatus
from app.testing.factories import create_user, get_auth_headers


@pytest.mark.unit
async def test_database_session(session: AsyncSession):
    """Test that database session fixture works."""
    assert session is not None
    assert isinstance(session, AsyncSession)


@pytest.mark.unit
async def test_create_user_factory(session: AsyncSession):
    """Test that user factory creates users correctly."""
    user = await create_user(
        session,
        email="factory-test@example.com",
        full_name="Factory Test User",
    )

    assert user.id is not None
    assert user.email == "factory-test@example.com"
    assert user.full_name == "Factory Test User"
    assert user.status == UserStatus.active
    assert user.hashed_password is not None


@pytest.mark.integration
async def test_http_client(client: AsyncClient):
    """Test that HTTP client fixture works."""
    assert client is not None
    assert isinstance(client, AsyncClient)


@pytest.mark.integration
async def test_version_endpoint(client: AsyncClient):
    """Test the version endpoint to verify API is working."""
    response = await client.get("/api/v1/version")
    assert response.status_code == 200
    data = response.json()
    assert "version" in data


@pytest.mark.integration
async def test_authenticated_request(client: AsyncClient, session: AsyncSession):
    """Test that authenticated requests work with auth headers."""
    # Create a test user
    user = await create_user(session, email="auth-test@example.com")

    # Get auth headers
    headers = get_auth_headers(user)

    # Make authenticated request
    response = await client.get("/api/v1/users/me", headers=headers)
    assert response.status_code == 200

    data = response.json()
    assert data["email"] == "auth-test@example.com"
    assert data["id"] == user.id


@pytest.mark.integration
async def test_acting_user_builds_guild_workspace(client: AsyncClient, acting_user):
    """The Actor seam provisions a guild + initiative + project and mints
    headers that work through the real-role request path."""
    from app.models.platform.guild import GuildRole
    from app.models.platform.user import UserRole

    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    # Guild-path actors default to the LOWEST platform tier: guild access
    # must never depend on platform privileges.
    assert a.user.role == UserRole.member
    assert a.guild is not None and a.initiative is not None and a.project is not None

    response = await client.get(a.g("/projects/"), headers=a.headers)
    assert response.status_code == 200
    assert any(p["id"] == a.project.id for p in response.json()["items"])

    # A second actor joining the same guild/initiative at member level.
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    response = await client.get(b.g("/initiatives/"), headers=b.headers)
    assert response.status_code == 200
    assert any(i["id"] == a.initiative.id for i in response.json())


@pytest.mark.unit
async def test_tenant_rows_land_in_guild_schema(session: AsyncSession, acting_user):
    """Factory-created tenant rows live in guild_<id>, not public (which no
    longer has tenant tables since the baseline squash)."""
    from sqlalchemy import text

    a = await acting_user(guild_role="admin", initiative=True, project=True)
    count = (
        await session.exec(
            text(  # type: ignore[call-overload]
                f'SELECT count(*) FROM "guild_{a.guild.id}".projects'
            )
        )
    ).scalar()
    assert count == 1


@pytest.mark.unit
async def test_unrouted_tenant_write_fails_closed(session: AsyncSession, acting_user):
    """A tenant write that carries no guild_id on an unrouted session must
    raise the harness's explicit error, not fall through toward public."""
    from sqlalchemy import text

    from app.models.tenant.task import TaskAssignee

    a = await acting_user(guild_role="admin")
    # Un-route the session, then write a guild_id-less junction row. The
    # router raises in before_flush, so no SQL (and no FK check) ever runs.
    await session.exec(
        text("SELECT set_config('search_path', 'public', false)")  # type: ignore[call-overload]
    )
    session.add(TaskAssignee(task_id=1, user_id=a.user.id))
    with pytest.raises(RuntimeError, match="not routed to a guild schema"):
        await session.commit()
    await session.rollback()
