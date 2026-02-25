import base64
from datetime import datetime, timezone
import hashlib
import hmac
import logging
import secrets
import time
from typing import Any, Annotated
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.api.deps import SessionDep, get_current_active_user
from app.db.session import get_admin_session
from app.core.config import settings
from sqlmodel.ext.asyncio.session import AsyncSession
from app.core.rate_limit import limiter
from app.core.encryption import decrypt_field, encrypt_token, SALT_OIDC_CLIENT_SECRET
from app.core.messages import AuthMessages, OidcMessages
from app.core.security import create_access_token, get_password_hash, verify_password
from app.models.user import User, UserRole
from app.models.guild import GuildRole
from app.schemas.token import Token
from app.schemas.auth import (
    DeviceTokenInfo,
    DeviceTokenRequest,
    DeviceTokenResponse,
    PasswordResetRequest,
    PasswordResetSubmit,
    VerificationConfirmRequest,
    VerificationSendResponse,
)
from app.schemas.user import UserCreate, UserRead
from app.db.session import AdminSessionLocal
from app.services import app_settings as app_settings_service
from app.services import email as email_service
from app.services import user_tokens
from app.services import initiatives as initiatives_service
from app.services import guilds as guilds_service
from app.services.oidc_sync import extract_claim_values, sync_oidc_assignments
from app.models.user_token import UserTokenPurpose

router = APIRouter()
AdminSessionDep = Annotated[AsyncSession, Depends(get_admin_session)]

STATE_TTL_SECONDS = 600
_oidc_metadata_cache: dict[str, dict[str, Any]] = {}
logger = logging.getLogger(__name__)


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/15minutes")
async def register_user(
    request: Request,
    user_in: UserCreate,
    session: AdminSessionDep,
    invite_code: str | None = Query(default=None),
) -> User:
    normalized_invite = (invite_code or "").strip() or None

    smtp_configured = False
    try:
        app_settings = await app_settings_service.get_app_settings(session)
        smtp_configured = bool(app_settings.smtp_host and app_settings.smtp_from_address)

        normalized_email = user_in.email.lower().strip()
        statement = select(User).where(func.lower(User.email) == normalized_email)
        existing = await session.exec(statement)
        if existing.one_or_none():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.EMAIL_ALREADY_REGISTERED)

        user_count_result = await session.exec(select(func.count(User.id)))
        user_count = user_count_result.one()
        is_first_user = user_count == 0

        # Block registration if:
        # - Public registration disabled OR guild creation disabled
        # - AND no invite code provided
        # - AND not the first user (bootstrap always allowed)
        if (not settings.ENABLE_PUBLIC_REGISTRATION or settings.DISABLE_GUILD_CREATION) and not normalized_invite and not is_first_user:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=AuthMessages.REGISTRATION_REQUIRES_INVITE)

        if normalized_invite:
            user_role = UserRole.member
        else:
            user_role = UserRole.admin if is_first_user else UserRole.member

        user = User(
            email=normalized_email,
            full_name=user_in.full_name,
            hashed_password=get_password_hash(user_in.password),
            role=user_role,
            is_active=True,
            email_verified=is_first_user or not smtp_configured,
        )
        session.add(user)
        await session.flush()

        if normalized_invite:
            try:
                guild = await guilds_service.redeem_invite_for_user(
                    session,
                    code=normalized_invite,
                    user=user,
                )
            except guilds_service.GuildInviteError as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
            guild_role = GuildRole.member
        else:
            guild_name_source = (user.full_name or user.email.split("@", 1)[0]).strip() or user.email
            guild_name = guild_name_source if guild_name_source.lower().endswith("guild") else f"{guild_name_source}'s Guild"
            guild = await guilds_service.create_guild(
                session,
                name=guild_name,
                creator=user,
            )
            guild_role = GuildRole.admin
            await initiatives_service.ensure_default_initiative(session, user, guild_id=guild.id)

        await guilds_service.ensure_membership(
            session,
            guild_id=guild.id,
            user_id=user.id,
            role=guild_role,
        )
        await session.commit()
    except IntegrityError as exc:  # pragma: no cover
        await session.rollback()
        logger.exception("Failed to register %s due to integrity error", user_in.email)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.UNABLE_TO_CREATE_USER) from exc

    await session.refresh(user)

    await initiatives_service.load_user_initiative_roles(session, [user])

    if smtp_configured and not user.email_verified:
        try:
            token = await user_tokens.create_token(
                session,
                user_id=user.id,
                purpose=UserTokenPurpose.email_verification,
                expires_minutes=60 * 24,
            )
            await email_service.send_verification_email(session, user, token)
        except email_service.EmailNotConfiguredError:
            logger.warning("SMTP not configured; skipping verification email for %s", user.email)
        except RuntimeError as exc:  # pragma: no cover
            logger.error("Failed to send verification email: %s", exc)
    return user


