from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import Cookie, Depends, Header, HTTPException, Query, Request, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.messages import AuthMessages, GuildMessages
from app.core.security import (
    AutoDelegationClaims,
    AutoDelegationVerificationError,
    verify_auto_delegation_token,
)
from app.db.session import get_session, set_rls_context
from app.models.guild import Guild, GuildMembership, GuildRole
from app.models.user import User, UserRole, UserStatus
from app.schemas.token import TokenPayload
from app.services import api_keys as api_keys_service
from app.services import auto_delegation_blocklist
from app.services import guilds as guilds_service
from app.services import user_tokens

SessionDep = Annotated[AsyncSession, Depends(get_session)]

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/token", auto_error=False)


async def _authenticate_device_token(session: AsyncSession, token: str) -> Optional[User]:
    """Authenticate using a device token and return the associated user."""
    device_token = await user_tokens.get_device_token(session, token=token)
    if not device_token:
        return None
    statement = select(User).where(User.id == device_token.user_id)
    result = await session.exec(statement)
    return result.one_or_none()


def _delegation_guild_matches_header(
    request: Request, claims: AutoDelegationClaims
) -> bool:
    """Reject delegation tokens whose ``guild_id`` claim contradicts the
    request's ``X-Guild-ID`` header.

    The header is what RLS will use to scope the query; if the token was
    issued for guild 42 and the request asks for guild 99, that's a
    cross-guild attempt — a user who's a member of both guilds shouldn't
    be able to use a token issued in one to access the other. When the
    header is absent (cross-guild endpoints like ``/users/me``) we allow,
    relying on the endpoint itself to scope appropriately.
    """
    raw = request.headers.get("X-Guild-ID")
    if not raw:
        return True
    try:
        return int(raw) == claims.guild_id
    except (TypeError, ValueError):
        return False


async def _authenticate_auto_delegation(
    request: Request,
    session: AsyncSession,
    token: str,
) -> Optional[User]:
    """Try to interpret ``token`` as a delegation JWT from initiative-auto.

    Returns the named user when the token verifies; ``None`` otherwise so
    the caller can fall through to other auth methods (regular JWT, API
    key, etc.) without 401-ing on what's actually a session-token-shaped
    bearer arriving at the same header.

    Authorization beyond authentication still happens downstream — this
    function only resolves identity. RLS, role-permission checks, and
    master switches gate the actual operation as if the user were
    calling directly.

    Three security checks fire here in order:
      1. Token verifies (signature, audience, issuer, required claims).
      2. ``jti`` is not in the blocklist — first presentation only.
      3. ``guild_id`` claim matches ``X-Guild-ID`` header when present.
    """
    if not settings.AUTO_DELEGATION_PUBLIC_KEY_PEM:
        return None  # delegation disabled — let other auth paths run

    try:
        claims = verify_auto_delegation_token(token)
    except AutoDelegationVerificationError:
        # Could be a session JWT or API key arriving on the same header.
        # Returning None lets the caller try those instead of failing.
        return None

    if not _delegation_guild_matches_header(request, claims):
        return None

    # Replay guard: a delegation JWT is one-shot. Even though the JWT is
    # technically valid for 15 minutes, a captured token must not be
    # usable a second time. The pre-flight ``is_jti_redeemed`` is a fast
    # path; the ``record_jti`` insert below is the actual race-safe
    # guarantee (unique-violation on the PK).
    if await auto_delegation_blocklist.is_jti_redeemed(session, claims.jti):
        return None

    statement = select(User).where(User.id == claims.user_id)
    result = await session.exec(statement)
    user = result.one_or_none()
    if user is None or user.status != UserStatus.active:
        # The user the token names doesn't exist or has been deactivated
        # since the token was minted. Auto can't impersonate non-active
        # accounts — workflows die when their owner leaves, by design.
        return None

    # Burn the jti now. Two requests racing past the pre-flight check
    # collide on the PK and the loser's ``record_jti`` raises
    # ``DelegationReplayError``, which we convert to the same None
    # signal — the request will be re-authenticated by another path or
    # rejected by the standard 401.
    try:
        await auto_delegation_blocklist.record_jti(
            session, jti=claims.jti, expires_at=_delegation_exp_from_jwt(token)
        )
    except auto_delegation_blocklist.DelegationReplayError:
        return None

    return user


def _delegation_exp_from_jwt(token: str) -> datetime:
    """Pull the ``exp`` timestamp out of a delegation JWT without
    re-verifying. Caller has already verified — we just need the value
    for the blocklist row's ``expires_at`` column so the cleanup job
    can prune expired entries.
    """
    payload = jwt.decode(token, options={"verify_signature": False})
    return datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc)


