"""
Integration tests for authentication endpoints.

Tests the auth API endpoints including:
- User registration
- Login/token generation
- Bootstrap status
- Email verification
- Password reset
"""

from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.encryption import encrypt_field, hash_email, SALT_EMAIL
from app.core.security import create_access_token, get_password_hash
from app.models.user import User, UserStatus
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
    assert data["status"] == "active"
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
async def test_register_persists_browser_timezone(
    client: AsyncClient, session: AsyncSession
):
    """The SPA forwards ``Intl.DateTimeFormat().resolvedOptions().timeZone``
    on registration so the new account's wall clock matches the user's
    actual zone instead of the model default ``"UTC"``."""
    from sqlmodel import select

    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "tz-user@example.com",
            "full_name": "TZ User",
            "password": "password123",
            "timezone": "America/Los_Angeles",
        },
    )
    assert response.status_code == 201
    user = (
        await session.exec(
            select(User).where(User.email_hash == hash_email("tz-user@example.com"))
        )
    ).one()
    assert user.timezone == "America/Los_Angeles"


@pytest.mark.integration
@pytest.mark.auth
async def test_register_rejects_invalid_timezone(client: AsyncClient):
    """Bogus IANA names from a hand-crafted request are rejected with the
    same error code the self-update path uses, so the SPA's existing
    ``getErrorMessage`` mapping picks it up."""
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "bad-tz@example.com",
            "full_name": "Bad TZ",
            "password": "password123",
            "timezone": "Mars/Olympus_Mons",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "USER_INVALID_TIMEZONE"


@pytest.mark.integration
@pytest.mark.auth
async def test_register_without_timezone_keeps_utc_default(
    client: AsyncClient, session: AsyncSession
):
    """Non-SPA callers (curl, integration scripts) that omit the field
    still hit the model default — keeps the change non-breaking."""
    from sqlmodel import select

    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "no-tz@example.com",
            "full_name": "No TZ",
            "password": "password123",
        },
    )
    assert response.status_code == 201
    user = (
        await session.exec(
            select(User).where(User.email_hash == hash_email("no-tz@example.com"))
        )
    ).one()
    assert user.timezone == "UTC"


# --- Captcha gate ----------------------------------------------------


@pytest.mark.integration
@pytest.mark.auth
async def test_register_requires_captcha_token_when_configured(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """When the deployment has CAPTCHA_PROVIDER set, the second-and-later
    user must include a token — bot signups can't slip through by just
    omitting the field. The bootstrap user already exists in this test
    so the first-user skip doesn't apply."""
    from app.core.config import settings as app_settings

    await create_user(session)  # exhaust the bootstrap-first-user skip
    monkeypatch.setattr(app_settings, "CAPTCHA_PROVIDER", "hcaptcha")
    monkeypatch.setattr(app_settings, "CAPTCHA_SITE_KEY", "site")
    monkeypatch.setattr(app_settings, "CAPTCHA_SECRET_KEY", "secret")

    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "needs-captcha@example.com",
            "full_name": "Needs Captcha",
            "password": "password123",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "CAPTCHA_REQUIRED"


@pytest.mark.integration
@pytest.mark.auth
async def test_register_skips_captcha_for_bootstrap_first_user(
    client: AsyncClient, monkeypatch
):
    """Fresh deployments shouldn't be locked out by a captcha config
    the operator may not have wired up yet — the first user always
    bypasses the check."""
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "CAPTCHA_PROVIDER", "hcaptcha")
    monkeypatch.setattr(app_settings, "CAPTCHA_SITE_KEY", "site")
    monkeypatch.setattr(app_settings, "CAPTCHA_SECRET_KEY", "secret")

    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "bootstrap@example.com",
            "full_name": "Bootstrap",
            "password": "password123",
        },
    )
    assert response.status_code == 201


@pytest.mark.integration
@pytest.mark.auth
async def test_register_no_captcha_required_when_provider_unset(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """OSS deployments leave the captcha vars unset — registration must
    work as before, with no field required."""
    from app.core.config import settings as app_settings

    await create_user(session)  # second-user path
    monkeypatch.setattr(app_settings, "CAPTCHA_PROVIDER", None)
    monkeypatch.setattr(app_settings, "CAPTCHA_SITE_KEY", None)
    monkeypatch.setattr(app_settings, "CAPTCHA_SECRET_KEY", None)

    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "no-captcha@example.com",
            "full_name": "No Captcha",
            "password": "password123",
        },
    )
    assert response.status_code == 201


