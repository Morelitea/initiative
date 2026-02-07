from datetime import datetime, timezone
from typing import List, Optional

from sqlmodel import select, delete
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import reapply_rls_context
from app.models.push_token import PushToken


async def register_push_token(
    session: AsyncSession,
    *,
    user_id: int,
    push_token: str,
    platform: str,
    device_token_id: Optional[int] = None,
) -> PushToken:
    """Register or update a push notification token for a user.

    Uses upsert logic on (user_id, push_token) to handle token refresh/rotation.
    If the token already exists, update the updated_at timestamp.
    """
    # Check if token already exists for this user
    stmt = select(PushToken).where(
        PushToken.user_id == user_id,
        PushToken.push_token == push_token,
    )
    result = await session.exec(stmt)
    existing_token = result.one_or_none()

    if existing_token:
        # Update existing token
        existing_token.platform = platform
        existing_token.device_token_id = device_token_id
        existing_token.updated_at = datetime.now(timezone.utc)
        session.add(existing_token)
        await session.commit()
        await reapply_rls_context(session)
        await session.refresh(existing_token)
        return existing_token
    else:
        # Create new token
        new_token = PushToken(
            user_id=user_id,
            push_token=push_token,
            platform=platform,
            device_token_id=device_token_id,
        )
        session.add(new_token)
        await session.commit()
        await reapply_rls_context(session)
        await session.refresh(new_token)
        return new_token


async def get_push_tokens_for_user(
    session: AsyncSession,
    *,
    user_id: int,
) -> List[PushToken]:
    """Get all active push tokens for a user."""
    stmt = select(PushToken).where(
        PushToken.user_id == user_id,
    ).order_by(PushToken.created_at.desc())
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


async def delete_push_token_by_id(
    session: AsyncSession,
    *,
    token_id: int,
    user_id: int,
) -> bool:
    """Delete a push token by ID (must belong to the user).

    Returns True if a token was deleted, False otherwise.
    """
    stmt = delete(PushToken).where(
        PushToken.id == token_id,
        PushToken.user_id == user_id,
    )
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


async def delete_tokens_by_device_token_id(
    session: AsyncSession,
    *,
    device_token_id: int,
) -> int:
    """Delete all push tokens associated with a device token.

    This is useful when a device token is revoked - we should also remove
    all push tokens for that device.

    Returns the number of tokens deleted.
    """
    stmt = delete(PushToken).where(PushToken.device_token_id == device_token_id)
    result = await session.exec(stmt)
    await session.commit()
    return result.rowcount  # type: ignore
