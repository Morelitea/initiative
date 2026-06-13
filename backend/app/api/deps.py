from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import Cookie, Depends, HTTPException, Path, Query, Request, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.capabilities import Capability, user_has_capability
from app.core.config import settings
from app.core.pam_context import set_active_grant
from app.core.role_context import set_active_role
from app.core.messages import AuthMessages, GuildMessages
from app.core.security import (
    AutoDelegationVerificationError,
    UploadTokenError,
    verify_auto_delegation_token,
    verify_upload_token,
)
from app.db.session import get_session, set_rls_context
from app.models.access_grant import AccessGrant, AccessLevel
from app.models.guild import Guild, GuildMembership, GuildRole
from app.models.user import User, UserRole, UserStatus
from app.schemas.token import TokenPayload
from app.services import access_grants as access_grants_service
from app.services import api_keys as api_keys_service
from app.services import auto_delegation_blocklist
from app.services import guilds as guilds_service
from app.services import user_tokens

SessionDep = Annotated[AsyncSession, Depends(get_session)]

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/token", auto_error=False
)


async def _authenticate_device_token(
    session: AsyncSession, token: str
) -> Optional[User]:
    """Authenticate using a device token and return the associated user."""
    device_token = await user_tokens.get_device_token(session, token=token)
    if not device_token:
        return None
    statement = select(User).where(User.id == device_token.user_id)
    result = await session.exec(statement)
    return result.one_or_none()


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

    Two security checks fire here in order:
      1. Token verifies (signature, audience, issuer, required claims).
      2. ``jti`` is not in the blocklist — first presentation only.

    A verified token also pins the request's guild context to the token's
    ``guild_id`` claim (via ``request.state.delegated_guild_id``): delegation
    tokens are minted for exactly one guild, and a machine caller has no
    server-held context of its own to resolve from. The claim takes
    precedence over the named user's ``active_guild_id`` flag, so an auto
    workflow always acts in the guild its token was issued for — never in
    whatever guild the human happens to be viewing.
    """
    if not settings.AUTO_DELEGATION_PUBLIC_KEY_PEM:
        return None  # delegation disabled — let other auth paths run

    try:
        claims = verify_auto_delegation_token(token)
    except AutoDelegationVerificationError:
        # Could be a session JWT or API key arriving on the same header.
        # Returning None lets the caller try those instead of failing.
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

    # Bind the request to the token's guild (see docstring). Stored on
    # request.state so the guild-context resolver can read it without the
    # claims object having to travel through every auth signature.
    request.state.delegated_guild_id = claims.guild_id

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
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND
        )
    if token_data.ver is None or token_data.ver != user.token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=AuthMessages.INVALID_TOKEN
        )
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
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    if current_user.status != UserStatus.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.INACTIVE_USER
        )
    return current_user


def require_roles(*roles: UserRole) -> Callable:
    async def dependency(
        current_user: Annotated[User, Depends(get_current_active_user)],
    ) -> User:
        if roles and current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=AuthMessages.INSUFFICIENT_PRIVILEGES,
            )
        return current_user

    return dependency


def require_capability(capability: Capability) -> Callable:
    """Dependency factory gating an endpoint on a platform capability.

    Prefer this over ``require_roles`` for platform-level authorization so
    access is expressed against the capability model rather than a hardcoded
    role name (see ``app.core.capabilities``).
    """

    async def dependency(
        current_user: Annotated[User, Depends(get_current_active_user)],
    ) -> User:
        if not user_has_capability(current_user, capability):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=AuthMessages.INSUFFICIENT_PRIVILEGES,
            )
        return current_user

    return dependency


@dataclass
class GuildContext:
    guild: Guild
    membership: GuildMembership
    # Set when access is via a time-bound PAM grant rather than real
    # membership. The ``membership`` is then a synthesized member-role stand-in
    # so ``.role`` stays valid for endpoint guards, while RLS context is driven
    # off the grant (scoped pam_read/pam_write, not the all-guild bypass).
    grant: Optional[AccessGrant] = None

    @property
    def guild_id(self) -> int:
        return self.guild.id  # ty: ignore[invalid-return-type]

    @property
    def role(self) -> GuildRole:
        return self.membership.role

    @property
    def is_pam(self) -> bool:
        return self.grant is not None


async def _load_guild_context(
    request: Request,
    session: AsyncSession,
    current_user: User,
    guild_id: int,
) -> GuildContext:
    """Resolve and validate the guild context for the path-addressed guild.

    The guild comes from the request path (``/g/{guild_id}/...``); it is only
    a selector, never a trust boundary. Access is validated fresh on every
    request — real membership or a live PAM grant, else 403 — so a forged or
    stale path can never read another guild's data. The ``int`` path converter
    guarantees ``guild_id`` is an integer before it reaches the privileged
    ``SET ROLE``/``search_path`` sink.
    """
    # Auto-delegation tokens are pinned to one guild at mint time; refuse if the
    # path addresses a different guild than the token was minted for.
    delegated = getattr(request.state, "delegated_guild_id", None)
    if delegated is not None and delegated != guild_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildMessages.GUILD_ACCESS_DENIED,
        )

    # Set minimal RLS context before querying guild_memberships (RLS-protected).
    # Full guild context is set later by get_guild_session / RLSSessionDep.
    await set_rls_context(
        session,
        user_id=current_user.id,
        is_superadmin=user_has_capability(current_user, Capability.DATA_BYPASS),
    )

    membership = await guilds_service.get_membership(
        session,
        guild_id=guild_id,
        user_id=current_user.id,
    )
    if membership is None:
        # No standing membership — fall back to a live PAM grant for this
        # guild. The grantee can read (and write, if read_write) within the
        # grant's window; RLS scopes it to this one guild via the pam flags
        # set in get_guild_session. A synthesized member-role membership keeps
        # ``GuildContext.role`` valid for endpoint guards without conferring
        # any guild privilege on its own.
        grant = await access_grants_service.get_live_grant(
            session, user_id=current_user.id, guild_id=guild_id
        )
        if grant is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=GuildMessages.GUILD_ACCESS_DENIED,
            )
        # Apply the pam context now so the grantee can actually read the guild
        # row (and below, get_guild_session re-applies the full context). The
        # guilds table has an additive pam_read policy keyed on pam_guild_id.
        await set_rls_context(
            session,
            user_id=current_user.id,
            pam_guild_id=guild_id,
            pam_read=True,
            pam_write=(grant.access_level == AccessLevel.read_write.value),
        )
        guild = await guilds_service.get_guild(session, guild_id=guild_id)
        synthetic = GuildMembership(
            guild_id=guild_id, user_id=current_user.id, role=GuildRole.member
        )
        return GuildContext(guild=guild, membership=synthetic, grant=grant)
    guild = await guilds_service.get_guild(session, guild_id=guild_id)
    return GuildContext(guild=guild, membership=membership)


async def get_guild_membership(
    request: Request,
    session: SessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_id: Annotated[int, Path(description="Guild this request operates in")],
) -> GuildContext:
    """Strict guild context resolved from the ``/g/{guild_id}`` path segment.

    Every guild-scoped router mounts under that prefix, so FastAPI injects
    ``guild_id`` from the path into this dependency. Membership (or a live PAM
    grant) is validated fresh; a non-member or stale grant gets 403. A
    guild-scoped route mounted *outside* the prefix fails at startup (missing
    path param) — a useful guard that every such route is path-addressed.
    """
    return await _load_guild_context(request, session, current_user, guild_id)


def require_guild_roles(*roles: GuildRole) -> Callable:
    async def dependency(
        context: Annotated[GuildContext, Depends(get_guild_membership)],
    ) -> GuildContext:
        if roles and context.membership.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=GuildMessages.GUILD_PERMISSION_REQUIRED,
            )
        return context

    return dependency


async def _apply_guild_session_context(
    session: AsyncSession,
    current_user: User,
    guild_context: GuildContext,
) -> AsyncSession:
    """Route ``session`` into ``guild_context``'s guild: set the RLS/session
    variables (and the request-scoped PAM/role contexts) for the user+guild,
    PAM-scoped when access is via a grant."""
    if guild_context.is_pam:
        # Scoped, time-bound access via a PAM grant — NOT the all-guild bypass.
        # Read grants get SELECT into this guild only; read_write also gets
        # writes. guild_role is left unset so guild-role-gated paths don't treat
        # the grantee as a member.
        grant = guild_context.grant
        access_level = (
            grant.access_level if grant is not None else AccessLevel.read.value
        )
        # Mirror the grant into the request-scoped PAM context so the app-layer
        # resource access checks (require_*_access) honor it consistently with
        # RLS — what the grantee can list, they can also open/edit per level.
        set_active_grant(guild_context.guild_id, access_level)
        # No real membership — leave the role context clear so role-gated
        # paths (initiative-scope guild-admin bypass) don't treat the grantee
        # as a member.
        set_active_role(None, None)
        # Leave current_guild_id unset — the existing write policies treat a
        # matching current_guild_id as proof of membership. Scope the grant via
        # pam_guild_id instead.
        await set_rls_context(
            session,
            user_id=current_user.id,
            guild_id=None,
            guild_role=None,
            is_superadmin=False,
            pam_guild_id=guild_context.guild_id,
            pam_read=True,
            pam_write=(access_level == AccessLevel.read_write.value),
        )
        return session

    set_active_grant(None, None)
    # Record the membership role for this request's active guild so the sync
    # access checks can apply the guild-admin leg of the initiative-scope gate.
    set_active_role(guild_context.guild_id, guild_context.role.value)
    await set_rls_context(
        session,
        user_id=current_user.id,
        guild_id=guild_context.guild_id,
        guild_role=guild_context.role.value,
        is_superadmin=user_has_capability(current_user, Capability.DATA_BYPASS),
    )
    return session


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
    return await _apply_guild_session_context(session, current_user, guild_context)


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
        is_superadmin=user_has_capability(current_user, Capability.DATA_BYPASS),
    )
    return session


# Dependency for routes that need user-level RLS without guild context
UserSessionDep = Annotated[AsyncSession, Depends(get_user_session)]


async def _load_active_user_by_id(session: AsyncSession, user_id: int) -> User:
    """Load a user by id for the uploads route, enforcing active status.

    Shared by the scoped-upload-token path so a deactivated account can't
    keep pulling media with a still-valid token.
    """
    statement = select(User).where(User.id == user_id)
    result = await session.exec(statement)
    user = result.one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND
        )
    if user.status != UserStatus.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.INACTIVE_USER
        )
    return user


async def _authenticate_upload_query_token(
    session: AsyncSession, token_param: str
) -> User:
    """Resolve a ``?token=`` query-param credential for /uploads/*.

    Query params leak via logs, browser history, and Referer headers, so this
    path deliberately accepts ONLY URL-safe, narrowly-scoped credentials:

      1. A short-lived, uploads-scoped JWT minted by ``POST /auth/upload-token``
         (native <img>/<iframe> media loads can't send headers or cookies).
      2. A device token (native long-lived credential, already used this way).

    It intentionally does NOT accept a full session JWT or an API key — those
    are long-lived, full-API credentials that must never ride in a URL. A
    session JWT presented here therefore 401s.
    """
    # 1. Scoped upload token (preferred for native media).
    try:
        user_id = verify_upload_token(token_param)
    except UploadTokenError:
        pass
    else:
        return await _load_active_user_by_id(session, user_id)

    # 2. Device token fallback (native apps historically pass these as ?token=).
    user = await _authenticate_device_token(session, token_param)
    if user:
        if user.status != UserStatus.active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=AuthMessages.INACTIVE_USER,
            )
        return user

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=AuthMessages.COULD_NOT_VALIDATE_CREDENTIALS,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_upload_user(
    request: Request,
    session: SessionDep,
    bearer_token: Annotated[Optional[str], Depends(oauth2_scheme)] = None,
    token_param: Annotated[Optional[str], Query(alias="token")] = None,
    session_cookie: Annotated[Optional[str], Cookie(alias=settings.COOKIE_NAME)] = None,
) -> User:
    """Auth dependency for /uploads/* and authenticated document downloads.

    Two trust tiers, by where the credential arrives:

      * Authorization header or HttpOnly cookie — not exposed in URLs, so the
        full credential set is honored (session JWT, API key, delegation JWT,
        DeviceToken scheme). This is the web <img> path (cookie) and direct API
        callers.
      * ``?token=`` query param — leaks via logs/history/Referer, so only a
        short-lived uploads-scoped token or a device token is accepted (see
        ``_authenticate_upload_query_token``). A full session JWT here is
        rejected; native clients fetch a scoped token from
        ``POST /auth/upload-token`` instead.
    """
    auth_header = request.headers.get("Authorization", "")

    # 1. DeviceToken scheme (Authorization header only — device tokens aren't safe in URLs)
    if auth_header.startswith("DeviceToken "):
        device_token = auth_header[12:]  # len("DeviceToken ") = 12
        user = await _authenticate_device_token(session, device_token)
        if user:
            if user.status != UserStatus.active:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=AuthMessages.INACTIVE_USER,
                )
            return user
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthMessages.INVALID_DEVICE_TOKEN,
            headers={"WWW-Authenticate": "DeviceToken"},
        )

    # 2. Header bearer or cookie carries the full-trust credential. A ?token=
    #    query param, by contrast, is restricted to URL-safe scoped credentials.
    header_token = bearer_token or session_cookie
    if not header_token:
        if token_param:
            return await _authenticate_upload_query_token(session, token_param)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthMessages.NOT_AUTHENTICATED,
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = header_token

    # Try API key authentication first
    user = await api_keys_service.authenticate_api_key(session, token)
    if user:
        if user.status != UserStatus.active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=AuthMessages.INACTIVE_USER,
            )
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
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        token_data = TokenPayload(**payload)
    except jwt.PyJWTError:
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND
        )
    if token_data.ver is None or token_data.ver != user.token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=AuthMessages.INVALID_TOKEN
        )
    if user.status != UserStatus.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.INACTIVE_USER
        )
    return user


UploadUserDep = Annotated[User, Depends(get_upload_user)]
