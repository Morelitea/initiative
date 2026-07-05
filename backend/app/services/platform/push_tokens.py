from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select, delete
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.push_token import PushToken


async def register_push_token(
    session: AsyncSession,
    *,
    user_id: int,
    push_token: str,
    platform: str,
    device_token_id: Optional[int] = None,
) -> PushToken:
    """Register or update a push notification token for a user.

    Uses a PostgreSQL upsert on (user_id, push_token) to atomically handle
    token refresh/rotation without a race-condition between SELECT and INSERT.
    """
    now = datetime.now(timezone.utc)
    stmt = (
        pg_insert(PushToken)
        .values(
            user_id=user_id,
            push_token=push_token,
            platform=platform,
            device_token_id=device_token_id,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_update(
            index_elements=["user_id", "push_token"],
            set_=dict(
                platform=platform,
                device_token_id=device_token_id,
                updated_at=now,
            ),
        )
        .returning(PushToken)
    )
    result = await session.exec(stmt)
    await session.commit()
    return result.scalars().one()


async def get_push_tokens_for_user(
    session: AsyncSession,
    *,
    user_id: int,
) -> List[PushToken]:
    """Get all active push tokens for a user."""
    stmt = (
        select(PushToken)
        .where(
            PushToken.user_id == user_id,
        )
        .order_by(PushToken.created_at.desc())
    )
    result = await session.exec(stmt)
    return list(result.all())


async def delete_push_token(
    session: AsyncSession,
    *,
    push_token: str,
) -> bool:
    """Remove a push token (on unregister or invalid token error).

    Returns True if a token was deleted, False otherwise.
    """
    stmt = delete(PushToken).where(PushToken.push_token == push_token)
    result = await session.exec(stmt)
    await session.commit()
    return result.rowcount > 0  # type: ignore


async def update_last_used(
    session: AsyncSession,
    *,
    push_token: str,
) -> None:
    """Track successful delivery by updating last_used_at timestamp."""
    stmt = select(PushToken).where(PushToken.push_token == push_token)
    result = await session.exec(stmt)
    token = result.one_or_none()

    if token:
        token.last_used_at = datetime.now(timezone.utc)
        session.add(token)
        await session.commit()