async def get_current_user(
    request: Request,
    session: SessionDep,
    bearer_token: Annotated[Optional[str], Depends(oauth2_scheme)] = None,
    session_cookie: Annotated[Optional[str], Cookie(alias=settings.COOKIE_NAME)] = None,
) -> User:
    # Check for Authorization header - could be Bearer, DeviceToken, or API key
    auth_header = request.headers.get("Authorization", "")

    # Handle DeviceToken scheme
    if auth_header.startswith("DeviceToken "):
        device_token = auth_header[12:]  # len("DeviceToken ") = 12
        user = await _authenticate_device_token(session, device_token)
        if user:
            return user
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthMessages.INVALID_DEVICE_TOKEN,
            headers={"WWW-Authenticate": "DeviceToken"},
        )

    # Use the bearer token from OAuth2 scheme, fall back to HttpOnly cookie (web sessions)
    token = bearer_token or session_cookie
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthMessages.NOT_AUTHENTICATED,
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Try API key authentication first
    user = await api_keys_service.authenticate_api_key(session, token)
    if user:
        return user

    # Try delegation JWT from initiative-auto (RS256, distinct audience).
    # Returns None on shape/algorithm mismatch so a regular HS256 session
    # JWT carrying through this header gracefully falls through to the
    # next branch.
    user = await _authenticate_auto_delegation(request, session, token)
    if user:
        return user

    # Try JWT authentication. Any PyJWTError (expired signature, bad sig,
    # malformed claims, …) is a credentials problem, so it should be 401
    # "please re-authenticate", not 403 "you're not allowed". The SPA's
    # 401 interceptor depends on this to auto-redirect to /welcome when
    # the access token expires.
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        token_data = TokenPayload(**payload)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthMessages.COULD_NOT_VALIDATE_CREDENTIALS,
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    if not token_data.sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthMessages.INVALID_TOKEN_PAYLOAD,
            headers={"WWW-Authenticate": "Bearer"},
        )

    statement = select(User).where(User.id == int(token_data.sub))
    result = await session.exec(statement)
    user = result.one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND)
    if token_data.ver is None or token_data.ver != user.token_version:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=AuthMessages.INVALID_TOKEN)
    return user


async def get_current_user_optional(
    request: Request,
    session: SessionDep,
    bearer_token: Annotated[Optional[str], Depends(oauth2_scheme)] = None,
    session_cookie: Annotated[Optional[str], Cookie(alias=settings.COOKIE_NAME)] = None,
) -> User | None:
    try:
        return await get_current_user(request, session, bearer_token, session_cookie)
    except HTTPException:
        return None


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)]
) -> User:
    if current_user.status != UserStatus.active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.INACTIVE_USER)
    return current_user


def require_roles(*roles: UserRole) -> Callable:
    async def dependency(current_user: Annotated[User, Depends(get_current_active_user)]) -> User:
        if roles and current_user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=AuthMessages.INSUFFICIENT_PRIVILEGES)
        return current_user

    return dependency


@dataclass
class GuildContext:
    guild: Guild
    membership: GuildMembership

    @property
    def guild_id(self) -> int:
        return self.guild.id  # type: ignore[return-value]

    @property
    def role(self) -> GuildRole:
        return self.membership.role


async def get_guild_membership(
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    requested_guild_id: Optional[int] = Header(None, alias="X-Guild-ID"),
) -> GuildContext:
    # Set minimal RLS context before querying guild_memberships (RLS-protected).
    # Full guild context is set later by get_guild_session / RLSSessionDep.
    await set_rls_context(
        session,
        user_id=current_user.id,
        is_superadmin=(current_user.role == UserRole.admin),
    )

    guild_id = await guilds_service.resolve_user_guild_id(
        session,
        user=current_user,
        guild_id=requested_guild_id,
    )
    if guild_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildMessages.NO_GUILD_MEMBERSHIP,
        )
    membership = await guilds_service.get_membership(
        session,
        guild_id=guild_id,
        user_id=current_user.id,
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=GuildMessages.GUILD_ACCESS_DENIED)
    guild = await guilds_service.get_guild(session, guild_id=guild_id)
    return GuildContext(guild=guild, membership=membership)


def require_guild_roles(*roles: GuildRole) -> Callable:
    async def dependency(context: Annotated[GuildContext, Depends(get_guild_membership)]) -> GuildContext:
        if roles and context.membership.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=GuildMessages.GUILD_PERMISSION_REQUIRED)
        return context

    return dependency


