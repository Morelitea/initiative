from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Optional

from fastapi import Cookie, Depends, Header, HTTPException, Query, Request, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.messages import AuthMessages, GuildMessages
from app.db.session import get_session, set_rls_context
from app.models.guild import Guild, GuildMembership, GuildRole
from app.models.user import User, UserRole
from app.schemas.token import TokenPayload
from app.services import api_keys as api_keys_service
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
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=AuthMessages.INVALID_DEVICE_TOKEN)

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

    # Try JWT authentication
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        token_data = TokenPayload(**payload)
    except jwt.PyJWTError as exc:  # pragma: no cover - FastAPI handles formatting
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=AuthMessages.COULD_NOT_VALIDATE_CREDENTIALS) from exc

    if not token_data.sub:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=AuthMessages.INVALID_TOKEN_PAYLOAD)

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
    if not current_user.is_active:
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
            if not user.is_active:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.INACTIVE_USER)
            return user
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=AuthMessages.INVALID_DEVICE_TOKEN)

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
        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.INACTIVE_USER)
        return user

    # Try JWT authentication
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        token_data = TokenPayload(**payload)
    except jwt.PyJWTError:
        # JWT decode failed — if token came from query param, also try as device token
        # (native app users may pass their device token as a query param)
        if token_param and not bearer_token:
            user = await _authenticate_device_token(session, token_param)
            if user:
                if not user.is_active:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.INACTIVE_USER)
                return user
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=AuthMessages.COULD_NOT_VALIDATE_CREDENTIALS)

    if not token_data.sub:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=AuthMessages.INVALID_TOKEN_PAYLOAD)

    statement = select(User).where(User.id == int(token_data.sub))
    result = await session.exec(statement)
    user = result.one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND)
    if token_data.ver is None or token_data.ver != user.token_version:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=AuthMessages.INVALID_TOKEN)
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.INACTIVE_USER)
    return user


UploadUserDep = Annotated[User, Depends(get_upload_user)]
