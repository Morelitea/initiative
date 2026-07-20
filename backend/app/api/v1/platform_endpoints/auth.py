from datetime import datetime, timezone
import logging
from typing import Any, Annotated
from urllib.parse import urlencode

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import delete as sql_delete, select

from app.api.deps import SessionDep, get_current_active_user, get_current_user_optional
from app.db.session import get_admin_session
from app.core.config import API_V1_STR, settings
from sqlmodel.ext.asyncio.session import AsyncSession
from app.core import auth_context
from app.core.rate_limit import get_inet_client_ip, limiter
from app.core.encryption import (
    decrypt_field,
    encrypt_field,
    hash_email,
    SALT_EMAIL,
    SALT_OIDC_CLIENT_SECRET,
)
from app.core.messages import AuthMessages, GuildMessages, OidcMessages
from app.core.password_policy import enforce_password_policy
from app.core.security import (
    REFRESH_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    create_access_token,
    create_upload_token,
    get_password_hash,
    mint_access_token,
    password_needs_rehash,
    verify_password,
)
from app.core.user_input_validators import (
    is_safe_next_path,
    is_valid_provider_slug,
    normalize_timezone,
)
from app.api.v1.platform_endpoints.session_cookies import (
    REFRESH_COOKIE_PATH,
    clear_refresh_cookie,
    set_refresh_cookie,
    set_session_cookie,
)
from app.models.platform.app_setting import AppSetting, AuthScope
from app.models.platform.auth_provider import AuthProvider
from app.models.platform.auth_provider_secret import AuthProviderSecret
from app.models.platform.user import User, UserRole, UserStatus
from app.models.platform.guild import Guild, GuildRole
from app.schemas.platform.token import Token
from app.schemas.platform.auth import (
    DeviceTokenInfo,
    DeviceTokenRequest,
    DeviceTokenResponse,
    LoginProviderEntry,
    LoginProvidersResponse,
    PasswordResetRequest,
    PasswordResetSubmit,
    UploadTokenResponse,
    VerificationConfirmRequest,
    VerificationSendResponse,
)
from app.schemas.platform.user import UserCreate, UserRead
from app.db.session import AdminSessionLocal
from app.services.auth import sessions as session_service
from app.services.auth.identity import (
    ResolutionOutcome,
    link_identity,
    resolve_oidc_identity,
    set_identity_refresh_token,
)
from app.services.auth.oidc.discovery import OidcDiscovery
from app.services.auth.oidc.flow_state import FlowStateError, decode_flow_state
from app.services.auth.oidc.jwks import JwksResolver
from app.services.auth.oidc.provider import (
    OidcClientConfig,
    OidcFlowError,
    OidcProvider,
)
from app.services.auth.platform_provider import (
    PLATFORM_OIDC_SLUG,
    ensure_platform_provider,
    get_platform_provider,
    is_login_ready,
)
from app.services.auth.sessions import RefreshOutcome
from app.services.platform import app_settings as app_settings_service
from app.services import email as email_service
from app.services.platform import user_tokens
from app.services.platform import guilds as guilds_service
from app.services.oidc_sync import extract_claim_values, sync_oidc_assignments
from app.models.platform.user_token import UserTokenPurpose

router = APIRouter()
AdminSessionDep = Annotated[AsyncSession, Depends(get_admin_session)]

logger = logging.getLogger(__name__)

# Shared across requests so provider discovery + JWKS caching work; the
# per-request OidcProvider is just configuration composed around them.
_oidc_discovery = OidcDiscovery()
_oidc_jwks = JwksResolver()


