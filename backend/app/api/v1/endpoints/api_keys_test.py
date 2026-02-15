"""
Integration tests for user-scoped API key endpoints.

Tests the API key endpoints at /api/v1/users/me/api-keys including:
- Listing API keys
- Creating API keys
- Deleting API keys
- Authentication with API keys
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.testing.factories import create_user, get_auth_headers


@pytest.mark.integration
@pytest.mark.auth
async def test_list_api_keys_empty(client: AsyncClient, session: AsyncSession):
    """Test listing API keys when user has none."""
    user = await create_user(session, email="test@example.com")
    headers = get_auth_headers(user)

    response = await client.get("/api/v1/users/me/api-keys", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert data["keys"] == []


@pytest.mark.integration
@pytest.mark.auth
async def test_create_api_key(client: AsyncClient, session: AsyncSession):
    """Test creating a new API key."""
    user = await create_user(session, email="test@example.com")
    headers = get_auth_headers(user)

    payload = {
        "name": "Test API Key",
        "expires_at": None,
    }

    response = await client.post("/api/v1/users/me/api-keys", headers=headers, json=payload)

    assert response.status_code == 201
    data = response.json()
    assert "secret" in data
    assert "api_key" in data
    assert data["api_key"]["name"] == "Test API Key"
    assert data["api_key"]["is_active"] is True
    assert data["secret"].startswith("ppk_")
    assert len(data["secret"]) > 20


@pytest.mark.integration
@pytest.mark.auth
async def test_create_api_key_with_expiration(client: AsyncClient, session: AsyncSession):
    """Test creating an API key with expiration date."""
    user = await create_user(session, email="test@example.com")
    headers = get_auth_headers(user)

    payload = {
        "name": "Expiring Key",
        "expires_at": "2025-12-31T23:59:59Z",
    }

    response = await client.post("/api/v1/users/me/api-keys", headers=headers, json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["api_key"]["expires_at"] is not None
    assert "2025-12-31" in data["api_key"]["expires_at"]


@pytest.mark.integration
@pytest.mark.auth
async def test_list_api_keys_after_creation(client: AsyncClient, session: AsyncSession):
    """Test that created API keys appear in list."""
    user = await create_user(session, email="test@example.com")
    headers = get_auth_headers(user)

    # Create two API keys
    await client.post(
        "/api/v1/users/me/api-keys",
        headers=headers,
        json={"name": "Key 1"},
    )
    await client.post(
        "/api/v1/users/me/api-keys",
        headers=headers,
        json={"name": "Key 2"},
    )

    # List keys
    response = await client.get("/api/v1/users/me/api-keys", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert len(data["keys"]) == 2
    key_names = {key["name"] for key in data["keys"]}
    assert "Key 1" in key_names
    assert "Key 2" in key_names


@pytest.mark.integration
@pytest.mark.auth
async def test_delete_api_key(client: AsyncClient, session: AsyncSession):
    """Test deleting an API key."""
    user = await create_user(session, email="test@example.com")
    headers = get_auth_headers(user)

    # Create a key
    create_response = await client.post(
        "/api/v1/users/me/api-keys",
        headers=headers,
        json={"name": "To Delete"},
    )
    api_key_id = create_response.json()["api_key"]["id"]

    # Delete it
    delete_response = await client.delete(
        f"/api/v1/users/me/api-keys/{api_key_id}",
        headers=headers,
    )

    assert delete_response.status_code == 204

    # Verify it's gone
    list_response = await client.get("/api/v1/users/me/api-keys", headers=headers)
    assert len(list_response.json()["keys"]) == 0


@pytest.mark.integration
@pytest.mark.auth
async def test_delete_nonexistent_api_key(client: AsyncClient, session: AsyncSession):
    """Test deleting an API key that doesn't exist."""
    user = await create_user(session, email="test@example.com")
    headers = get_auth_headers(user)

    response = await client.delete("/api/v1/users/me/api-keys/99999", headers=headers)

    assert response.status_code == 404
    assert response.json()["detail"] == "USER_API_KEY_NOT_FOUND"


