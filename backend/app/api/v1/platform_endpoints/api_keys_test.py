"""
Integration tests for user-scoped API key endpoints.

Tests the API key endpoints at /api/v1/users/me/api-keys including:
- Listing API keys
- Creating API keys
- Deleting API keys
- Authentication with API keys
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_user,
    get_auth_headers,
)


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

    response = await client.post(
        "/api/v1/users/me/api-keys", headers=headers, json=payload
    )

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
async def test_create_api_key_with_expiration(
    client: AsyncClient, session: AsyncSession
):
    """A future expiry within the max-TTL window is honored verbatim."""
    user = await create_user(session, email="test@example.com")
    headers = get_auth_headers(user)

    expires = datetime.now(timezone.utc) + timedelta(days=30)
    payload = {
        "name": "Expiring Key",
        "expires_at": expires.isoformat(),
    }

    response = await client.post(
        "/api/v1/users/me/api-keys", headers=headers, json=payload
    )

    assert response.status_code == 201
    data = response.json()
    returned = datetime.fromisoformat(data["api_key"]["expires_at"])
    # Within the 90-day ceiling, so preserved (allow ~1s of round-trip drift).
    assert abs((returned - expires).total_seconds()) < 5


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
async def test_cannot_delete_other_users_api_key(
    client: AsyncClient, session: AsyncSession
):
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
async def test_api_key_works_for_non_admin_users(
    client: AsyncClient, session: AsyncSession
):
    """Test that non-admin users can create and use API keys."""
    # Create a regular member user (not admin)
    from app.models.platform.user import UserRole

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
async def test_api_key_prefix_is_masked_in_list(
    client: AsyncClient, session: AsyncSession
):
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


# --- Least-privilege scoping (read_only / guild_id) -------------------------


@pytest.mark.integration
@pytest.mark.auth
async def test_create_api_key_without_expiry_never_expires(
    client: AsyncClient, session: AsyncSession
):
    """A key created without an expiry never expires, and a far-future expiry
    is kept verbatim (no enforced ceiling) — revocation is the kill switch."""
    user = await create_user(session, email="ttl@example.com")
    headers = get_auth_headers(user)

    forever = await client.post(
        "/api/v1/users/me/api-keys", headers=headers, json={"name": "Forever"}
    )
    assert forever.status_code == 201
    assert forever.json()["api_key"]["expires_at"] is None

    far = (datetime.now(timezone.utc) + timedelta(days=3650)).isoformat()
    long_lived = await client.post(
        "/api/v1/users/me/api-keys",
        headers=headers,
        json={"name": "Far", "expires_at": far},
    )
    returned = datetime.fromisoformat(long_lived.json()["api_key"]["expires_at"])
    expected = datetime.fromisoformat(far)
    assert abs((returned - expected).total_seconds()) < 5


@pytest.mark.integration
@pytest.mark.auth
async def test_read_only_key_blocks_writes_allows_reads(
    client: AsyncClient, session: AsyncSession
):
    """A read_only key may issue safe reads but is refused on any write."""
    user = await create_user(session, email="ro@example.com")
    headers = get_auth_headers(user)

    create = await client.post(
        "/api/v1/users/me/api-keys",
        headers=headers,
        json={"name": "RO", "read_only": True},
    )
    assert create.status_code == 201
    assert create.json()["api_key"]["read_only"] is True
    ro_headers = {"Authorization": f"Bearer {create.json()['secret']}"}

    # Safe read works.
    read = await client.get("/api/v1/users/me", headers=ro_headers)
    assert read.status_code == 200

    # A write (creating another key) is refused at the auth layer.
    write = await client.post(
        "/api/v1/users/me/api-keys", headers=ro_headers, json={"name": "nope"}
    )
    assert write.status_code == 403
    assert write.json()["detail"] == "USER_API_KEY_READ_ONLY"


@pytest.mark.integration
@pytest.mark.auth
async def test_guild_bound_key_is_pinned_to_its_guild(
    client: AsyncClient, session: AsyncSession
):
    """A guild-bound key reaches only its own guild; a different guild the user
    is otherwise a member of is refused (proving the block is the key pin)."""
    user = await create_user(session, email="pinned@example.com")
    guild_a = await create_guild(session, creator=user)
    guild_b = await create_guild(session, creator=user)
    await create_guild_membership(
        session, user=user, guild=guild_a, role=GuildRole.member
    )
    await create_guild_membership(
        session, user=user, guild=guild_b, role=GuildRole.member
    )
    headers = get_auth_headers(user)

    create = await client.post(
        "/api/v1/users/me/api-keys",
        headers=headers,
        json={"name": "GuildA", "guild_id": guild_a.id},
    )
    assert create.json()["api_key"]["guild_id"] == guild_a.id
    key_headers = {"Authorization": f"Bearer {create.json()['secret']}"}

    # Reaches its own guild.
    own = await client.get(f"/api/v1/g/{guild_a.id}/initiatives/", headers=key_headers)
    assert own.status_code == 200

    # Refused on a different guild the user *is* a member of.
    other = await client.get(
        f"/api/v1/g/{guild_b.id}/initiatives/", headers=key_headers
    )
    assert other.status_code == 403
    assert other.json()["detail"] == "GUILD_ACCESS_DENIED"

    # The same user's session JWT reaches guild B — so the block was the key
    # pin, not a membership problem.
    jwt_other = await client.get(
        f"/api/v1/g/{guild_b.id}/initiatives/", headers=headers
    )
    assert jwt_other.status_code == 200


@pytest.mark.integration
@pytest.mark.auth
async def test_password_change_deactivates_api_keys(
    client: AsyncClient, session: AsyncSession
):
    """Changing the password (a credential-reset) deactivates outstanding API
    keys, so a leaked key can't survive a compromise response."""
    user = await create_user(session, email="rotate@example.com")
    headers = get_auth_headers(user)

    create = await client.post(
        "/api/v1/users/me/api-keys", headers=headers, json={"name": "Doomed"}
    )
    key_headers = {"Authorization": f"Bearer {create.json()['secret']}"}

    # The key works before the reset.
    before = await client.get("/api/v1/users/me", headers=key_headers)
    assert before.status_code == 200

    # Reset the password with the required current password.
    changed = await client.patch(
        "/api/v1/users/me",
        headers=headers,
        json={
            "password": "brand-new-secret-123",
            "current_password": "testpassword123",
        },
    )
    assert changed.status_code == 200

    # The key no longer authenticates.
    after = await client.get("/api/v1/users/me", headers=key_headers)
    assert after.status_code == 401