def _refresh_rejected(detail: str) -> JSONResponse:
    """A 401 for a failed refresh that also clears the stale auth cookies.

    The clearing must ride on the *returned* response: mutating the injected
    ``Response`` and then ``raise``-ing an ``HTTPException`` drops the Set-Cookie
    headers (FastAPI builds a fresh response for the exception), so the browser
    would keep resending a dead refresh token. Returning the response directly is
    the only way the delete-cookie headers reach the client."""
    response = JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"detail": detail},
        headers={"WWW-Authenticate": "Bearer"},
    )
    clear_refresh_cookie(response)
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    return response


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
        smtp_configured = bool(
            app_settings.smtp_host and app_settings.smtp_from_address
        )

        normalized_email = user_in.email.lower().strip()
        statement = select(User).where(User.email_hash == hash_email(normalized_email))
        existing = await session.exec(statement)
        if existing.one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=AuthMessages.EMAIL_ALREADY_REGISTERED,
            )

        user_count_result = await session.exec(select(func.count(User.id)))
        user_count = user_count_result.one()
        is_first_user = user_count == 0

        # Block registration if:
        # - Public registration disabled OR guild creation disabled
        # - AND no invite code provided
        # - AND not the first user (bootstrap always allowed)
        if (
            (not settings.ENABLE_PUBLIC_REGISTRATION or settings.DISABLE_GUILD_CREATION)
            and not normalized_invite
            and not is_first_user
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=AuthMessages.REGISTRATION_REQUIRES_INVITE,
            )

        # Captcha gate (no-op when ``CAPTCHA_PROVIDER`` isn't configured;
        # see ``app.services.captcha``). Skipped on the bootstrap
        # first-user path because there's no bot economics on a fresh
        # deployment with zero users — and operators shouldn't be
        # locked out by a captcha they haven't fully wired up yet.
        # ``get_real_client_ip`` honours ``X-Forwarded-For`` only when
        # ``BEHIND_PROXY`` is on, so when the API sits behind nginx /
        # ALB / Cloudflare the captcha provider sees the real client IP
        # for its anti-abuse heuristics — not the proxy's.
        if not is_first_user:
            from app.core.rate_limit import get_real_client_ip
            from app.services import captcha as captcha_service

            await captcha_service.verify_or_raise(
                user_in.captcha_token,
                remote_ip=get_real_client_ip(request),
            )

        # Enforce password policy (NIST 800-63B: length + HIBP breach
        # check) before we hash. Raises 422 PASSWORD_TOO_SHORT /
        # PASSWORD_BREACHED on failure.
        await enforce_password_policy(user_in.password)

        if normalized_invite:
            user_role = UserRole.member
        else:
            # The very first user bootstraps the platform as owner — the only
            # role that can manage app-wide configuration (OIDC, SMTP, …).
            user_role = UserRole.owner if is_first_user else UserRole.member

        # Validate the optional browser-supplied IANA timezone via the
        # same helper used by self-update / admin-update. Returns
        # ``None`` when the field is omitted or blank, in which case
        # we simply don't pass ``timezone`` to the model and the
        # column default ``"UTC"`` applies.
        normalized_timezone = normalize_timezone(user_in.timezone)

        user_kwargs: dict[str, Any] = dict(
            email_hash=hash_email(normalized_email),
            email_encrypted=encrypt_field(normalized_email, SALT_EMAIL),
            full_name=user_in.full_name,
            hashed_password=get_password_hash(user_in.password),
            role=user_role,
            status=UserStatus.active,
            email_verified=is_first_user or not smtp_configured,
        )
        if normalized_timezone is not None:
            user_kwargs["timezone"] = normalized_timezone
        user = User(**user_kwargs)
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
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
                ) from exc
            except guilds_service.GuildCapacityError as exc:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
                ) from exc
            # Joining an existing (already-provisioned) guild — just record membership.
            await guilds_service.ensure_membership(
                session,
                guild_id=guild.id,
                user_id=user.id,
                role=GuildRole.member,
            )
            await session.commit()
        else:
            guild_name_source = (
                user.full_name or user.email.split("@", 1)[0]
            ).strip() or user.email
            guild_name = (
                guild_name_source
                if guild_name_source.lower().endswith("guild")
                else f"{guild_name_source}'s Guild"
            )
            # create_guild makes the shared rows (guild + admin membership). Commit
            # them — together with the user — then provision + seed the schema
            # (settings + default initiative). On failure, undo the whole registration.
            guild = await guilds_service.create_guild(
                session, name=guild_name, creator=user
            )
            await session.commit()
            # Capture ids before the seed: the rollback in the failure path expires
            # the ORM objects, so reading guild.id / user.id afterwards would reload.
            guild_id = guild.id
            user_id = user.id
            try:
                await guilds_service.seed_guild_content(
                    session, guild_id=guild_id, creator=user
                )
                await session.commit()
            except Exception:
                from contextlib import suppress as _suppress

                from app.db.schema_provisioning import deprovision_guild

                logger.exception(
                    "Guild %s setup failed during registration; rolling back", guild_id
                )
                # Roll back FIRST. If the seed failed on a DB error the session is
                # aborted; without this rollback every cleanup query below raises
                # PendingRollbackError and the already-committed user + guild rows
                # are stranded. Rollback also reverts the seed's SET ROLE (Postgres
                # SET is transactional) so deprovision can DROP the role; this is an
                # system-engine session (BYPASSRLS), so removing the shared rows isn't filtered.
                await session.rollback()
                with _suppress(Exception):
                    await deprovision_guild(guild_id)
                # Bulk DELETEs by captured id (CASCADE clears the roster) — never
                # session.delete (walks ORM relationships with async-unsafe sync
                # loads) and never the expired ORM objects (would reload).
                await session.exec(sql_delete(Guild).where(Guild.id == guild_id))
                await session.exec(sql_delete(User).where(User.id == user_id))
                await session.commit()
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=AuthMessages.UNABLE_TO_CREATE_USER,
                )
    except IntegrityError as exc:  # pragma: no cover
        await session.rollback()
        logger.exception("Failed to register user due to integrity error")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.UNABLE_TO_CREATE_USER,
        ) from exc

    await session.refresh(user)

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
            logger.warning(
                "SMTP not configured; skipping verification email for user %s", user.id
            )
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
    response: Response,
    session: SessionDep,
    admin_session: AdminSessionDep,
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> Token:
    normalized_email = form_data.username.lower().strip()
    statement = select(User).where(User.email_hash == hash_email(normalized_email))
    result = await session.exec(statement)
    user = result.one_or_none()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.INCORRECT_CREDENTIALS,
        )

    if user.status != UserStatus.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.INACTIVE_USER
        )
    if not user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.EMAIL_NOT_VERIFIED,
        )

    if password_needs_rehash(user.hashed_password):
        # Best-effort: a transient DB error or argon2 hashing failure here
        # must not turn a successful authentication into a 500. The next
        # login will retry the upgrade, and the legacy bcrypt hash keeps
        # working until then.
        try:
            user.hashed_password = get_password_hash(form_data.password)
            session.add(user)
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("Failed to upgrade password hash for user %s", user.id)

    # The new login model end-to-end (history/auth-detailed-design.md §3): the
    # server-side session is load-bearing — the access token carries sid/amr/sat
    # and lives AUTH_ACCESS_TTL_MINUTES; the rotating refresh cookie carries the
    # session (the SPA renews silently). Session writes run on the system engine
    # (auth_sessions is app_admin-only).
    #
    # Fallback: a transient session-store failure must not block sign-in — issue
    # a legacy long-lived token instead (the dual-verify window accepts both);
    # that session just can't renew silently.
    try:
        issued = await session_service.create_session(
            admin_session,
            user_id=user.id,
            amr=["pwd"],
            satisfied_providers=[],
            user_agent=request.headers.get("user-agent"),
            ip=get_inet_client_ip(request),
        )
        await admin_session.commit()
    except Exception:
        await admin_session.rollback()
        logger.exception(
            "Failed to establish refresh session for user %s; "
            "falling back to a legacy access token",
            user.id,
        )
        access_token = create_access_token(
            subject=str(user.id), token_version=user.token_version
        )
        set_session_cookie(
            response, access_token, max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        )
        # A leftover refresh cookie from an earlier session (possibly another
        # account on this browser) must not ride the new login — clear it so a
        # later silent renewal can't swap the session out from under the user.
        clear_refresh_cookie(response)
        return Token(access_token=access_token)

    access_token, access_max_age = mint_access_token(
        user_id=user.id,
        token_version=user.token_version,
        session_id=issued.session.id,
        amr=issued.session.amr,
        satisfied_providers=issued.session.satisfied_providers,
    )
    set_session_cookie(response, access_token, max_age=access_max_age)
    set_refresh_cookie(response, issued.refresh_token)
    return Token(access_token=access_token)


