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
from app.testing.factories import create_user


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
