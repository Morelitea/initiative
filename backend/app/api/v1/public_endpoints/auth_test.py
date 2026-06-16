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
    """Test that first registered user becomes owner and gets a guild."""
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
    assert data["role"] == "owner"  # First user bootstraps as owner


@pytest.mark.integration
@pytest.mark.auth
async def test_register_duplicate_email(client: AsyncClient, session: AsyncSession):
    """Test that registration fails for duplicate email."""
    await create_user(session, email="existing@example.com")

    user_data = {
        "email": "existing@example.com",
        "full_name": "Duplicate User",
        "password": "password1234",
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
        "password": "password1234",
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
            "password": "password1234",
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
            "password": "password1234",
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
            "password": "password1234",
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
            "password": "password1234",
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
            "password": "password1234",
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
            "password": "password1234",
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
            "password": "password1234",
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
async def test_login_rehashes_legacy_bcrypt_password(
    client: AsyncClient, session: AsyncSession
):
    """A user whose stored hash predates the argon2 migration should still
    log in successfully, and the hash should be rewritten as argon2id on
    the way out so the bcrypt verify path eventually disappears for active
    users.
    """
    import bcrypt as _bcrypt

    password = "legacy-bcrypt-password"
    legacy_hash = _bcrypt.hashpw(password.encode("utf-8"), _bcrypt.gensalt()).decode(
        "utf-8"
    )
    assert legacy_hash.startswith("$2"), "test setup expected a real bcrypt hash"

    user = User(
        email_hash=hash_email("legacy@example.com"),
        email_encrypted=encrypt_field("legacy@example.com", SALT_EMAIL),
        full_name="Legacy User",
        hashed_password=legacy_hash,
        status=UserStatus.active,
        email_verified=True,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    response = await client.post(
        "/api/v1/auth/token",
        data={"username": "legacy@example.com", "password": password},
    )
    assert response.status_code == 200

    await session.refresh(user)
    assert user.hashed_password.startswith("$argon2"), (
        "expected legacy bcrypt hash to be rewritten as argon2id after a successful login"
    )

    # Second login must verify against the new argon2 hash.
    response = await client.post(
        "/api/v1/auth/token",
        data={"username": "legacy@example.com", "password": password},
    )
    assert response.status_code == 200


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
async def test_expired_jwt_returns_401(client: AsyncClient, session: AsyncSession):
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

    response = await client.post("/api/v1/auth/logout", headers=get_auth_headers(user))
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
async def test_logout_clears_session_cookie(client: AsyncClient, session: AsyncSession):
    """The logout response must set an expired session_token cookie so
    browsers using HttpOnly cookie auth (the web default) actually
    forget the session."""
    user = await create_user(session)
    response = await client.post("/api/v1/auth/logout", headers=get_auth_headers(user))
    assert response.status_code == 204
    set_cookie = response.headers.get("set-cookie", "")
    assert "session_token=" in set_cookie
    # Starlette's delete_cookie sets Max-Age=0 and an expires in the
    # past. Accept either marker so the assertion is robust.
    assert "Max-Age=0" in set_cookie or "1970" in set_cookie


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.parametrize(
    ("public_registration_enabled", "guild_creation_disabled"),
    [(False, False), (True, True)],
)
async def test_oidc_callback_blocks_new_user_when_registration_disabled(
    client: AsyncClient,
    session: AsyncSession,
    monkeypatch,
    public_registration_enabled: bool,
    guild_creation_disabled: bool,
):
    """OIDC callback must honor the same no-invite registration gate as /register."""
    from app.core import config as cfg
    import app.api.v1.public_endpoints.auth as auth_module

    monkeypatch.setattr(
        cfg.settings, "ENABLE_PUBLIC_REGISTRATION", public_registration_enabled
    )
    monkeypatch.setattr(cfg.settings, "DISABLE_GUILD_CREATION", guild_creation_disabled)
    # Must have at least one existing user so is_first_user is False
    await create_user(session)

    valid_state = auth_module._generate_state()

    class _FakeTokenResp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"access_token": "tok", "sub": "sub-new"}

    class _FakeUserinfoResp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {
                "email": "brandnew@example.com",
                "name": "Brand New",
                "sub": "sub-new",
            }

    class _FakeHttpxClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def post(self, *a, **kw):
            return _FakeTokenResp()

        async def get(self, *a, **kw):
            return _FakeUserinfoResp()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _FakeHttpxClient())

    async def _fake_runtime_config(s):
        settings_obj = type(
            "S",
            (),
            {
                "oidc_enabled": True,
                "oidc_issuer": "https://id.example.com",
                "oidc_client_id": "cid",
                "oidc_client_secret_encrypted": None,
                "oidc_scopes": ["openid"],
                "oidc_provider_name": "Test",
                "oidc_role_claim_path": None,
            },
        )()
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