@router.post("/refresh", response_model=Token)
@limiter.limit("60/minute")
async def refresh_access_token(
    request: Request,
    response: Response,
    admin_session: AdminSessionDep,
) -> Token | JSONResponse:
    """Rotate the refresh cookie → a fresh short-lived access token + new refresh.

    Single-use rotation with theft detection lives in the session service; this
    endpoint is the ``rotate → commit → branch`` caller (see
    ``services.auth.sessions``). Reuse of a spent token revokes the whole chain,
    but the client is always told the same generic thing — never that a replay
    was detected. Runs on the system engine: validation is a pre-auth lookup by
    refresh-token hash.
    """
    raw = request.cookies.get(REFRESH_COOKIE_NAME)
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthMessages.NOT_AUTHENTICATED,
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await session_service.rotate_session(
        admin_session,
        raw_refresh_token=raw,
        user_agent=request.headers.get("user-agent"),
        ip=get_inet_client_ip(request),
    )
    # Commit BEFORE branching: one commit persists the rotation (ROTATED) or the
    # theft-revocation (REUSED), so a rejection can't leave the chain kill
    # uncommitted (see RotationResult).
    await admin_session.commit()

    if not result.ok:
        if result.outcome is RefreshOutcome.REUSED:
            logger.warning("Refresh token replay detected; revoked session chain")
        return _refresh_rejected(AuthMessages.INVALID_REFRESH_TOKEN)

    issued = result.issued
    user = await admin_session.get(User, issued.session.user_id)
    if user is None or user.status != UserStatus.active:
        # The account was deactivated/removed after the session was minted — kill
        # the fresh session too rather than hand back a usable token.
        await session_service.revoke_chain(admin_session, session_id=issued.session.id)
        await admin_session.commit()
        return _refresh_rejected(AuthMessages.INVALID_REFRESH_TOKEN)

    access_token, access_max_age = mint_access_token(
        user_id=user.id,
        token_version=user.token_version,
        session_id=issued.session.id,
        amr=issued.session.amr,
        satisfied_providers=issued.session.satisfied_providers,
    )
    set_session_cookie(response, access_token, max_age=access_max_age)
    set_refresh_cookie(response, issued.refresh_token)
    return Token(access_token=access_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    session: SessionDep,
    admin_session: AdminSessionDep,
    current_user: Annotated[User | None, Depends(get_current_user_optional)] = None,
) -> None:
    # Note: `session` and `get_current_user_optional` must resolve to the
    # SAME session — the `current_user` object is attached to the dep's
    # session, so committing a different one silently drops the
    # token_version bump. (Tests alias both deps to one fixture session,
    # which can mask a mismatch.)
    # (``admin_session`` is a SEPARATE, deliberate session used only to revoke
    # auth_sessions — which the request-path role doesn't touch — never for
    # the token_version bump above.)
    if current_user is not None:
        current_user.token_version += 1
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("DeviceToken "):
            device_token_str = auth_header[12:]
            device_token = await user_tokens.get_device_token(
                session, token=device_token_str
            )
            if device_token:
                device_token.consumed_at = datetime.now(timezone.utc)
                session.add(device_token)
        session.add(current_user)
        await session.commit()
        # Revoke the refresh side too: the token_version bump covers access
        # tokens, and revoking the refresh chain completes "logout = sign out
        # everywhere".
        await session_service.revoke_all_for_user(
            admin_session, user_id=current_user.id
        )
        await admin_session.commit()
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    clear_refresh_cookie(response)


@router.post("/upload-token", response_model=UploadTokenResponse)
@limiter.limit("60/minute")
async def issue_upload_token(
    request: Request,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> UploadTokenResponse:
    """Mint a short-lived, uploads-scoped token for the authenticated user.

    Native (Capacitor) clients call this to load ``/uploads/*`` media and
    document downloads via ``?token=`` without putting the long-lived session
    JWT in the URL (which would leak through logs, history, and Referer). The
    token is accepted only by the uploads/download routes and is useless as a
    general API credential.
    """
    # Copy the minting session's satisfied-provider set into the scoped token
    # so media loads and the sync-content keepalive pass a policy-gated guild
    # exactly when the session itself would.
    satisfied = auth_context.satisfied_providers()
    token, expires_in = create_upload_token(
        user_id=current_user.id,
        satisfied_providers=sorted(satisfied)
        if isinstance(satisfied, frozenset)
        else (),
    )
    return UploadTokenResponse(upload_token=token, expires_in=expires_in)


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
    statement = select(User).where(User.email_hash == hash_email(normalized_email))
    result = await session.exec(statement)
    user = result.one_or_none()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.INCORRECT_CREDENTIALS,
        )

    if user.status != UserStatus.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.INACTIVE_USER
        )
    if not user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.EMAIL_NOT_VERIFIED,
        )

    if password_needs_rehash(user.hashed_password):
        # Best-effort upgrade — see login_access_token for rationale.
        try:
            user.hashed_password = get_password_hash(payload.password)
            session.add(user)
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("Failed to upgrade password hash for user %s", user.id)

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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.TOKEN_NOT_FOUND
        )


