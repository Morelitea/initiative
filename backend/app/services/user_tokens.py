from datetime import datetime, timedelta, timezone
import secrets
from typing import Optional

from sqlmodel import select, delete
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.user_token import UserToken, UserTokenPurpose


DEFAULT_TOKEN_TTL_MINUTES = 60


async def _delete_existing_tokens(session: AsyncSession, user_id: int, purpose: UserTokenPurpose) -> None:
    stmt = delete(UserToken).where(
        UserToken.user_id == user_id,
        UserToken.purpose == purpose,
    )
    await session.exec(stmt)


async def create_token(
    session: AsyncSession,
    *,
    user_id: int,
    purpose: UserTokenPurpose,
    expires_minutes: int = DEFAULT_TOKEN_TTL_MINUTES,
) -> str:
    await _delete_existing_tokens(session, user_id, purpose)
    token_value = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    token = UserToken(
        user_id=user_id,
        token=token_value,
        purpose=purpose,
        expires_at=expires_at,
    )
    session.add(token)
    await session.commit()
    return token_value


async def get_valid_token(
    session: AsyncSession,
    *,
    token: str,
    purpose: UserTokenPurpose,
) -> Optional[UserToken]:
    stmt = select(UserToken).where(
        UserToken.token == token,
        UserToken.purpose == purpose,
    )
    result = await session.exec(stmt)
    record = result.one_or_none()
    if not record:
        return None
    if record.consumed_at is not None:
        return None
    if record.expires_at < datetime.now(timezone.utc):
        return None
    return record


async def consume_token(
    session: AsyncSession,
    *,
    token: str,
    purpose: UserTokenPurpose,
) -> Optional[UserToken]:
    record = await get_valid_token(session, token=token, purpose=purpose)
    if not record:
        return None
    record.consumed_at = datetime.now(timezone.utc)
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record


async def purge_expired_tokens(session: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    stmt = delete(UserToken).where(UserToken.expires_at < now)
    await session.exec(stmt)
    await session.commit()