@router.get("/bootstrap")
async def bootstrap_status(session: SessionDep) -> dict[str, bool]:
    result = await session.exec(select(func.count(User.id)))
    count = result.one()
    return {
        "has_users": count > 0,
        "public_registration_enabled": settings.ENABLE_PUBLIC_REGISTRATION,
    }


@router.post("/token", response_model=Token)
@limiter.limit("5/15minutes")
async def login_access_token(
    request: Request,
    session: SessionDep,
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> Token:
    normalized_email = form_data.username.lower().strip()
    statement = select(User).where(func.lower(User.email) == normalized_email)
    result = await session.exec(statement)
    user = result.one_or_none()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.INCORRECT_CREDENTIALS)

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.INACTIVE_USER)
    if not user.email_verified:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.EMAIL_NOT_VERIFIED)

    access_token = create_access_token(subject=str(user.id))
    return Token(access_token=access_token)


@router.post("/device-token", response_model=DeviceTokenResponse)
@limiter.limit("5/15minutes")
async def create_device_token(
    request: Request,
    session: SessionDep,
    payload: DeviceTokenRequest,
) -> DeviceTokenResponse:
    """
    Create a long-lived device token for mobile app authentication.
    Device tokens do not expire and can be used instead of JWT tokens.
    """
    normalized_email = payload.email.lower().strip()
    statement = select(User).where(func.lower(User.email) == normalized_email)
    result = await session.exec(statement)
    user = result.one_or_none()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.INCORRECT_CREDENTIALS)

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.INACTIVE_USER)
    if not user.email_verified:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.EMAIL_NOT_VERIFIED)

    device_token = await user_tokens.create_device_token(
        session,
        user_id=user.id,
        device_name=payload.device_name.strip(),
    )
    return DeviceTokenResponse(device_token=device_token)


@router.get("/device-tokens", response_model=list[DeviceTokenInfo])
async def list_device_tokens(
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> list[DeviceTokenInfo]:
    """List all device tokens for the current user."""
    tokens = await user_tokens.get_user_device_tokens(session, user_id=current_user.id)
    return [
        DeviceTokenInfo(
            id=t.id,
            device_name=t.device_name,
            created_at=t.created_at,
        )
        for t in tokens
    ]


@router.delete("/device-tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_device_token(
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    token_id: int,
) -> None:
    """Revoke a device token."""
    success = await user_tokens.revoke_device_token(
        session,
        token_id=token_id,
        user_id=current_user.id,
    )
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.TOKEN_NOT_FOUND)


