"""Push-notification registrations (``push_tokens``).

A device registers and unregisters under its owner's platform tier, whose
policies admit that account's own rows. Delivery reads and prunes a
recipient's rows on the system engine (``push_notifications.send_push_to_user``).
"""

import uuid
from datetime import datetime, timezone
from typing import Iterable, List, Optional

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import and_, or_
from sqlmodel import select, delete, update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.push_token import PushToken
from app.services.auth import sessions as session_service
from app.services.platform import user_tokens


async def register_push_token(
    session: AsyncSession,
    *,
    user_id: int,
    push_token: str,
    platform: str,
    device_token_id: Optional[int] = None,
    session_id: Optional[uuid.UUID] = None,
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
            session_id=session_id,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_update(
            index_elements=["user_id", "push_token"],
            set_=dict(
                platform=platform,
                device_token_id=device_token_id,
                session_id=session_id,
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


async def live_for_user(session: AsyncSession, *, user_id: int) -> List[PushToken]:
    """The recipient's devices whose sign-in still stands.

    A row stands while the session that registered it has a live chain, or,
    registered under a device token, while that token is good. A row that
    names neither stands for nothing; the app registers again each time it
    starts. Rows whose sign-in has ended are removed, and a row whose session
    was renewed moves to the live row. Does not commit — the caller owns the
    transaction.
    """
    rows = await get_push_tokens_for_user(session, user_id=user_id)
    tips = await session_service.live_chain_tips(
        session, session_ids={r.session_id for r in rows if r.session_id}
    )
    devices = await user_tokens.live_device_token_ids(
        session, token_ids={r.device_token_id for r in rows if r.device_token_id}
    )
    live: List[PushToken] = []
    ended: List[PushToken] = []
    for row in rows:
        if row.session_id is not None:
            tip = tips.get(row.session_id)
            if tip is None:
                ended.append(row)
                continue
            if tip != row.session_id:
                await follow_session(session, from_id=row.session_id, to_id=tip)
            live.append(row)
        elif row.device_token_id in devices:
            live.append(row)
        else:
            ended.append(row)
    if ended:
        # Only a row still naming the sign-in read above: one registered again
        # in the meantime names its new session and stays.
        await session.exec(
            delete(PushToken).where(
                PushToken.user_id == user_id,
                or_(
                    *(
                        and_(
                            PushToken.id == row.id,
                            PushToken.session_id.is_not_distinct_from(row.session_id),
                            PushToken.device_token_id.is_not_distinct_from(
                                row.device_token_id
                            ),
                        )
                        for row in ended
                    )
                ),
            )
        )
    return live


async def follow_session(
    session: AsyncSession, *, from_id: uuid.UUID, to_id: uuid.UUID
) -> None:
    """Move the devices one session registered to the session taking its place.

    Called wherever a session is succeeded — a refresh, a step-up, a
    replacement — so a device's row names a live row of its sign-in. Does not
    commit: it lands with the session change.
    """
    await session.exec(
        update(PushToken)
        .where(PushToken.session_id == from_id)
        .values(session_id=to_id)
    )


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
