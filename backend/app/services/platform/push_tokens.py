"""Push-notification registrations (``push_tokens``).

A device registers and unregisters under its owner's platform tier, whose
policies admit that account's own rows. Delivery reads and prunes a
recipient's rows on the system engine (``push_notifications.send_push_to_user``).
"""

from datetime import datetime, timezone
from typing import Iterable, List, Optional

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select, delete, update
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
    user_id: int,
    push_token: str,
) -> bool:
    """Remove one of ``user_id``'s push tokens (on unregister or invalid
    token error). Scoped to the owner so a leaked token value can't be used
    to silence another user's devices.

    Returns True if a token was deleted, False otherwise.
    """
    stmt = delete(PushToken).where(
        PushToken.user_id == user_id,
        PushToken.push_token == push_token,
    )
    result = await session.exec(stmt)
    await session.commit()
    return result.rowcount > 0


async def purge_all(session: AsyncSession) -> int:
    """Drop every stored push token, and say how many.

    What a deployment switching push notifications off asks for: it stops
    sending, and it stops holding the addresses it was sending to. A device
    registers again the next time the app starts, so switching it back on
    restores delivery without anybody doing anything.
    """
    result = await session.exec(delete(PushToken))
    return result.rowcount or 0


async def record_delivery(
    session: AsyncSession,
    *,
    user_id: int,
    delivered_ids: Iterable[int],
    dead_tokens: Iterable[str],
) -> None:
    """Stamp the rows a push reached and drop the ones FCM reported gone.

    Both halves are scoped to ``user_id``, the account the push was for. Does
    not commit — the caller owns the transaction.
    """
    delivered = list(delivered_ids)
    if delivered:
        await session.exec(
            update(PushToken)
            .where(PushToken.user_id == user_id, PushToken.id.in_(delivered))
            .values(last_used_at=datetime.now(timezone.utc))
        )
    dead = list(dead_tokens)
    if dead:
        await session.exec(
            delete(PushToken).where(
                PushToken.user_id == user_id, PushToken.push_token.in_(dead)
            )
        )
