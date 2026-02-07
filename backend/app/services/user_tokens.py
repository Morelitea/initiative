from datetime import datetime, timedelta, timezone
import secrets
from typing import Optional, List

from sqlmodel import select, delete
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import reapply_rls_context
from app.models.user_token import UserToken, UserTokenPurpose


DEFAULT_TOKEN_TTL_MINUTES = 60
# Device tokens last 100 years (effectively never expire)
DEVICE_TOKEN_TTL_DAYS = 36500


async def _delete_existing_tokens(session: AsyncSession, user_id: int, purpose: UserTokenPurpose) -> None:
    """Delete existing tokens for a user with a specific purpose (except device_auth)."""
    # For device tokens, we allow multiple devices per user
    if purpose == UserTokenPurpose.device_auth:
        return
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
    await reapply_rls_context(session)
    await session.refresh(record)
    return record


async def purge_expired_tokens(session: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    stmt = delete(UserToken).where(UserToken.expires_at < now)
    await session.exec(stmt)
    await session.commit()


# Device token functions


async def create_device_token(
    session: AsyncSession,
    *,
    user_id: int,
    device_name: str,
) -> str:
    """Create a long-lived device token for mobile app authentication."""
    token_value = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(days=DEVICE_TOKEN_TTL_DAYS)
    token = UserToken(
        user_id=user_id,
        token=token_value,
        purpose=UserTokenPurpose.device_auth,
        device_name=device_name,
        expires_at=expires_at,
    )
    session.add(token)
    await session.commit()
    return token_value


async def get_device_token(
    session: AsyncSession,
    *,
    token: str,
) -> Optional[UserToken]:
    """Get a valid device token (not consumed, not expired)."""
    return await get_valid_token(session, token=token, purpose=UserTokenPurpose.device_auth)


async def get_user_device_tokens(
    session: AsyncSession,
    *,
    user_id: int,
) -> List[UserToken]:
    """Get all device tokens for a user."""
    now = datetime.now(timezone.utc)
    stmt = select(UserToken).where(
        UserToken.user_id == user_id,
        UserToken.purpose == UserTokenPurpose.device_auth,
        UserToken.consumed_at.is_(None),
        UserToken.expires_at > now,
    ).order_by(UserToken.created_at.desc())
    result = await session.exec(stmt)
    return list(result.all())


async def revoke_device_token(
    session: AsyncSession,
    *,
    token_id: int,
    user_id: int,
) -> bool:
    """Revoke a device token by marking it as consumed."""
    stmt = select(UserToken).where(
        UserToken.id == token_id,
        UserToken.user_id == user_id,
        UserToken.purpose == UserTokenPurpose.device_auth,
    )
    result = await session.exec(stmt)
    token = result.one_or_none()
    if not token:
        return False
    token.consumed_at = datetime.now(timezone.utc)
    session.add(token)
    await session.commit()
    return True