def _patch_oidc_callback(monkeypatch, *, userinfo_profile: dict) -> None:
    """Wire the OIDC callback's httpx + runtime-config deps to a fixed profile.

    Mirrors the harness used by
    ``test_oidc_callback_blocks_new_user_when_registration_disabled`` so the
    callback runs against a deterministic userinfo response.
    """
    import app.api.v1.public_endpoints.auth as auth_module

    class _FakeTokenResp:
        status_code = 200

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"access_token": "tok"}

    class _FakeUserinfoResp:
        status_code = 200

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return userinfo_profile

    class _FakeHttpxClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def post(self, *a, **kw):
            return _FakeTokenResp()

        async def get(self, *a, **kw):
            return _FakeUserinfoResp()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _FakeHttpxClient())

    async def _fake_runtime_config(s):
        settings_obj = type(
            "S",
            (),
            {
                "oidc_enabled": True,
                "oidc_issuer": "https://id.example.com",
                "oidc_client_id": "cid",
                "oidc_client_secret_encrypted": None,
                "oidc_scopes": ["openid"],
                "oidc_provider_name": "Test",
                "oidc_role_claim_path": None,
            },
        )()
        metadata = {
            "authorization_endpoint": "https://id.example.com/auth",
            "token_endpoint": "https://id.example.com/token",
            "userinfo_endpoint": "https://id.example.com/userinfo",
        }
        return settings_obj, metadata

    monkeypatch.setattr(auth_module, "_get_oidc_runtime_config", _fake_runtime_config)


@pytest.mark.integration
@pytest.mark.auth
@pytest.mark.parametrize(
    "verified_claim",
    [
        pytest.param(False, id="email_verified_false"),
        pytest.param(None, id="email_verified_absent"),
    ],
)
async def test_oidc_callback_refuses_existing_account_when_email_unverified(
    client: AsyncClient,
    session: AsyncSession,
    monkeypatch,
    verified_claim,
):
    """SEC-9: an OIDC login must not link to / log into a pre-existing local
    account when the IdP does not assert ``email_verified is True`` for a
    matching email. A false claim (IdP allows unverified emails) and an absent
    claim (e.g. Azure AD) are both refused — fail closed."""
    import app.api.v1.public_endpoints.auth as auth_module

    existing = await create_user(
        session,
        email="victim@example.com",
        full_name="Victim",
        email_verified=False,
    )

    profile = {"email": "victim@example.com", "name": "Attacker", "sub": "sub-attacker"}
    if verified_claim is not None:
        profile["email_verified"] = verified_claim
    _patch_oidc_callback(monkeypatch, userinfo_profile=profile)

    valid_state = auth_module._generate_state()
    response = await client.get(
        "/api/v1/auth/oidc/callback",
        params={"code": "fake-code", "state": valid_state},
        follow_redirects=False,
    )

    assert response.status_code in (302, 307)
    assert "OIDC_EMAIL_UNVERIFIED" in response.headers["location"]
    # No session was issued.
    assert "session_token" not in response.cookies
    # The account must not have been silently promoted to verified, and its
    # profile must not have been overwritten by the attacker-supplied claims.
    await session.refresh(existing)
    assert existing.email_verified is False
    assert existing.full_name == "Victim"


