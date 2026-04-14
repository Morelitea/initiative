"""
Integration tests for authentication endpoints.

Tests the auth API endpoints including:
- User registration
- Login/token generation
- Bootstrap status
- Email verification
- Password reset
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.encryption import encrypt_field, hash_email, SALT_EMAIL
from app.core.security import get_password_hash
from app.models.user import User
from app.testing.factories import create_user, get_auth_headers, get_auth_token


@pytest.mark.integration
@pytest.mark.auth
async def test_bootstrap_status_no_users(client: AsyncClient):
    """Test bootstrap status when no users exist."""
    response = await client.get("/api/v1/auth/bootstrap")

    assert response.status_code == 200
    data = response.json()
    assert data["has_users"] is False
    assert "public_registration_enabled" in data


@pytest.mark.integration
@pytest.mark.auth
async def test_bootstrap_status_with_users(client: AsyncClient, session: AsyncSession):
    """Test bootstrap status when users exist."""
    await create_user(session)

    response = await client.get("/api/v1/auth/bootstrap")

    assert response.status_code == 200
    data = response.json()
    assert data["has_users"] is True
    assert "public_registration_enabled" in data


@pytest.mark.integration
@pytest.mark.auth
async def test_register_first_user(client: AsyncClient):
    """Test that first registered user becomes admin and gets a guild."""
    user_data = {
        "email": "first@example.com",
        "full_name": "First User",
        "password": "securepassword123",
    }

    response = await client.post("/api/v1/auth/register", json=user_data)

    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "first@example.com"
    assert data["full_name"] == "First User"
    assert data["is_active"] is True
    assert data["role"] == "admin"  # First user should be admin


@pytest.mark.integration
@pytest.mark.auth
async def test_register_duplicate_email(client: AsyncClient, session: AsyncSession):
    """Test that registration fails for duplicate email."""
    await create_user(session, email="existing@example.com")

    user_data = {
        "email": "existing@example.com",
        "full_name": "Duplicate User",
        "password": "password123",
    }

    response = await client.post("/api/v1/auth/register", json=user_data)

    assert response.status_code == 400
    assert response.json()["detail"] == "EMAIL_ALREADY_REGISTERED"


@pytest.mark.integration
@pytest.mark.auth
async def test_register_normalizes_email(client: AsyncClient):
    """Test that email is normalized during registration."""
    user_data = {
        "email": "  TEST@EXAMPLE.COM  ",
        "full_name": "Test User",
        "password": "password123",
    }

    response = await client.post("/api/v1/auth/register", json=user_data)

    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "test@example.com"


@pytest.mark.integration
@pytest.mark.auth
async def test_login_success(client: AsyncClient, session: AsyncSession):
    """Test successful login returns access token."""
    # Create user with known password
    password = "testpassword123"
    user = User(
        email_hash=hash_email("login@example.com"),
        email_encrypted=encrypt_field("login@example.com", SALT_EMAIL),
        full_name="Login User",
        hashed_password=get_password_hash(password),
        is_active=True,
        email_verified=True,
    )
    session.add(user)
    await session.commit()

    # Attempt login
    response = await client.post(
        "/api/v1/auth/token",
        data={
            "username": "login@example.com",
            "password": password,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert len(data["access_token"]) > 0


@pytest.mark.integration
@pytest.mark.auth
async def test_login_wrong_password(client: AsyncClient, session: AsyncSession):
    """Test that login fails with wrong password."""
    password = "correct_password"
    user = User(
        email_hash=hash_email("test@example.com"),
        email_encrypted=encrypt_field("test@example.com", SALT_EMAIL),
        full_name="Test User",
        hashed_password=get_password_hash(password),
        is_active=True,
        email_verified=True,
    )
    session.add(user)
    await session.commit()

    response = await client.post(
        "/api/v1/auth/token",
        data={
            "username": "test@example.com",
            "password": "wrong_password",
        },
    )

    assert response.status_code == 400
    assert "incorrect" in response.json()["detail"].lower()


@pytest.mark.integration
@pytest.mark.auth
async def test_login_inactive_user(client: AsyncClient, session: AsyncSession):
    """Test that inactive users cannot login."""
    password = "testpassword"
    user = User(
        email_hash=hash_email("inactive@example.com"),
        email_encrypted=encrypt_field("inactive@example.com", SALT_EMAIL),
        full_name="Inactive User",
        hashed_password=get_password_hash(password),
        is_active=False,  # Inactive user
        email_verified=True,
    )
    session.add(user)
    await session.commit()

    response = await client.post(
        "/api/v1/auth/token",
        data={
            "username": "inactive@example.com",
            "password": password,
        },
    )

    assert response.status_code == 400
    assert "inactive" in response.json()["detail"].lower()


@pytest.mark.integration
@pytest.mark.auth
async def test_login_unverified_email(client: AsyncClient, session: AsyncSession):
    """Test that users with unverified emails cannot login."""
    password = "testpassword"
    user = User(
        email_hash=hash_email("unverified@example.com"),
        email_encrypted=encrypt_field("unverified@example.com", SALT_EMAIL),
        full_name="Unverified User",
        hashed_password=get_password_hash(password),
        is_active=True,
        email_verified=False,  # Email not verified
    )
    session.add(user)
    await session.commit()

    response = await client.post(
        "/api/v1/auth/token",
        data={
            "username": "unverified@example.com",
            "password": password,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "EMAIL_NOT_VERIFIED"


@pytest.mark.integration
@pytest.mark.auth
async def test_login_nonexistent_user(client: AsyncClient):
    """Test that login fails for nonexistent user."""
    response = await client.post(
        "/api/v1/auth/token",
        data={
            "username": "nonexistent@example.com",
            "password": "anypassword",
        },
    )

    assert response.status_code == 400
    assert "incorrect" in response.json()["detail"].lower()


@pytest.mark.integration
@pytest.mark.auth
async def test_login_email_case_insensitive(client: AsyncClient, session: AsyncSession):
    """Test that login email is case-insensitive."""
    password = "testpassword"
    user = User(
        email_hash=hash_email("test@example.com"),
        email_encrypted=encrypt_field("test@example.com", SALT_EMAIL),
        full_name="Test User",
        hashed_password=get_password_hash(password),
        is_active=True,
        email_verified=True,
    )
    session.add(user)
    await session.commit()

    # Login with uppercase email
    response = await client.post(
        "/api/v1/auth/token",
        data={
            "username": "TEST@EXAMPLE.COM",  # uppercase
            "password": password,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data


@pytest.mark.integration
@pytest.mark.auth
async def test_logout_persists_token_version_bump(
    client: AsyncClient, session: AsyncSession
):
    """The logout endpoint must actually persist the token_version bump
    to the database. Previously the endpoint used AdminSessionDep while
    get_current_user_optional used SessionDep, so the user object came
    from a detached session and session.commit() silently dropped the
    change in production. (The conftest fixture aliases both deps to the
    same session, so this test asserts on the raw row state rather than
    relying on a subsequent request to observe the failure.)"""
    user = await create_user(session)
    initial_version = user.token_version

    response = await client.post(
        "/api/v1/auth/logout", headers=get_auth_headers(user)
    )
    assert response.status_code == 204

    # Re-read from the database to prove the bump was persisted.
    await session.refresh(user)
    assert user.token_version == initial_version + 1


@pytest.mark.integration
@pytest.mark.auth
async def test_logout_invalidates_existing_jwt(
    client: AsyncClient, session: AsyncSession
):
    """Logging out must invalidate any previously-issued JWT by bumping
    the user's token_version. Otherwise a browser that still has a
    cached JWT (or cookie) can keep making authenticated requests,
    which is how users reported "I logged out but My Tasks still
    loads when I type the URL"."""
    user = await create_user(session)
    # Baseline: the token works before logout.
    headers = get_auth_headers(user)
    before = await client.get("/api/v1/users/me", headers=headers)
    assert before.status_code == 200

    # Capture the same token so we can replay it after logout.
    replay_token = get_auth_token(user)
    logout_response = await client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {replay_token}"},
    )
    assert logout_response.status_code == 204

    # Any subsequent request using the old token must be rejected.
    after = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {replay_token}"},
    )
    assert after.status_code == 401


@pytest.mark.integration
@pytest.mark.auth
async def test_logout_clears_session_cookie(
    client: AsyncClient, session: AsyncSession
):
    """The logout response must set an expired session_token cookie so
    browsers using HttpOnly cookie auth (the web default) actually
    forget the session."""
    user = await create_user(session)
    response = await client.post(
        "/api/v1/auth/logout", headers=get_auth_headers(user)
    )
    assert response.status_code == 204
    set_cookie = response.headers.get("set-cookie", "")
    assert "session_token=" in set_cookie
    # Starlette's delete_cookie sets Max-Age=0 and an expires in the
    # past. Accept either marker so the assertion is robust.
    assert "Max-Age=0" in set_cookie or "1970" in set_cookie
