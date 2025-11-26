from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Optional

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.db.session import get_session
from app.models.guild import Guild, GuildMembership, GuildRole
from app.models.user import User, UserRole
from app.schemas.token import TokenPayload
from app.services import api_keys as api_keys_service
from app.services import guilds as guilds_service

SessionDep = Annotated[AsyncSession, Depends(get_session)]

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/token")


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    session: SessionDep,
) -> User:
    user = await api_keys_service.authenticate_api_key(session, token)
    if user:
        return user

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        token_data = TokenPayload(**payload)
    except JWTError as exc:  # pragma: no cover - FastAPI handles formatting
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Could not validate credentials") from exc

    if not token_data.sub:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid token payload")

    statement = select(User).where(User.id == int(token_data.sub))
    result = await session.exec(statement)
    user = result.one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)]
) -> User:
    if not current_user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user")
    return current_user


def require_roles(*roles: UserRole) -> Callable:
    async def dependency(current_user: Annotated[User, Depends(get_current_active_user)]) -> User:
        if roles and current_user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient privileges")
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
    guild_id = await guilds_service.resolve_user_guild_id(
        session,
        user=current_user,
        guild_id=requested_guild_id,
    )
    membership = await guilds_service.get_membership(
        session,
        guild_id=guild_id,
        user_id=current_user.id,
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Guild access denied")
    guild = await guilds_service.get_guild(session, guild_id=guild_id)
    return GuildContext(guild=guild, membership=membership)


def require_guild_roles(*roles: GuildRole) -> Callable:
    async def dependency(context: Annotated[GuildContext, Depends(get_guild_membership)]) -> GuildContext:
        if roles and context.membership.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Guild permission required")
        return context

    return dependency