@pytest.mark.integration
@pytest.mark.auth
async def test_oidc_callback_links_existing_account_when_email_verified(
    client: AsyncClient,
    session: AsyncSession,
    monkeypatch,
):
    """SEC-9: the verified flow is unchanged — a matching email with
    ``email_verified=true`` logs into the existing account and promotes an
    unverified local account to verified."""
    import app.api.v1.public_endpoints.auth as auth_module
    from app.core.config import settings as app_config

    existing = await create_user(
        session,
        email="member@example.com",
        full_name="Member",
        email_verified=False,
    )

    profile = {
        "email": "member@example.com",
        "name": "Member",
        "sub": "sub-member",
        "email_verified": True,
    }
    _patch_oidc_callback(monkeypatch, userinfo_profile=profile)

    valid_state = auth_module._generate_state()
    response = await client.get(
        "/api/v1/auth/oidc/callback",
        params={"code": "fake-code", "state": valid_state},
        follow_redirects=False,
    )

    assert response.status_code in (302, 307)
    assert "OIDC_EMAIL_UNVERIFIED" not in response.headers["location"]
    # A session cookie is issued on the verified web flow.
    assert app_config.COOKIE_NAME in response.cookies
    # The verified claim promotes the previously-unverified local account.
    await session.refresh(existing)
    assert existing.email_verified is True


@pytest.mark.integration
@pytest.mark.auth
async def test_oidc_login_rejects_non_https_authorization_endpoint(
    client: AsyncClient,
    monkeypatch,
):
    """A discovery doc whose authorization_endpoint isn't an absolute https
    URL must not be used as a redirect target (CodeQL py/url-redirection)."""
    import app.api.v1.public_endpoints.auth as auth_module

    async def _fake_runtime_config(s):
        settings_obj = type(
            "S",
            (),
            {
                "oidc_enabled": True,
                "oidc_issuer": "https://id.example.com",
                "oidc_client_id": "cid",
                "oidc_client_secret_encrypted": None,
                "oidc_scopes": ["openid"],
                "oidc_provider_name": "Test",
            },
        )()
        metadata = {
            "authorization_endpoint": "http://evil.example.com/auth",
            "token_endpoint": "https://id.example.com/token",
        }
        return settings_obj, metadata

    monkeypatch.setattr(auth_module, "_get_oidc_runtime_config", _fake_runtime_config)

    response = await client.get("/api/v1/auth/oidc/login", follow_redirects=False)

    assert response.status_code == 500
    assert response.json()["detail"] == "OIDC_METADATA_INCOMPLETE"


@pytest.mark.integration
@pytest.mark.auth
async def test_oidc_login_rejects_null_authorization_endpoint(
    client: AsyncClient,
    monkeypatch,
):
    """A non-string (e.g. null) authorization_endpoint must surface the clean
    OIDC_METADATA_INCOMPLETE error, not an uncaught urlsplit TypeError."""
    import app.api.v1.public_endpoints.auth as auth_module

    async def _fake_runtime_config(s):
        settings_obj = type(
            "S",
            (),
            {
                "oidc_enabled": True,
                "oidc_issuer": "https://id.example.com",
                "oidc_client_id": "cid",
                "oidc_client_secret_encrypted": None,
                "oidc_scopes": ["openid"],
                "oidc_provider_name": "Test",
            },
        )()
        metadata = {
            "authorization_endpoint": None,
            "token_endpoint": "https://id.example.com/token",
        }
        return settings_obj, metadata

    monkeypatch.setattr(auth_module, "_get_oidc_runtime_config", _fake_runtime_config)

    response = await client.get("/api/v1/auth/oidc/login", follow_redirects=False)

    assert response.status_code == 500
    assert response.json()["detail"] == "OIDC_METADATA_INCOMPLETE"