def _provider_redirect_uri(provider_slug: str, guild_id: int | None = None) -> str:
    """Per-provider callback URL. For the platform slug this is the same
    ``/auth/oidc/callback`` operators registered at their IdP before the
    routes were generalized — the slug is literally ``oidc``. Guild-scoped
    providers get a guild-addressed callback (their slug is only unique
    within the guild)."""
    base = settings.APP_URL.rstrip("/")
    if guild_id is not None:
        return f"{base}{API_V1_STR}/auth/g/{guild_id}/{provider_slug}/callback"
    return f"{base}{API_V1_STR}/auth/{provider_slug}/callback"


def _provider_state_key(row: AuthProvider) -> str:
    """The identity a login-flow state binds to. Operator-global rows keep the
    bare slug (states minted before guild providers stay valid); guild rows
    are namespaced so a state begun with one guild's provider can't complete
    against another guild's provider of the same slug."""
    if row.guild_id is not None:
        return f"g{row.guild_id}:{row.slug}"
    return row.slug


def _frontend_redirect_uri() -> str:
    base = settings.APP_URL.rstrip("/")
    return f"{base}/oidc/callback"


# Carries a validated SPA return path from /auth/{slug}/login to the web
# callback (e.g. the guild page a step-up started from). Scoped to the auth
# routes and short-lived — it only needs to survive one IdP round trip.
OIDC_NEXT_COOKIE = "oidc_next"
OIDC_NEXT_COOKIE_MAX_AGE = 600


def _platform_oidc_active(app_settings: AppSetting) -> bool:
    """The platform OIDC login is offered only when the platform posture is
    live AND the provider is enabled + fully configured. In guild scope the
    platform provider is dormant (kept, not deleted) and must not authenticate
    anyone — enforced here, server-side, not just hidden in the UI."""
    return bool(
        app_settings.auth_scope == AuthScope.platform.value
        and app_settings.oidc_enabled
        and app_settings.oidc_issuer
        and app_settings.oidc_client_id
        and app_settings.oidc_client_secret_encrypted
    )


async def _resolve_login_provider(
    app_settings: AppSetting, admin_session: AsyncSession, provider_slug: str
) -> AuthProvider:
    """The enabled operator-global provider row for one login slug, or 404.

    The scope gate comes first: in guild posture every operator-global provider
    is dormant and must not authenticate anyone — enforced server-side, not
    just hidden in the UI. The platform slug keeps ``app_settings`` as its
    config surface (reconciled into the registry row on every resolve); any
    other slug is a registry row directly. A malformed slug is treated like an
    unknown one (no registry row can carry it)."""
    if not is_valid_provider_slug(provider_slug):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=OidcMessages.OIDC_NOT_ENABLED
        )
    if app_settings.auth_scope != AuthScope.platform.value:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=OidcMessages.OIDC_NOT_ENABLED
        )
    if provider_slug == PLATFORM_OIDC_SLUG:
        if not _platform_oidc_active(app_settings):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=OidcMessages.OIDC_NOT_ENABLED,
            )
        return await ensure_platform_provider(admin_session, app_settings)
    row = (
        await admin_session.exec(
            select(AuthProvider).where(
                AuthProvider.slug == provider_slug,
                AuthProvider.guild_id.is_(None),
            )
        )
    ).one_or_none()
    if row is None or not is_login_ready(row):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=OidcMessages.OIDC_NOT_ENABLED
        )
    return row


async def _resolve_guild_login_provider(
    app_settings: AppSetting,
    admin_session: AsyncSession,
    guild_id: int,
    provider_slug: str,
) -> AuthProvider:
    """The login-ready guild-scoped provider row for one (guild, slug), or
    404. Guild providers serve logins only under per-guild auth posture —
    the mirror image of ``_resolve_login_provider``'s operator-global gate.
    An unknown guild, slug, or config-incomplete row all look identical."""
    if not is_valid_provider_slug(provider_slug):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=OidcMessages.OIDC_NOT_ENABLED
        )
    if app_settings.auth_scope != AuthScope.guild.value:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=OidcMessages.OIDC_NOT_ENABLED
        )
    row = (
        await admin_session.exec(
            select(AuthProvider).where(
                AuthProvider.slug == provider_slug,
                AuthProvider.guild_id == guild_id,
            )
        )
    ).one_or_none()
    if row is None or not is_login_ready(row):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=OidcMessages.OIDC_NOT_ENABLED
        )
    return row


async def _build_row_oidc_provider(
    admin_session: AsyncSession, row: AuthProvider
) -> OidcProvider:
    """The relying-party client for one provider row — the single builder for
    every slug. The platform row is reconciled from ``app_settings`` (config
    AND secret) by ``_resolve_login_provider`` before it gets here, so the
    registry row is always the client's source of truth. The secret comes from
    the app_admin-only companion table; ``None`` (public / PKCE-only client)
    is valid. Tests monkeypatch this builder to point flows at a fake IdP."""
    secret_row = await admin_session.get(AuthProviderSecret, row.id)
    client_secret = (
        decrypt_field(secret_row.client_secret_encrypted, SALT_OIDC_CLIENT_SECRET)
        if secret_row and secret_row.client_secret_encrypted
        else None
    )
    return OidcProvider(
        OidcClientConfig(
            issuer=row.issuer,
            client_id=row.client_id,
            redirect_uri=_provider_redirect_uri(row.slug, row.guild_id),
            client_secret=client_secret,
            scopes=row.scopes or "openid",
            provider_slug=_provider_state_key(row),
        ),
        discovery=_oidc_discovery,
        jwks=_oidc_jwks,
    )


