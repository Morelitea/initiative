from datetime import datetime, timedelta, timezone
from hashlib import sha256
import secrets
from typing import Optional, List

from sqlmodel import select, delete, update as sql_update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import reapply_rls_context
from app.models.user import User
from app.models.user_token import UserToken, UserTokenPurpose


DEFAULT_TOKEN_TTL_MINUTES = 60
# Device tokens are sliding-window: capped at this many days from last use.
# Presenting the token (see ``get_device_token``) refreshes the expiry, so an
# actively-used device stays logged in indefinitely while an abandoned token
# dies within the cap.
DEVICE_TOKEN_TTL_DAYS = 90
# Refreshing expiry on every single request would write to the DB on every
# authenticated call. The window is only re-slid once the previous slide is
# more than a day old — i.e. when the remaining lifetime has dropped below
# ``TTL - 1 day`` — so an active device writes at most ~once/day while its
# expiry still tracks last use to within a day.
DEVICE_TOKEN_SLIDING_REFRESH_THRESHOLD = timedelta(days=DEVICE_TOKEN_TTL_DAYS - 1)


def _hash_token(token: str) -> str:
    """Hash a token for storage/lookup.

    Tokens are high-entropy random secrets (``secrets.token_urlsafe(48)``), so a
    single unsalted SHA-256 is sufficient and keeps lookups indexable — this
    mirrors ``app.services.api_keys._hash_token``.
    """
    return sha256(token.encode("utf-8")).hexdigest()


async def _delete_existing_tokens(
    session: AsyncSession, user_id: int, purpose: UserTokenPurpose
) -> None:
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
        token=_hash_token(token_value),
        purpose=purpose,
        expires_at=expires_at,
    )
    session.add(token)
    await session.commit()
    # Return the raw token exactly once; only its hash is persisted.
    return token_value


async def get_valid_token(
    session: AsyncSession,
    *,
    token: str,
    purpose: UserTokenPurpose,
) -> Optional[UserToken]:
    stmt = select(UserToken).where(
        UserToken.token == _hash_token(token),
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
    """Create a sliding-window device token for mobile app authentication."""
    token_value = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(days=DEVICE_TOKEN_TTL_DAYS)
    token = UserToken(
        user_id=user_id,
        token=_hash_token(token_value),
        purpose=UserTokenPurpose.device_auth,
        device_name=device_name,
        expires_at=expires_at,
    )
    session.add(token)
    await session.commit()
    # Return the raw token exactly once; only its hash is persisted.
    return token_value


async def get_device_token(
    session: AsyncSession,
    *,
    token: str,
) -> Optional[UserToken]:
    """Get a valid device token (not consumed, not expired) and slide its expiry.

    Device tokens use a sliding 90-day window: each successful presentation
    pushes ``expires_at`` to now + ``DEVICE_TOKEN_TTL_DAYS`` so an actively-used
    device never has to re-authenticate, while an abandoned token expires within
    the cap. The write is throttled (only once the remaining lifetime falls below
    ``DEVICE_TOKEN_SLIDING_REFRESH_THRESHOLD``, i.e. at most ~once/day) to avoid
    a DB write on every call.
    """
    record = await get_valid_token(
        session, token=token, purpose=UserTokenPurpose.device_auth
    )
    if record is None:
        return None
    now = datetime.now(timezone.utc)
    if record.expires_at - now < DEVICE_TOKEN_SLIDING_REFRESH_THRESHOLD:
        record.expires_at = now + timedelta(days=DEVICE_TOKEN_TTL_DAYS)
        session.add(record)
        await session.commit()
        await reapply_rls_context(session)
        await session.refresh(record)
    return record


async def get_user_device_tokens(
    session: AsyncSession,
    *,
    user_id: int,
) -> List[UserToken]:
    """Get all device tokens for a user."""
    now = datetime.now(timezone.utc)
    stmt = (
        select(UserToken)
        .where(
            UserToken.user_id == user_id,
            UserToken.purpose == UserTokenPurpose.device_auth,
            UserToken.consumed_at.is_(None),
            UserToken.expires_at > now,
        )
        .order_by(UserToken.created_at.desc())
    )
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


async def revoke_active_device_tokens(
    session: AsyncSession,
    *,
    user_id: int,
) -> None:
    """Mark every active device token for a user as consumed.

    Used after a password change/reset so previously-issued long-lived
    device tokens can no longer authenticate. Does not commit — the caller
    owns the surrounding transaction.
    """
    await session.exec(
        sql_update(UserToken)
        .where(
            UserToken.user_id == user_id,
            UserToken.purpose == UserTokenPurpose.device_auth,
            UserToken.consumed_at.is_(None),
        )
        .values(consumed_at=datetime.now(timezone.utc))
    )


async def revoke_user_sessions(
    session: AsyncSession,
    *,
    user: User,
) -> None:
    """Invalidate every outstanding session for ``user`` after a credential
    change.

    Bumps ``token_version`` (which the JWT/WS authenticators compare against,
    invalidating any still-unexpired access token) and bulk-revokes the
    user's active ``device_auth`` tokens. Shared by the self-service password
    change, the forgot-password reset, and the admin password reset so the
    three paths can't drift. Does not commit — the caller owns the transaction
    and is responsible for ``session.add(user)``/``commit``.
    """
    user.token_version += 1
    await revoke_active_device_tokens(session, user_id=user.id)
