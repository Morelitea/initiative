import logging
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import secrets
from typing import Optional, List

from sqlmodel import select, delete, update as sql_update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.user import User
from app.models.platform.user_token import UserToken, UserTokenPurpose
from app.services.auth import sessions as session_service
from app.services.platform import api_keys as api_keys_service


DEFAULT_TOKEN_TTL_MINUTES = 60
# Device tokens are sliding-window: capped at this many days from last use.
# Presenting the token (see ``get_device_token``) refreshes the expiry, so an
# actively-used device stays logged in indefinitely while an abandoned token
# dies within the cap.
logger = logging.getLogger(__name__)

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
    session: AsyncSession,
    user_id: int,
    purpose: UserTokenPurpose,
    user_email_id: int | None = None,
) -> None:
    """Drop the outstanding tokens a new one replaces.

    Scoped to the address when there is one: an account proving two addresses
    has one pending token per address, and issuing the second must not spend
    the first. Device tokens are per device and replace nothing.
    """
    if purpose == UserTokenPurpose.device_auth:
        return
    stmt = delete(UserToken).where(
        UserToken.user_id == user_id,
        UserToken.purpose == purpose,
    )
    stmt = stmt.where(
        UserToken.user_email_id == user_email_id
        if user_email_id is not None
        else UserToken.user_email_id.is_(None)
    )
    await session.exec(stmt)


async def create_token(
    session: AsyncSession,
    *,
    user_id: int,
    purpose: UserTokenPurpose,
    expires_minutes: int = DEFAULT_TOKEN_TTL_MINUTES,
    user_email_id: int | None = None,
) -> str:
    await _delete_existing_tokens(session, user_id, purpose, user_email_id)
    token_value = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    token = UserToken(
        user_id=user_id,
        token=_hash_token(token_value),
        purpose=purpose,
        user_email_id=user_email_id,
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
    await session.refresh(record)
    return record


async def purge_expired_tokens(session: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    stmt = delete(UserToken).where(UserToken.expires_at < now)
    await session.exec(stmt)
    await session.commit()


# ``user_tokens`` is a shared/public table the system engine holds DELETE on
# (see app/db/system_grants.py), so the sweep runs on AdminSessionLocal with
# no guild routing.
TOKEN_PURGE_POLL_SECONDS = 3600


async def process_expired_token_purge() -> None:
    """Hourly background sweep: delete expired ``user_tokens`` rows.

    Covers all purposes — consumed/expired password-reset and email-verify
    tokens as well as device tokens past their sliding-window cap. Without
    it, expired rows accumulate forever.
    """
    from app.db.session import AdminSessionLocal

    async with AdminSessionLocal() as session:
        await purge_expired_tokens(session)


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
        await session.refresh(record)
        await _record_device_token_use(user_id=record.user_id)
    return record


async def _record_device_token_use(*, user_id: int) -> None:
    """Note that a device token was presented, at the throttle above.

    Once per device per day rather than once per request, which is what makes
    it readable as adoption. On its own system-engine session: the request path
    holds nothing on ``audit_events`` in either direction.

    A record that cannot be written is logged and passed over. Presenting a
    credential that is still good is not the moment to refuse service.
    """
    from app.core.audit_events import AuditEventType
    from app.db import session as db_session
    from app.services import audit as audit_service

    try:
        async with db_session.AdminSessionLocal() as admin_session:
            await audit_service.record(
                admin_session,
                event_type=AuditEventType.AUTH_DEVICE_TOKEN_USED,
                actor_user_id=user_id,
            )
            await admin_session.commit()
    except Exception:
        logger.exception("Could not record device-token use for user %s", user_id)


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
    admin_session: AsyncSession,
    commit: bool = True,
) -> None:
    """Invalidate every outstanding session for ``user`` after a credential
    change.

    Bumps ``token_version`` (which the JWT/WS authenticators compare against,
    invalidating any still-unexpired access token), bulk-revokes the user's
    active ``device_auth`` tokens, deactivates their API keys (a leaked PAT must
    not survive a compromise response), and revokes their rotating **refresh
    sessions** — without which a captured refresh token would keep minting valid
    access tokens *at the new ``token_version``* right past the reset. Shared by
    the self-service password change, the forgot-password reset, and the admin
    password reset so the three paths can't drift.

    Two sessions by design: the caller's ``session`` carries the request-path
    writes (``token_version``, device tokens) and the caller commits it;
    ``admin_session`` is the system engine, the only role that may touch the
    ``app_admin``-only tables — ``auth_sessions`` and ``user_api_keys``. The
    API-key deactivation and refresh-session revocation are committed here by
    default so they can't be forgotten by a caller — revoking ahead of a
    password write that later fails just logs the user out, which is the
    fail-safe direction.

    ``commit=False`` leaves them staged, for the one caller that opens a
    replacement session immediately afterwards: staged together, the
    revocations and their replacement land in one transaction, so a failure to
    open the replacement leaves the account holding everything it had.
    """
    user.token_version += 1
    await revoke_active_device_tokens(session, user_id=user.id)
    await api_keys_service.deactivate_user_api_keys(admin_session, user_id=user.id)
    await session_service.revoke_all_for_user(admin_session, user_id=user.id)
    if commit:
        await admin_session.commit()