def _login_entry(row: AuthProvider) -> LoginProviderEntry:
    login_url = (
        f"{API_V1_STR}/auth/g/{row.guild_id}/{row.slug}/login"
        if row.guild_id is not None
        else f"{API_V1_STR}/auth/{row.slug}/login"
    )
    return LoginProviderEntry(
        id=row.id,
        slug=row.slug,
        display_name=row.display_name,
        kind=row.kind,
        login_url=login_url,
        icon=row.icon,
        button_style=row.button_style,
    )


@router.get("/providers", response_model=LoginProvidersResponse)
async def list_login_providers(
    session: SessionDep, admin_session: AdminSessionDep
) -> LoginProvidersResponse:
    """The sign-in providers the login page offers — non-secret metadata only.

    Empty in guild posture (operator-global providers are dormant there) and
    on instances with no SSO configured. Strictly read-only: an
    unauthenticated GET must not trigger writes, so the platform entry is
    built from ``app_settings`` (its config surface) rather than the
    write-capable reconcile — that runs in the login flow and at boot.
    Registry rows are read on the system engine (``auth_providers`` carries no
    request-path grant)."""
    app_settings = await app_settings_service.get_app_settings(session)
    if app_settings.auth_scope != AuthScope.platform.value:
        return LoginProvidersResponse(providers=[])

    entries: list[LoginProviderEntry] = []
    if _platform_oidc_active(app_settings):
        # Row read only for display extras (icon/button_style); name and
        # liveness come from app_settings, matching what login would do.
        platform_row = await get_platform_provider(admin_session)
        entries.append(
            LoginProviderEntry(
                # None until the platform row's first reconcile (login/boot);
                # consumers that need a registry id (the guild auth-policy
                # picker) skip id-less entries.
                id=platform_row.id if platform_row else None,
                slug=PLATFORM_OIDC_SLUG,
                display_name=app_settings.oidc_provider_name or "SSO",
                kind="oidc",
                login_url=f"{API_V1_STR}/auth/{PLATFORM_OIDC_SLUG}/login",
                icon=platform_row.icon if platform_row else None,
                button_style=platform_row.button_style if platform_row else None,
            )
        )

    rows = (
        await admin_session.exec(
            select(AuthProvider)
            .where(
                AuthProvider.guild_id.is_(None),
                AuthProvider.slug != PLATFORM_OIDC_SLUG,
                AuthProvider.enabled.is_(True),
                AuthProvider.kind == "oidc",
                AuthProvider.issuer.is_not(None),
                AuthProvider.client_id.is_not(None),
            )
            .order_by(AuthProvider.display_name)
        )
    ).all()
    # is_login_ready re-checks the same predicates and stays the single
    # authority (it also guards empty strings, which SQL NULL checks miss).
    entries.extend(_login_entry(row) for row in rows if is_login_ready(row))
    return LoginProvidersResponse(providers=entries)


async def _begin_provider_login(
    admin_session: AsyncSession,
    provider_row: AuthProvider,
    *,
    mobile: bool,
    device_name: str,
    next_path: str,
) -> RedirectResponse:
    """Begin the relying-party flow for a resolved provider row — shared by
    the operator-global and guild-addressed login routes.

    ``next_path`` is an optional SPA path to return to after the web callback
    (e.g. the guild page a step-up started from). Only a validated relative
    path is accepted; it rides a short-lived cookie to the callback, which
    passes it to the SPA's ``/oidc/callback`` page as a query param."""
    provider = await _build_row_oidc_provider(admin_session, provider_row)
    try:
        begun = await provider.begin(
            mobile=mobile, device_name=device_name if mobile else ""
        )
    except OidcFlowError as exc:
        logger.error("OIDC login could not start: %s (%s)", exc.code, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=OidcMessages.OIDC_METADATA_INCOMPLETE,
        ) from exc
    # Discovery validated the authorization endpoint as an absolute https URL
    # (see app.services.auth.oidc.discovery), so a malformed or tampered
    # discovery document cannot send the user to a non-TLS location.
    response = RedirectResponse(begun.authorization_url)
    if not mobile and is_safe_next_path(next_path):
        response.set_cookie(
            key=OIDC_NEXT_COOKIE,
            value=next_path,
            max_age=OIDC_NEXT_COOKIE_MAX_AGE,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
            path=REFRESH_COOKIE_PATH,
        )
    return response


@router.get("/g/{guild_id}/providers", response_model=LoginProvidersResponse)
async def list_guild_login_providers(
    session: SessionDep, admin_session: AdminSessionDep, guild_id: int
) -> LoginProvidersResponse:
    """One guild's sign-in providers — non-secret metadata only, with
    guild-addressed login URLs and the guild's display name for its login
    page. Empty (and nameless) outside per-guild auth posture and for a
    guild with no login-ready providers; an unknown guild id is
    indistinguishable from an empty registry."""
    app_settings = await app_settings_service.get_app_settings(session)
    if app_settings.auth_scope != AuthScope.guild.value:
        return LoginProvidersResponse(providers=[])
    rows = (
        await admin_session.exec(
            select(AuthProvider)
            .where(AuthProvider.guild_id == guild_id)
            .order_by(AuthProvider.display_name)
        )
    ).all()
    entries = [_login_entry(row) for row in rows if is_login_ready(row)]
    guild_name = None
    if entries:
        guild = await admin_session.get(Guild, guild_id)
        guild_name = guild.name if guild else None
    return LoginProvidersResponse(providers=entries, guild_name=guild_name)