def _generate_state(mobile: bool = False, device_name: str = "") -> str:
    timestamp = str(int(time.time()))
    mobile_flag = "1" if mobile else "0"
    encoded_device_name = base64.urlsafe_b64encode(device_name.encode()).decode()
    code_verifier = secrets.token_urlsafe(32)
    payload = f"{timestamp}.{mobile_flag}.{encoded_device_name}.{code_verifier}"
    signature = hmac.new(settings.SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def _validate_state(value: str | None) -> tuple[bool, bool, str, str]:
    """Validate OIDC state parameter and extract mobile flag, device name, and code verifier.

    Returns:
        Tuple of (is_valid, is_mobile, device_name, code_verifier)
    """
    if not value:
        return (False, False, "", "")
    try:
        parts = value.split(".")
        if len(parts) != 5:
            return (False, False, "", "")
        ts_str, mobile_flag, encoded_device_name, code_verifier, signature = parts
    except ValueError:
        return (False, False, "", "")
    payload = f"{ts_str}.{mobile_flag}.{encoded_device_name}.{code_verifier}"
    expected = hmac.new(settings.SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return (False, False, "", "")
    try:
        ts = int(ts_str)
    except ValueError:
        return (False, False, "", "")
    if int(time.time()) - ts > STATE_TTL_SECONDS:
        return (False, False, "", "")
    try:
        device_name = base64.urlsafe_b64decode(encoded_device_name.encode()).decode()
    except Exception:
        device_name = ""
    return (True, mobile_flag == "1", device_name, code_verifier)


def _backend_redirect_uri() -> str:
    base = settings.APP_URL.rstrip("/")
    return f"{base}{settings.API_V1_STR}/auth/oidc/callback"


def _frontend_redirect_uri() -> str:
    base = settings.APP_URL.rstrip("/")
    return f"{base}/oidc/callback"


async def _fetch_oidc_metadata(issuer_url: str) -> dict[str, Any]:
    # Normalize: strip trailing well-known path if present, then re-append
    normalized = issuer_url.rstrip("/")
    well_known_suffix = "/.well-known/openid-configuration"
    if normalized.endswith(well_known_suffix):
        normalized = normalized[: -len(well_known_suffix)]
    discovery_url = f"{normalized}{well_known_suffix}"
    if discovery_url in _oidc_metadata_cache:
        return _oidc_metadata_cache[discovery_url]
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(discovery_url)
        resp.raise_for_status()
        metadata = resp.json()
    _oidc_metadata_cache[discovery_url] = metadata
    return metadata


async def _get_oidc_runtime_config(session: SessionDep) -> tuple[Any, dict[str, Any]]:
    app_settings = await app_settings_service.get_app_settings(session)
    if not (
        app_settings.oidc_enabled
        and app_settings.oidc_issuer
        and app_settings.oidc_client_id
        and app_settings.oidc_client_secret_encrypted
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=OidcMessages.OIDC_NOT_ENABLED)

    metadata = await _fetch_oidc_metadata(app_settings.oidc_issuer)
    required = ["authorization_endpoint", "token_endpoint"]
    for key in required:
        if key not in metadata:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=OidcMessages.OIDC_METADATA_INCOMPLETE)
    return app_settings, metadata


@router.get("/oidc/status")
async def oidc_status(request: Request, session: SessionDep) -> dict[str, Any]:
    app_settings = await app_settings_service.get_app_settings(session)
    enabled = bool(
        app_settings.oidc_enabled
        and app_settings.oidc_issuer
        and app_settings.oidc_client_id
        and app_settings.oidc_client_secret_encrypted
    )
    login_url = None
    provider_name = None
    if enabled:
        login_url = f"{settings.API_V1_STR}/auth/oidc/login"
        provider_name = app_settings.oidc_provider_name
    return {"enabled": enabled, "login_url": login_url, "provider_name": provider_name}


@router.get("/oidc/login")
@limiter.limit("20/minute")
async def oidc_login(
    request: Request,
    session: SessionDep,
    mobile: bool = Query(default=False),
    device_name: str = Query(default="Mobile Device"),
) -> RedirectResponse:
    app_settings, metadata = await _get_oidc_runtime_config(session)
    state = _generate_state(mobile=mobile, device_name=device_name if mobile else "")
    # Extract code_verifier from state to compute PKCE challenge
    state_parts = state.split(".")
    code_verifier = state_parts[3]
    code_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    params = {
        "client_id": app_settings.oidc_client_id,
        "response_type": "code",
        "scope": " ".join(app_settings.oidc_scopes or ["openid"]),
        "redirect_uri": _backend_redirect_uri(),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    authorize_url = f"{metadata['authorization_endpoint']}?{urlencode(params)}"
    return RedirectResponse(authorize_url)


def _mobile_redirect_uri() -> str:
    return "initiative://oidc/callback"


def _error_redirect(is_mobile: bool | None, error: str) -> RedirectResponse:
    """Redirect to app/frontend with error instead of returning JSON."""
    params = {"error": error}
    if is_mobile:
        url = f"{_mobile_redirect_uri()}?{urlencode(params)}"
    else:
        url = f"{_frontend_redirect_uri()}?{urlencode(params)}"
    return RedirectResponse(url)


@router.get("/oidc/callback")
@limiter.limit("20/minute")
async def oidc_callback(
    request: Request,
    session: SessionDep,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
):
    if not code:
        return _error_redirect(None, "missing_authorization_code")
    is_valid, is_mobile, device_name, code_verifier = _validate_state(state)
    if not is_valid:
        return _error_redirect(None, "invalid_state")

    app_settings, metadata = await _get_oidc_runtime_config(session)
    token_payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": _backend_redirect_uri(),
        "client_id": app_settings.oidc_client_id,
        "client_secret": decrypt_field(app_settings.oidc_client_secret_encrypted, SALT_OIDC_CLIENT_SECRET) if app_settings.oidc_client_secret_encrypted else None,
        "code_verifier": code_verifier,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        token_resp = await client.post(metadata["token_endpoint"], data=token_payload)
        try:
            token_resp.raise_for_status()
        except httpx.HTTPStatusError:
            logger.error(
                "OIDC token request failed: status=%s body=%s",
                token_resp.status_code,
                token_resp.text,
            )
            return _error_redirect(is_mobile, "token_request_failed")
        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            logger.error("OIDC token response missing access_token")
            return _error_redirect(is_mobile, "token_missing_access_token")

        userinfo_endpoint = metadata.get("userinfo_endpoint")
        if not userinfo_endpoint:
            logger.error("OIDC metadata missing userinfo_endpoint")
            return _error_redirect(is_mobile, "userinfo_endpoint_missing")
        userinfo_resp = await client.get(
            userinfo_endpoint,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        try:
            userinfo_resp.raise_for_status()
        except httpx.HTTPStatusError:
            logger.error(
                "OIDC userinfo request failed: status=%s body=%s",
                userinfo_resp.status_code,
                userinfo_resp.text,
            )
            return _error_redirect(is_mobile, "userinfo_request_failed")
        profile = userinfo_resp.json()

    email = profile.get("email")
    if not email:
        sub = profile.get("sub")
        if not sub:
            logger.error("OIDC profile missing both email and sub")
            return _error_redirect(is_mobile, "profile_missing_identity")
        email = f"{sub}@oidc.local"
    normalized_email = email.lower().strip()
    full_name = profile.get("name") or profile.get("preferred_username") or normalized_email
    avatar_url = profile.get("picture")

    statement = select(User).where(func.lower(User.email) == normalized_email)
    result = await session.exec(statement)
    user = result.one_or_none()
    # Extract OIDC refresh token + sub for background sync
    oidc_sub = profile.get("sub")
    refresh_token = token_data.get("refresh_token")
    encrypted_refresh = encrypt_token(refresh_token) if refresh_token else None
    now_utc = datetime.now(timezone.utc)

    if not user:
        random_password = secrets.token_urlsafe(32)
        user = User(
            email=normalized_email,
            full_name=full_name,
            hashed_password=get_password_hash(random_password),
            role=UserRole.member,
            is_active=True,
            avatar_url=avatar_url,
            avatar_base64=None,
            email_verified=True,
            oidc_sub=oidc_sub,
            oidc_refresh_token_encrypted=encrypted_refresh,
            oidc_last_synced_at=now_utc,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
    else:
        updated = False
        if not user.is_active:
            user.is_active = True
            updated = True
        if not user.email_verified:
            user.email_verified = True
            updated = True
        if full_name and user.full_name != full_name:
            user.full_name = full_name
            updated = True
        if avatar_url and user.avatar_url != avatar_url:
            user.avatar_url = avatar_url
            user.avatar_base64 = None
            updated = True
        # Always update OIDC sync fields on login
        if oidc_sub:
            user.oidc_sub = oidc_sub
            updated = True
        if encrypted_refresh is not None:
            user.oidc_refresh_token_encrypted = encrypted_refresh
            updated = True
        user.oidc_last_synced_at = now_utc
        updated = True
        if updated:
            session.add(user)
            await session.commit()
            await session.refresh(user)

    # OIDC claim-to-role sync
    try:
        claim_path = app_settings.oidc_role_claim_path if hasattr(app_settings, "oidc_role_claim_path") else None
        if claim_path:
            # Decode id_token claims (without signature verification — we trust the token endpoint)
            id_token_claims = None
            raw_id_token = token_data.get("id_token")
            if raw_id_token:
                try:
                    import json as _json
                    parts = raw_id_token.split(".")
                    if len(parts) >= 2:
                        payload_b64 = parts[1]
                        payload_b64 += "=" * (-len(payload_b64) % 4)
                        id_token_claims = _json.loads(base64.urlsafe_b64decode(payload_b64))
                except Exception:
                    pass  # id_token decode is best-effort

            claim_values = extract_claim_values(profile, id_token_claims, claim_path)
            async with AdminSessionLocal() as admin_session:
                sync_result = await sync_oidc_assignments(
                    admin_session,
                    user_id=user.id,
                    claim_values=claim_values,
                )
                logger.info(
                    "OIDC sync for %s: +%d/~%d/-%d guilds, +%d/~%d/-%d initiatives",
                    user.email,
                    len(sync_result.guilds_added),
                    len(sync_result.guilds_updated),
                    len(sync_result.guilds_removed),
                    len(sync_result.initiatives_added),
                    len(sync_result.initiatives_updated),
                    len(sync_result.initiatives_removed),
                )
    except Exception:
        logger.exception("OIDC claim sync failed for user %s", user.email)

    if is_mobile:
        device_token = await user_tokens.create_device_token(
            session,
            user_id=user.id,
            device_name=device_name or "Mobile Device",
        )
        redirect_params = {"token": device_token, "token_type": "device_token"}
        redirect_url = f"{_mobile_redirect_uri()}?{urlencode(redirect_params)}"
    else:
        app_token = create_access_token(subject=str(user.id))
        redirect_params = {"token": app_token}
        redirect_url = f"{_frontend_redirect_uri()}?{urlencode(redirect_params)}"
    return RedirectResponse(redirect_url)


@router.post("/verification/send", response_model=VerificationSendResponse)
@limiter.limit("5/15minutes")
async def resend_verification_email(
    request: Request,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> VerificationSendResponse:
    if current_user.email_verified:
        return VerificationSendResponse(status="already_verified")
    try:
        token = await user_tokens.create_token(
            session,
            user_id=current_user.id,
            purpose=UserTokenPurpose.email_verification,
            expires_minutes=60 * 24,
        )
        await email_service.send_verification_email(session, current_user, token)
    except email_service.EmailNotConfiguredError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.SMTP_NOT_CONFIGURED) from None
    except RuntimeError as exc:  # pragma: no cover
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return VerificationSendResponse(status="sent")


@router.post("/verification/confirm", response_model=VerificationSendResponse)
@limiter.limit("5/15minutes")
async def confirm_verification(request: Request, session: SessionDep, payload: VerificationConfirmRequest) -> VerificationSendResponse:
    record = await user_tokens.consume_token(
        session,
        token=payload.token,
        purpose=UserTokenPurpose.email_verification,
    )
    if not record:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.INVALID_OR_EXPIRED_TOKEN)
    user_stmt = select(User).where(User.id == record.user_id)
    user_result = await session.exec(user_stmt)
    user = user_result.one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND)
    if not user.email_verified:
        user.email_verified = True
        user.updated_at = datetime.now(timezone.utc)
        session.add(user)
        await session.commit()
        await session.refresh(user)
    return VerificationSendResponse(status="verified")


@router.post("/password/forgot", response_model=VerificationSendResponse)
@limiter.limit("5/15minutes")
async def request_password_reset(request: Request, payload: PasswordResetRequest, session: SessionDep) -> VerificationSendResponse:
    normalized_email = payload.email.lower().strip()
    stmt = select(User).where(func.lower(User.email) == normalized_email)
    result = await session.exec(stmt)
    user = result.one_or_none()
    if not user or not user.is_active:
        return VerificationSendResponse(status="sent")
    try:
        token = await user_tokens.create_token(
            session,
            user_id=user.id,
            purpose=UserTokenPurpose.password_reset,
            expires_minutes=60,
        )
        await email_service.send_password_reset_email(session, user, token)
    except email_service.EmailNotConfiguredError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.SMTP_NOT_CONFIGURED) from None
    except RuntimeError as exc:  # pragma: no cover
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return VerificationSendResponse(status="sent")


@router.post("/password/reset", response_model=VerificationSendResponse)
@limiter.limit("5/15minutes")
async def reset_password(request: Request, payload: PasswordResetSubmit, session: SessionDep) -> VerificationSendResponse:
    record = await user_tokens.consume_token(
        session,
        token=payload.token,
        purpose=UserTokenPurpose.password_reset,
    )
    if not record:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.INVALID_OR_EXPIRED_TOKEN)
    stmt = select(User).where(User.id == record.user_id)
    result = await session.exec(stmt)
    user = result.one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND)
    user.hashed_password = get_password_hash(payload.password)
    if not user.email_verified:
        user.email_verified = True
    user.updated_at = datetime.now(timezone.utc)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return VerificationSendResponse(status="reset")