@pytest.mark.integration
@pytest.mark.auth
async def test_oidc_login_redirects_to_https_authorization_endpoint(
    client: AsyncClient,
    monkeypatch,
):
    """Happy path: an https authorization_endpoint is used as the redirect."""
    import app.api.v1.public_endpoints.auth as auth_module

    async def _fake_runtime_config(s):
        settings_obj = type(
            "S",
            (),
            {
                "oidc_enabled": True,
                "oidc_issuer": "https://id.example.com",
                "oidc_client_id": "cid",
                "oidc_client_secret_encrypted": None,
                "oidc_scopes": ["openid"],
                "oidc_provider_name": "Test",
            },
        )()
        metadata = {
            "authorization_endpoint": "https://id.example.com/auth",
            "token_endpoint": "https://id.example.com/token",
        }
        return settings_obj, metadata

    monkeypatch.setattr(auth_module, "_get_oidc_runtime_config", _fake_runtime_config)

    response = await client.get("/api/v1/auth/oidc/login", follow_redirects=False)

    assert response.status_code in (302, 307)
    assert response.headers["location"].startswith("https://id.example.com/auth?")


# --- Password policy -------------------------------------------------


@pytest.mark.integration
@pytest.mark.auth
async def test_register_rejects_password_shorter_than_minimum(client: AsyncClient):
    """11-char passwords (the previous loose default in our own tests)
    must now be rejected. Locks down the new NIST-aligned 12-char floor."""
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "tooshort@example.com",
            "full_name": "Too Short",
            "password": "elevenchars",  # 11 chars
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "PASSWORD_TOO_SHORT"


@pytest.mark.integration
@pytest.mark.auth
async def test_register_rejects_breached_password(client: AsyncClient, monkeypatch):
    """A password that passes the length floor but appears in HIBP must
    be rejected with the BREACHED code, not silently accepted."""
    from app.services import hibp as hibp_module

    async def _breached(_pw: str) -> bool:
        return True

    monkeypatch.setattr(hibp_module, "is_password_breached", _breached)

    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "breached@example.com",
            "full_name": "Breached",
            "password": "long-enough-but-pwned",
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "PASSWORD_BREACHED"


@pytest.mark.integration
@pytest.mark.auth
async def test_register_accepts_compliant_password(client: AsyncClient):
    """Sanity check: a 12+ char password with HIBP disabled (default in
    tests) succeeds, so the policy gate isn't accidentally rejecting
    everything."""
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "ok@example.com",
            "full_name": "OK User",
            "password": "twelve-chars",  # exactly 12 chars
        },
    )
    assert response.status_code == 201


@pytest.mark.integration
@pytest.mark.auth
async def test_login_grandfathers_existing_short_password(
    client: AsyncClient, session: AsyncSession
):
    """Users whose hashes were written before the policy landed must keep
    logging in. The policy applies only to flows that *set* a new
    password — never to ``verify_password`` on the login path."""
    short_password = "shortpw"  # 7 chars — would fail the policy if applied
    user = User(
        email_hash=hash_email("legacy-short@example.com"),
        email_encrypted=encrypt_field("legacy-short@example.com", SALT_EMAIL),
        full_name="Legacy Short",
        hashed_password=get_password_hash(short_password),
        status=UserStatus.active,
        email_verified=True,
    )
    session.add(user)
    await session.commit()

    response = await client.post(
        "/api/v1/auth/token",
        data={"username": "legacy-short@example.com", "password": short_password},
    )
    assert response.status_code == 200
    assert "access_token" in response.json()