@pytest.mark.integration
@pytest.mark.auth
async def test_register_with_valid_captcha_token_succeeds(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """Happy path: valid token from the provider → registration completes.
    The provider call is stubbed at the verifier-service layer so this
    test doesn't need network access."""
    from app.core.config import settings as app_settings
    from app.services import captcha as captcha_service

    await create_user(session)  # second-user path
    monkeypatch.setattr(app_settings, "CAPTCHA_PROVIDER", "hcaptcha")
    monkeypatch.setattr(app_settings, "CAPTCHA_SITE_KEY", "site")
    monkeypatch.setattr(app_settings, "CAPTCHA_SECRET_KEY", "secret")

    async def _ok(*_args, **_kwargs):
        return None

    monkeypatch.setattr(captcha_service, "verify_or_raise", _ok)

    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "good-token@example.com",
            "full_name": "Good Token",
            "password": "password123",
            "captcha_token": "stub-valid-token",
        },
    )
    assert response.status_code == 201


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
        status=UserStatus.active,
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
        status=UserStatus.active,
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
        status=UserStatus.deactivated,  # Deactivated user
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
        status=UserStatus.active,
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
        status=UserStatus.active,
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
async def test_malformed_jwt_returns_401(client: AsyncClient):
    """A garbage bearer token should be rejected as 401 Unauthorized with
    a WWW-Authenticate challenge, not 403. The SPA's 401 interceptor
    depends on this distinction to auto-redirect expired sessions to
    /welcome."""
    headers = {"Authorization": "Bearer not.a.valid.jwt"}
    response = await client.get("/api/v1/users/me", headers=headers)

    assert response.status_code == 401
    assert response.headers.get("WWW-Authenticate") == "Bearer"


@pytest.mark.integration
@pytest.mark.auth
async def test_expired_jwt_returns_401(
    client: AsyncClient, session: AsyncSession
):
    """An expired JWT (the common case when the access token lifetime
    elapses mid-session) must return 401, not 403. Regression guard
    for the 403 -> 401 fix in get_current_user."""
    user = await create_user(session)
    expired_token = create_access_token(
        subject=str(user.id),
        token_version=user.token_version,
        expires_delta=timedelta(seconds=-1),
    )
    response = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )

    assert response.status_code == 401
    assert response.headers.get("WWW-Authenticate") == "Bearer"


@pytest.mark.integration
@pytest.mark.auth
async def test_stale_token_version_returns_401(
    client: AsyncClient, session: AsyncSession
):
    """A JWT issued before a token_version bump (e.g. after logout or
    password change) must return 401 so the SPA auto-redirects instead
    of leaving a stale session in place."""
    user = await create_user(session)
    stale_token = create_access_token(
        subject=str(user.id),
        token_version=user.token_version,
    )
    # Bump the version out-of-band to simulate a logout happening in
    # another tab.
    user.token_version += 1
    session.add(user)
    await session.commit()

    response = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {stale_token}"},
    )
    assert response.status_code == 401


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


@pytest.mark.integration
@pytest.mark.auth
async def test_oidc_callback_blocks_new_user_when_registration_disabled(
    client: AsyncClient,
    session: AsyncSession,
    monkeypatch,
):
    """OIDC callback must not create a new account when public registration is off."""
    from app.core import config as cfg
    import app.api.v1.endpoints.auth as auth_module

    monkeypatch.setattr(cfg.settings, "ENABLE_PUBLIC_REGISTRATION", False)
    # Must have at least one existing user so is_first_user is False
    await create_user(session)

    valid_state = auth_module._generate_state()

    class _FakeTokenResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {"access_token": "tok", "sub": "sub-new"}

    class _FakeUserinfoResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {"email": "brandnew@example.com", "name": "Brand New", "sub": "sub-new"}

    class _FakeHttpxClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, *a, **kw): return _FakeTokenResp()
        async def get(self, *a, **kw): return _FakeUserinfoResp()

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _FakeHttpxClient())

    async def _fake_runtime_config(s):
        settings_obj = type("S", (), {
            "oidc_enabled": True, "oidc_issuer": "https://id.example.com",
            "oidc_client_id": "cid", "oidc_client_secret_encrypted": "enc",
            "oidc_scopes": ["openid"], "oidc_provider_name": "Test",
            "oidc_role_claim_path": None,
        })()
        metadata = {
            "authorization_endpoint": "https://id.example.com/auth",
            "token_endpoint": "https://id.example.com/token",
            "userinfo_endpoint": "https://id.example.com/userinfo",
        }
        return settings_obj, metadata

    monkeypatch.setattr(auth_module, "_get_oidc_runtime_config", _fake_runtime_config)

    response = await client.get(
        "/api/v1/auth/oidc/callback",
        params={"code": "fake-code", "state": valid_state},
        follow_redirects=False,
    )

    assert response.status_code in (302, 307)
    assert "OIDC_REGISTRATION_DISABLED" in response.headers["location"]
    assert "session_token" not in response.cookies