@router.get("/g/{guild_id}/{provider_slug}/login")
@limiter.limit("20/minute")
async def guild_provider_login(
    request: Request,
    session: SessionDep,
    admin_session: AdminSessionDep,
    guild_id: int,
    provider_slug: str,
    next_path: str = Query(default="", alias="next"),
) -> RedirectResponse:
    """Begin the relying-party flow for one of a guild's own providers.
    Web only for now — native guild step-up arrives with native session
    tokens, so there is no ``mobile`` variant of this route."""
    app_settings = await app_settings_service.get_app_settings(session)
    provider_row = await _resolve_guild_login_provider(
        app_settings, admin_session, guild_id, provider_slug
    )
    return await _begin_provider_login(
        admin_session, provider_row, mobile=False, device_name="", next_path=next_path
    )


@router.get("/{provider_slug}/login")
@limiter.limit("20/minute")
async def provider_login(
    request: Request,
    session: SessionDep,
    admin_session: AdminSessionDep,
    provider_slug: str,
    mobile: bool = Query(default=False),
    device_name: str = Query(default="Mobile Device"),
    next_path: str = Query(default="", alias="next"),
) -> RedirectResponse:
    """Begin the relying-party flow for one operator-global provider. The
    platform provider's slug is ``oidc``, so the pre-generalization
    ``/auth/oidc/login`` URL is this same route."""
    app_settings = await app_settings_service.get_app_settings(session)
    provider_row = await _resolve_login_provider(
        app_settings, admin_session, provider_slug
    )
    return await _begin_provider_login(
        admin_session,
        provider_row,
        mobile=mobile,
        device_name=device_name,
        next_path=next_path,
    )


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


async def _discard_provisioned_user(
    admin_session: AsyncSession, *, user_id: int
) -> None:
    """Delete a user JIT-provisioned earlier in this same request that we then
    couldn't admit to any guild. The federated-identity link and its secret
    cascade off the row (ON DELETE CASCADE)."""
    user = await admin_session.get(User, user_id)
    if user is not None:
        await admin_session.delete(user)
        await admin_session.commit()