@pytest.mark.integration
@pytest.mark.auth
async def test_password_reset_rejects_short_password(
    client: AsyncClient, session: AsyncSession
):
    """Password reset must run the same policy as registration. The
    reset token must NOT be consumed when the candidate fails — a
    failed attempt would otherwise burn the user's only reset link."""
    from app.models.user_token import UserToken, UserTokenPurpose
    from app.services import user_tokens

    user = await create_user(session, email="reset@example.com")
    token = await user_tokens.create_token(
        session,
        user_id=user.id,
        purpose=UserTokenPurpose.password_reset,
    )

    response = await client.post(
        "/api/v1/auth/password/reset",
        json={"token": token, "password": "elevenchars"},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "PASSWORD_TOO_SHORT"

    # Reset token must still be redeemable — we failed before consuming it.
    # Tokens are stored hashed (SEC-13), so look the row up by its hash.
    from sqlmodel import select

    from app.services.user_tokens import _hash_token

    fresh = (
        await session.exec(
            select(UserToken).where(UserToken.token == _hash_token(token))
        )
    ).one()
    assert fresh.consumed_at is None


@pytest.mark.integration
@pytest.mark.auth
async def test_password_reset_revokes_sessions_and_device_tokens(
    client: AsyncClient, session: AsyncSession
):
    """A successful forgot-password reset must invalidate the user's
    outstanding JWT (token_version bump) and active device tokens, so a
    stolen-but-unexpired credential can't survive the reset."""
    from sqlmodel import select

    from app.models.user_token import UserToken, UserTokenPurpose
    from app.services import user_tokens

    user = await create_user(session, email="reset-revoke@example.com")
    old_jwt = get_auth_token(user)
    device_token = await user_tokens.create_device_token(
        session, user_id=user.id, device_name="Reset phone"
    )
    reset_token = await user_tokens.create_token(
        session,
        user_id=user.id,
        purpose=UserTokenPurpose.password_reset,
    )

    response = await client.post(
        "/api/v1/auth/password/reset",
        json={"token": reset_token, "password": "brand-new-secret-123"},
    )
    assert response.status_code == 200

    # Old JWT rejected (token_version bumped).
    post_jwt = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {old_jwt}"},
    )
    assert post_jwt.status_code == 401

    # Device token rejected (consumed).
    post_device = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"DeviceToken {device_token}"},
    )
    assert post_device.status_code == 401

    token_row = (
        await session.exec(
            select(UserToken).where(
                UserToken.user_id == user.id,
                UserToken.purpose == UserTokenPurpose.device_auth,
            )
        )
    ).one()
    assert token_row.consumed_at is not None


@pytest.mark.integration
@pytest.mark.auth
async def test_register_rolls_back_when_guild_seed_fails(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """A DB-side guild-seed failure mid-registration rolls back the whole
    registration — no orphaned user or guild rows — and returns 500.

    The seed failure here aborts the transaction, so registration must roll back
    before its cleanup queries run; otherwise they raise PendingRollbackError and
    the already-committed user + guild rows are stranded.
    """
    from sqlalchemy import text
    from sqlmodel import select

    from app.models.guild import Guild
    from app.services import guilds as guilds_service

    async def _boom(seed_session, *args, **kwargs):
        # Simulate a real DB failure: abort the transaction like a failing query
        # would, so the cleanup path MUST rollback before it can delete anything.
        await seed_session.execute(text("SELECT * FROM does_not_exist_xyz"))

    monkeypatch.setattr(guilds_service, "seed_guild_content", _boom)

    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "seedfail@example.com",
            "full_name": "Seed Fail",
            "password": "securepassword123",
        },
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "UNABLE_TO_CREATE_USER"

    # Neither the user nor its guild may survive a failed registration.
    users = (
        await session.exec(
            select(User).where(User.email_hash == hash_email("seedfail@example.com"))
        )
    ).all()
    assert users == [], "user row must be rolled back when guild seeding fails"
    guilds = (await session.exec(select(Guild))).all()
    assert guilds == [], "guild row must be rolled back when guild seeding fails"
