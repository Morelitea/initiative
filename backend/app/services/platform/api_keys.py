from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from secrets import token_urlsafe
from typing import Optional, Sequence, Tuple

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.models.platform.api_key import UserApiKey
from app.models.platform.user import User, UserStatus
from app.services import audit as audit_service

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
    # Flushed first so the record can name the key it describes.
    await session.flush()
    await _record_key_event(
        session, AuditEventType.API_KEY_CREATED, user_id=user.id, api_key=api_key
    )
    await session.commit()
    await session.refresh(api_key)
    return secret, api_key


async def _record_key_event(
    session: AsyncSession,
    event_type: AuditEventType,
    *,
    user_id: int,
    api_key: UserApiKey,
) -> None:
    """Record one key's arrival or departure.

    A key is the account's own credential, so it is both actor and subject. The
    record carries the key's scope — never its name, its prefix or its hash.
    """
    await audit_service.record(
        session,
        event_type=event_type,
        actor_user_id=user_id,
        target_user_id=user_id,
        guild_id=api_key.guild_id,
        target_type="user_api_key",
        target_id=api_key.id,
        detail={
            "read_only": api_key.read_only,
            "expires_at": (
                api_key.expires_at.isoformat() if api_key.expires_at else None
            ),
            "guild_bound": api_key.guild_id is not None,
        },
    )


async def delete_api_key(session: AsyncSession, *, user: User, api_key_id: int) -> bool:
    statement = select(UserApiKey).where(
        UserApiKey.id == api_key_id, UserApiKey.user_id == user.id
    )
    result = await session.exec(statement)
    api_key = result.one_or_none()
    if not api_key:
        return False

    await _record_key_event(
        session, AuditEventType.API_KEY_DELETED, user_id=user.id, api_key=api_key
    )
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

    ``user_api_keys`` is a pre-auth credential store (looked up by ``token_hash``
    before the user is known), so it carries no request-path grant and no own-row
    policy — the lookup runs on the system engine (``SystemSessionLocal``), like
    ``auth_sessions``. The resolved ``User`` is loaded on the caller's request
    ``session`` so it stays attached for the rest of the request; only the
    detached ``api_key``'s already-loaded scope columns are read downstream.
    """
    from app.db.session import SystemSessionLocal

    token_hash = _hash_token(token)
    async with SystemSessionLocal() as system_session:
        statement = select(UserApiKey).where(
            UserApiKey.token_hash == token_hash, UserApiKey.is_active.is_(True)
        )
        api_key = (await system_session.exec(statement)).one_or_none()
        if not api_key:
            return None

        now = datetime.now(timezone.utc)
        if api_key.expires_at and api_key.expires_at <= now:
            return None

        user = (
            await session.exec(select(User).where(User.id == api_key.user_id))
        ).one_or_none()
        if not user or user.status != UserStatus.active:
            return None

        # Record use only once an active user is confirmed (matches prior order).
        api_key.last_used_at = now
        await system_session.commit()

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