async def _complete_provider_login(
    request: Request,
    session: AsyncSession,
    admin_session: AsyncSession,
    provider_row: AuthProvider,
    code: str | None,
    state: str | None,
):
    """Complete the relying-party flow for a resolved provider row — shared
    by the operator-global and guild-addressed callback routes. Guild rows
    differ in three ways: a successful sign-in also admits the user to the
    provider's guild (JIT-provisioning unknown users when the provider allows
    it, always as plain member, capacity-enforced), the operator claim-to-role
    sync doesn't run, and mobile flows can't reach here (the guild login route
    doesn't offer one)."""
    # Best-effort mobile flag so even early failures land on the right surface
    # (app vs. web); ``complete()`` re-validates the state authoritatively.
    is_mobile: bool | None = None
    if state:
        try:
            is_mobile = decode_flow_state(state).mobile
        except FlowStateError:
            is_mobile = None

    provider = await _build_row_oidc_provider(admin_session, provider_row)
    try:
        completion = await provider.complete(code=code or "", state=state or "")
    except OidcFlowError as exc:
        logger.warning("OIDC callback rejected: %s (%s)", exc.code, exc)
        return _error_redirect(is_mobile, exc.code)
    is_mobile = completion.mobile

    # The verified id_token is the identity source of truth; userinfo (when the
    # provider advertises it) only enriches profile claims, and only when its
    # sub matches the id_token's (OIDC Core §5.3.2).
    claims = dict(completion.claims)
    userinfo: dict[str, Any] | None = None
    if completion.access_token:
        try:
            userinfo = await provider.fetch_userinfo(completion.access_token)
        except OidcFlowError as exc:
            logger.warning("OIDC userinfo enrichment failed: %s", exc)
    if userinfo is not None:
        if userinfo.get("sub") == completion.subject:
            for key, value in userinfo.items():
                claims.setdefault(key, value)
        else:
            logger.warning(
                "OIDC userinfo sub does not match id_token sub; ignoring userinfo"
            )
            userinfo = None

    email_claim = claims.get("email")
    email = (
        email_claim.strip().lower()
        if isinstance(email_claim, str) and email_claim.strip()
        else None
    )
    # Trust the IdP's ``email_verified`` claim only as an explicit ``true``; a
    # missing/false claim is treated as unverified (some IdPs omit it entirely).
    email_verified = claims.get("email_verified") is True
    name_claim = claims.get("name") or claims.get("preferred_username")
    full_name = name_claim if isinstance(name_claim, str) and name_claim else None
    picture_claim = claims.get("picture")
    avatar_url = (
        picture_claim if isinstance(picture_claim, str) and picture_claim else None
    )

    resolution = await resolve_oidc_identity(
        admin_session,
        provider=provider_row,
        subject=completion.subject,
        email=email,
        email_verified=email_verified,
        full_name=full_name,
        avatar_url=avatar_url,
    )

    if resolution.user is None:
        # JIT_DISABLED / REGISTRATION_DISABLED: unknown user, provisioning off.
        return _error_redirect(is_mobile, OidcMessages.REGISTRATION_DISABLED)
    user = resolution.user

    # Refuse to silently reactivate an admin- or self-deactivated account via
    # SSO — deactivation is reversed by an admin, not by a login. Checked
    # before any link is written.
    if user.status != UserStatus.active:
        return _error_redirect(is_mobile, OidcMessages.ACCOUNT_INACTIVE)

    if resolution.outcome is ResolutionOutcome.EMAIL_UNVERIFIED:
        # An unlinked local account matched by an email the IdP has not
        # verified: refused, protecting pre-registered accounts.
        logger.warning(
            "OIDC login refused: email_verified not asserted for existing "
            "account (user_id=%s)",
            user.id,
        )
        return _error_redirect(is_mobile, OidcMessages.EMAIL_UNVERIFIED)

    identity = resolution.identity
    if resolution.outcome is ResolutionOutcome.EMAIL_MATCH:
        # Platform policy: a verified IdP email claims its matching local
        # account (parity with the previous flow); the link makes every later
        # login resolve by (provider, subject).
        identity = await link_identity(
            admin_session,
            user=user,
            provider=provider_row,
            subject=completion.subject,
            email_verified=email_verified,
        )

    # Profile refresh from the verified claims.
    if email_verified and not user.email_verified:
        user.email_verified = True
    if full_name and user.full_name != full_name:
        user.full_name = full_name
    if avatar_url and user.avatar_url != avatar_url:
        user.avatar_url = avatar_url
        user.avatar_base64 = None
    # Record the login on the identity link: the IdP refresh token (rotated by
    # the background group re-sync) and the sync stamp the sweep filters on —
    # the ``federated_identities`` successors of the legacy ``users.oidc_*``
    # columns, which are no longer written and drop in the final cutover phase.
    if identity is not None:
        if completion.refresh_token:
            await set_identity_refresh_token(
                admin_session,
                identity_id=identity.id,
                refresh_token=completion.refresh_token,
            )
        identity.last_synced_at = datetime.now(timezone.utc)
        admin_session.add(identity)
    admin_session.add(user)
    await admin_session.commit()
    await admin_session.refresh(user)

    if provider_row.guild_id is not None:
        # The guild's own IdP is its configured identity source, so a
        # successful authentication doubles as admission: get-or-create the
        # membership, always as plain member (roles are assigned in the app),
        # honoring the guild's member capacity.
        #
        # ``resolve_oidc_identity`` has already committed a JIT-provisioned
        # user, so plain values are captured up front — the rollback below
        # expires the ORM object.
        onboarding_user_id = user.id
        was_provisioned = resolution.outcome is ResolutionOutcome.PROVISIONED
        try:
            await guilds_service.ensure_membership(
                admin_session,
                guild_id=provider_row.guild_id,
                user_id=onboarding_user_id,
            )
            await admin_session.commit()
        except guilds_service.GuildCapacityError:
            await admin_session.rollback()
            # A user provisioned by THIS sign-in belongs to no other guild, so
            # a full guild would strand a usable-nowhere account. Undo it (the
            # federated-identity link and its secret cascade). An account that
            # already existed keeps whatever access it had.
            if was_provisioned:
                await _discard_provisioned_user(
                    admin_session, user_id=onboarding_user_id
                )
            return _error_redirect(is_mobile, GuildMessages.GUILD_USER_LIMIT_REACHED)
        await admin_session.refresh(user)

    # OIDC claim-to-role sync (the id_token claims are verified upstream now).
    # Operator-global providers only: the mapping registry is platform-level
    # configuration; per-guild claim mappings are their own later feature.
    try:
        claim_path = (
            provider_row.role_claim_path if provider_row.guild_id is None else None
        )
        if claim_path:
            claim_values = extract_claim_values(
                userinfo or {}, completion.claims, claim_path
            )
            async with AdminSessionLocal() as sync_session:
                sync_result = await sync_oidc_assignments(
                    sync_session,
                    user_id=user.id,
                    claim_values=claim_values,
                )
                logger.info(
                    "OIDC sync for user %s: +%d/~%d/-%d guilds, +%d/~%d/-%d initiatives",
                    user.id,
                    len(sync_result.guilds_added),
                    len(sync_result.guilds_updated),
                    len(sync_result.guilds_removed),
                    len(sync_result.initiatives_added),
                    len(sync_result.initiatives_updated),
                    len(sync_result.initiatives_removed),
                )
    except Exception:
        logger.exception("OIDC claim sync failed for user %s", user.id)

    if is_mobile:
        device_token = await user_tokens.create_device_token(
            session,
            user_id=user.id,
            device_name=completion.device_name or "Mobile Device",
        )
        redirect_params = {"token": device_token, "token_type": "device_token"}
        redirect_url = f"{_mobile_redirect_uri()}?{urlencode(redirect_params)}"
        return RedirectResponse(redirect_url)
    # The new login model, mirroring the password path (§3): the session is
    # load-bearing — the access token carries sid/amr/sat (the inputs the
    # per-guild auth-policy gate and step-up read later) and the rotating
    # refresh cookie carries the session.
    #
    # Fallback: a transient session-store failure must not fail a successful
    # SSO login — issue a legacy long-lived token instead (dual-verify window);
    # that session just can't renew silently.
    #
    # ``user`` is attached to ``admin_session``, so the rollback below expires
    # its attributes; the plain values are captured up front so the failure
    # path never touches the ORM object again.
    user_id, token_version = user.id, user.token_version
    provider_id, provider_slug = provider_row.id, provider_row.slug
    # Return the browser to where the login started (a step-up hands the
    # guild page it interrupted): the login route stored a validated SPA
    # path in the short-lived cookie; re-validate before echoing it, and
    # clear the cookie either way.
    next_path = request.cookies.get(OIDC_NEXT_COOKIE, "")
    frontend_uri = _frontend_redirect_uri()
    if is_safe_next_path(next_path):
        frontend_uri = f"{frontend_uri}?{urlencode({'next': next_path})}"
    oidc_response = RedirectResponse(frontend_uri)
    oidc_response.delete_cookie(key=OIDC_NEXT_COOKIE, path=REFRESH_COOKIE_PATH)
    # A step-up upgrades the session it interrupted rather than starting
    # over: the live session's factors carry forward (union) and the old
    # session is revoked, replaced by the new one — satisfying one guild's
    # requirement never un-satisfies another's. Only the same user's session
    # merges; anything else is a fresh login.
    amr = [f"oidc:{provider_slug}"]
    satisfied = [provider_id]
    prior = None
    prior_raw = request.cookies.get(REFRESH_COOKIE_NAME)
    if prior_raw:
        prior = await session_service.get_live_session_by_refresh_token(
            admin_session, prior_raw
        )
        if prior is not None and prior.user_id == user_id:
            amr = sorted(set(prior.amr) | set(amr))
            satisfied = sorted(set(prior.satisfied_providers) | set(satisfied))
        else:
            prior = None
    try:
        issued = await session_service.create_session(
            admin_session,
            user_id=user_id,
            amr=amr,
            satisfied_providers=satisfied,
            user_agent=request.headers.get("user-agent"),
            ip=get_inet_client_ip(request),
        )
        if prior is not None:
            # Chain-revoke, not single-revoke: a concurrent /auth/refresh may
            # have rotated the presented session between our read and this
            # write, and the replacement must not leave that rotation child
            # running beside the stepped-up session. The new session is a
            # fresh chain root, so the walk never touches it.
            await session_service.revoke_chain(admin_session, session_id=prior.id)
        await admin_session.commit()
    except Exception:
        await admin_session.rollback()
        logger.exception(
            "Failed to establish refresh session for user %s; "
            "falling back to a legacy access token",
            user_id,
        )
        legacy_token = create_access_token(
            subject=str(user_id), token_version=token_version
        )
        set_session_cookie(
            oidc_response,
            legacy_token,
            max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )
        # Same rule as the password-login fallback: a leftover refresh cookie
        # must not ride the new login.
        clear_refresh_cookie(oidc_response)
        return oidc_response

    app_token, access_max_age = mint_access_token(
        user_id=user_id,
        token_version=token_version,
        session_id=issued.session.id,
        amr=issued.session.amr,
        satisfied_providers=issued.session.satisfied_providers,
    )
    set_session_cookie(oidc_response, app_token, max_age=access_max_age)
    set_refresh_cookie(oidc_response, issued.refresh_token)
    return oidc_response