@pytest.mark.integration
@pytest.mark.auth
async def test_cannot_delete_other_users_api_key(client: AsyncClient, session: AsyncSession):
    """Test that users cannot delete other users' API keys."""
    user1 = await create_user(session, email="user1@example.com")
    user2 = await create_user(session, email="user2@example.com")

    headers1 = get_auth_headers(user1)
    headers2 = get_auth_headers(user2)

    # User 1 creates a key
    create_response = await client.post(
        "/api/v1/users/me/api-keys",
        headers=headers1,
        json={"name": "User 1 Key"},
    )
    api_key_id = create_response.json()["api_key"]["id"]

    # User 2 tries to delete User 1's key
    delete_response = await client.delete(
        f"/api/v1/users/me/api-keys/{api_key_id}",
        headers=headers2,
    )

    assert delete_response.status_code == 404


@pytest.mark.integration
@pytest.mark.auth
async def test_authenticate_with_api_key(client: AsyncClient, session: AsyncSession):
    """Test that API keys can be used for authentication."""
    user = await create_user(session, email="test@example.com", full_name="Test User")
    headers = get_auth_headers(user)

    # Create an API key
    create_response = await client.post(
        "/api/v1/users/me/api-keys",
        headers=headers,
        json={"name": "Auth Test Key"},
    )
    api_key_secret = create_response.json()["secret"]

    # Use API key to authenticate
    api_key_headers = {"Authorization": f"Bearer {api_key_secret}"}
    auth_response = await client.get("/api/v1/users/me", headers=api_key_headers)

    assert auth_response.status_code == 200
    data = auth_response.json()
    assert data["email"] == "test@example.com"
    assert data["full_name"] == "Test User"


@pytest.mark.integration
@pytest.mark.auth
async def test_api_key_works_for_non_admin_users(client: AsyncClient, session: AsyncSession):
    """Test that non-admin users can create and use API keys."""
    # Create a regular member user (not admin)
    from app.models.user import UserRole

    user = await create_user(
        session,
        email="member@example.com",
        role=UserRole.member,
    )
    headers = get_auth_headers(user)

    # Member creates an API key
    create_response = await client.post(
        "/api/v1/users/me/api-keys",
        headers=headers,
        json={"name": "Member Key"},
    )

    assert create_response.status_code == 201
    api_key_secret = create_response.json()["secret"]

    # Use the API key to authenticate
    api_key_headers = {"Authorization": f"Bearer {api_key_secret}"}
    auth_response = await client.get("/api/v1/users/me", headers=api_key_headers)

    assert auth_response.status_code == 200
    assert auth_response.json()["email"] == "member@example.com"


@pytest.mark.integration
@pytest.mark.auth
async def test_create_api_key_requires_authentication(client: AsyncClient):
    """Test that creating API keys requires authentication."""
    payload = {"name": "Unauthorized Key"}

    response = await client.post("/api/v1/users/me/api-keys", json=payload)

    assert response.status_code == 401


@pytest.mark.integration
@pytest.mark.auth
async def test_list_api_keys_requires_authentication(client: AsyncClient):
    """Test that listing API keys requires authentication."""
    response = await client.get("/api/v1/users/me/api-keys")

    assert response.status_code == 401


@pytest.mark.integration
@pytest.mark.auth
async def test_delete_api_key_requires_authentication(client: AsyncClient):
    """Test that deleting API keys requires authentication."""
    response = await client.delete("/api/v1/users/me/api-keys/1")

    assert response.status_code == 401


@pytest.mark.integration
@pytest.mark.auth
async def test_api_key_prefix_is_masked_in_list(client: AsyncClient, session: AsyncSession):
    """Test that API key secrets are not exposed in list, only prefix."""
    user = await create_user(session, email="test@example.com")
    headers = get_auth_headers(user)

    # Create a key
    create_response = await client.post(
        "/api/v1/users/me/api-keys",
        headers=headers,
        json={"name": "Test Key"},
    )
    full_secret = create_response.json()["secret"]
    expected_prefix = full_secret[:12]  # ppk_ plus 8 chars

    # List keys
    list_response = await client.get("/api/v1/users/me/api-keys", headers=headers)
    keys = list_response.json()["keys"]

    assert len(keys) == 1
    assert keys[0]["token_prefix"] == expected_prefix
    assert "secret" not in keys[0]  # Full secret should not be exposed
