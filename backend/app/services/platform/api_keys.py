from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from secrets import token_urlsafe
from typing import Optional, Sequence, Tuple

from sqlmodel import select
from app.db.session import reapply_rls_context
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.api_key import UserApiKey
from app.models.platform.user import User, UserStatus

API_KEY_PREFIX = "ppk_"
API_KEY_DISPLAY_PREFIX_LENGTH = 12


def _hash_token(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def _generate_secret() -> str:
    return f"{API_KEY_PREFIX}{token_urlsafe(32)}"


async def list_api_keys(session: AsyncSession, *, user: User) -> Sequence[UserApiKey]:
    statement = (
        select(UserApiKey)
        .where(UserApiKey.user_id == user.id)
        .order_by(UserApiKey.created_at.desc())
    )
    result = await session.exec(statement)
    return result.all()


async def create_api_key(
    session: AsyncSession,
    *,
    user: User,
    name: str,
    expires_at: Optional[datetime] = None,
    read_only: bool = False,
    guild_id: Optional[int] = None,
) -> Tuple[str, UserApiKey]:
    if not user.id:
        raise ValueError("User must be persisted before creating API keys")

    secret = _generate_secret()
    api_key = UserApiKey(
        user_id=user.id,
        name=name,
        token_prefix=secret[:API_KEY_DISPLAY_PREFIX_LENGTH],
        token_hash=_hash_token(secret),
        expires_at=expires_at,
        read_only=read_only,
        guild_id=guild_id,
    )
    session.add(api_key)
    await session.commit()
    await reapply_rls_context(session)
    await session.refresh(api_key)
    return secret, api_key


async def delete_api_key(session: AsyncSession, *, user: User, api_key_id: int) -> bool:
    statement = select(UserApiKey).where(
        UserApiKey.id == api_key_id, UserApiKey.user_id == user.id
    )
    result = await session.exec(statement)
    api_key = result.one_or_none()
    if not api_key:
        return False

    await session.delete(api_key)
    await session.commit()
    return True


async def authenticate_api_key(
    session: AsyncSession, token: str
) -> Optional[Tuple[User, UserApiKey]]:
    """Resolve a ``ppk_`` token to its ``(user, key)`` pair, or ``None``.

    Returns the key alongside the user so callers can enforce its scope
    (``read_only`` / ``guild_id``) — the user object alone carries no record of
    which credential authenticated the request.
    """
    token_hash = _hash_token(token)
    statement = select(UserApiKey).where(
        UserApiKey.token_hash == token_hash, UserApiKey.is_active.is_(True)
    )
    result = await session.exec(statement)
    api_key = result.one_or_none()
    if not api_key:
        return None

    now = datetime.now(timezone.utc)
    if api_key.expires_at and api_key.expires_at <= now:
        return None

    user_result = await session.exec(select(User).where(User.id == api_key.user_id))
    user = user_result.one_or_none()
    if not user or user.status != UserStatus.active:
        return None

    api_key.last_used_at = now
    await session.commit()
    return user, api_key


async def deactivate_user_api_keys(session: AsyncSession, *, user_id: int) -> int:
    """Deactivate every active API key for ``user_id`` and return the count.

    Invoked from the credential-reset path so a password change / reset also
    locks out outstanding keys (a leaked key must not survive a compromise
    response). Does not commit — the caller owns the transaction.
    """
    statement = select(UserApiKey).where(
        UserApiKey.user_id == user_id, UserApiKey.is_active.is_(True)
    )
    result = await session.exec(statement)
    keys = result.all()
    for key in keys:
        key.is_active = False
        session.add(key)
    return len(keys)