@router.get("/g/{guild_id}/{provider_slug}/callback")
@limiter.limit("20/minute")
async def guild_provider_callback(
    request: Request,
    session: SessionDep,
    admin_session: AdminSessionDep,
    guild_id: int,
    provider_slug: str,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
):
    """Complete the relying-party flow for one of a guild's own providers —
    the guild-addressed URL registered at the guild's IdP."""
    app_settings = await app_settings_service.get_app_settings(session)
    provider_row = await _resolve_guild_login_provider(
        app_settings, admin_session, guild_id, provider_slug
    )
    return await _complete_provider_login(
        request, session, admin_session, provider_row, code, state
    )


@router.get("/{provider_slug}/callback")
@limiter.limit("20/minute")
async def provider_callback(
    request: Request,
    session: SessionDep,
    admin_session: AdminSessionDep,
    provider_slug: str,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
):
    """Complete the relying-party flow for one operator-global provider (see
    provider_login: the platform provider's slug is ``oidc``, so the URL
    operators registered at their IdP is this same route)."""
    app_settings = await app_settings_service.get_app_settings(session)
    provider_row = await _resolve_login_provider(
        app_settings, admin_session, provider_slug
    )
    return await _complete_provider_login(
        request, session, admin_session, provider_row, code, state
    )


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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.SMTP_NOT_CONFIGURED,
        ) from None
    except RuntimeError as exc:  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    return VerificationSendResponse(status="sent")


@router.post("/verification/confirm", response_model=VerificationSendResponse)
@limiter.limit("5/15minutes")
async def confirm_verification(
    request: Request, session: SessionDep, payload: VerificationConfirmRequest
) -> VerificationSendResponse:
    record = await user_tokens.consume_token(
        session,
        token=payload.token,
        purpose=UserTokenPurpose.email_verification,
    )
    if not record:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.INVALID_OR_EXPIRED_TOKEN,
        )
    user_stmt = select(User).where(User.id == record.user_id)
    user_result = await session.exec(user_stmt)
    user = user_result.one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND
        )
    if not user.email_verified:
        user.email_verified = True
        user.updated_at = datetime.now(timezone.utc)
        session.add(user)
        await session.commit()
        await session.refresh(user)
    return VerificationSendResponse(status="verified")


@router.post("/password/forgot", response_model=VerificationSendResponse)
@limiter.limit("5/15minutes")
async def request_password_reset(
    request: Request, payload: PasswordResetRequest, session: SessionDep
) -> VerificationSendResponse:
    normalized_email = payload.email.lower().strip()
    stmt = select(User).where(User.email_hash == hash_email(normalized_email))
    result = await session.exec(stmt)
    user = result.one_or_none()
    if not user or user.status != UserStatus.active:
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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.SMTP_NOT_CONFIGURED,
        ) from None
    except RuntimeError as exc:  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    return VerificationSendResponse(status="sent")


@router.post("/password/reset", response_model=VerificationSendResponse)
@limiter.limit("5/15minutes")
async def reset_password(
    request: Request,
    payload: PasswordResetSubmit,
    session: SessionDep,
    admin_session: AdminSessionDep,
) -> VerificationSendResponse:
    # Run the policy first so an invalid candidate doesn't burn the
    # reset token; ``consume_token`` is one-shot.
    await enforce_password_policy(payload.password)
    record = await user_tokens.consume_token(
        session,
        token=payload.token,
        purpose=UserTokenPurpose.password_reset,
    )
    if not record:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.INVALID_OR_EXPIRED_TOKEN,
        )
    stmt = select(User).where(User.id == record.user_id)
    result = await session.exec(stmt)
    user = result.one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND
        )
    user.hashed_password = get_password_hash(payload.password)
    # Bump token_version and revoke device tokens / API keys / refresh sessions
    # so no stale credential (JWT, device token, or captured refresh) survives.
    await user_tokens.revoke_user_sessions(
        session, user=user, admin_session=admin_session
    )
    if not user.email_verified:
        user.email_verified = True
    user.updated_at = datetime.now(timezone.utc)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return VerificationSendResponse(status="reset")
