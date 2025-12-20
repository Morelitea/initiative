"""
Smoke tests to verify test infrastructure is working correctly.

These tests validate that the test database, fixtures, and basic
testing setup are functioning properly.
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from tests.factories import create_user, get_auth_headers


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
    assert user.is_active is True
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