async def get_guild_session(
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> AsyncSession:
    """Get a session with RLS context set for the current user and guild.

    This dependency injects PostgreSQL session variables (via set_config
    with is_local=false) that RLS policies use to filter data. Use this
    instead of SessionDep when you need database-level access control.

    Variables persist for the lifetime of the underlying connection, not
    just the current transaction. After session.commit() the connection
    may be returned to the pool, so call reapply_rls_context(session)
    before any post-commit queries.
    """
    await set_rls_context(
        session,
        user_id=current_user.id,
        guild_id=guild_context.guild_id,
        guild_role=guild_context.role.value,
        is_superadmin=(current_user.role == UserRole.admin),
    )
    return session


# Dependency for routes that need RLS-aware database access
RLSSessionDep = Annotated[AsyncSession, Depends(get_guild_session)]


async def get_user_session(
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> AsyncSession:
    """Get a session with user context only (no guild).

    For cross-guild operations like guild creation, listing user's guilds,
    or accepting invites where no specific guild context is needed.
    """
    await set_rls_context(
        session,
        user_id=current_user.id,
        is_superadmin=(current_user.role == UserRole.admin),
    )
    return session


# Dependency for routes that need user-level RLS without guild context
UserSessionDep = Annotated[AsyncSession, Depends(get_user_session)]


async def get_upload_user(
    request: Request,
    session: SessionDep,
    bearer_token: Annotated[Optional[str], Depends(oauth2_scheme)] = None,
    token_param: Annotated[Optional[str], Query(alias="token")] = None,
    session_cookie: Annotated[Optional[str], Cookie(alias=settings.COOKIE_NAME)] = None,
) -> User:
    """Auth dependency for /uploads/* — accepts token from Authorization header OR ?token= query param.

    Supports all three auth schemes so that <img> and <iframe> tags (which can't
    send Authorization headers) work by appending ?token=<jwt> to the URL.
    """
    auth_header = request.headers.get("Authorization", "")

    # 1. DeviceToken scheme (Authorization header only — device tokens aren't safe in URLs)
    if auth_header.startswith("DeviceToken "):
        device_token = auth_header[12:]  # len("DeviceToken ") = 12
        user = await _authenticate_device_token(session, device_token)
        if user:
            if user.status != UserStatus.active:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.INACTIVE_USER)
            return user
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthMessages.INVALID_DEVICE_TOKEN,
            headers={"WWW-Authenticate": "DeviceToken"},
        )

    # 2. Bearer token (Authorization header), ?token= query param, or HttpOnly cookie (web sessions)
    token = bearer_token or token_param or session_cookie
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthMessages.NOT_AUTHENTICATED,
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Try API key authentication first
    user = await api_keys_service.authenticate_api_key(session, token)
    if user:
        if user.status != UserStatus.active:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.INACTIVE_USER)
        return user

    # Try delegation JWT from initiative-auto. Same chain placement as
    # ``get_current_user`` so /uploads/* accepts auto-driven workflow
    # downloads without per-route changes. Falls through on shape /
    # algorithm / audience mismatch so a regular HS256 session JWT
    # arriving on the same header still hits the standard JWT branch
    # below.
    user = await _authenticate_auto_delegation(request, session, token)
    if user:
        # Delegation already enforces ``user.status == active``;
        # ``_authenticate_auto_delegation`` returned None otherwise.
        return user

    # Try JWT authentication. Expired / malformed tokens are 401 (not 403)
    # so the SPA can auto-redirect to /welcome when the session lapses.
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        token_data = TokenPayload(**payload)
    except jwt.PyJWTError:
        # JWT decode failed — if token came from query param, also try as device token
        # (native app users may pass their device token as a query param)
        if token_param and not bearer_token:
            user = await _authenticate_device_token(session, token_param)
            if user:
                if user.status != UserStatus.active:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.INACTIVE_USER)
                return user
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthMessages.COULD_NOT_VALIDATE_CREDENTIALS,
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not token_data.sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthMessages.INVALID_TOKEN_PAYLOAD,
            headers={"WWW-Authenticate": "Bearer"},
        )

    statement = select(User).where(User.id == int(token_data.sub))
    result = await session.exec(statement)
    user = result.one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND)
    if token_data.ver is None or token_data.ver != user.token_version:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=AuthMessages.INVALID_TOKEN)
    if user.status != UserStatus.active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.INACTIVE_USER)
    return user


UploadUserDep = Annotated[User, Depends(get_upload_user)]
