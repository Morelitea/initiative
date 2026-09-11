"""Resolving an address to an account, and keeping the set of them.

An account has many addresses and signs in with any of them. ``user_emails``
is where they live, in the same two representations ``users`` has always used:
a keyed HMAC for the equality lookup and a Fernet ciphertext for reading the
address back.

``users.email_hash`` / ``email_encrypted`` still hold the one address an
account was created with, and a lookup falls back to them so an account whose
row did not come across still signs in. Every fallback is logged with the
account it resolved; the columns on ``users`` come off once that log has
stayed quiet under real traffic.

Runs on the system engine. ``user_emails`` carries no request-path grants for
the same reason ``auth_sessions`` carries none: resolving an address happens
before there is anybody to scope a policy to.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import delete, update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.encryption import SALT_EMAIL, encrypt_field, hash_email
from app.models.platform.user import User
from app.models.platform.user_email import UserEmail

logger = logging.getLogger(__name__)

# Where an address came from, for whoever reads the row.
SOURCE_SIGNUP = "signup"
SOURCE_ADDED = "added"
SOURCE_OIDC = "oidc"
SOURCE_SYNTHETIC = "synthetic"


def normalize(email: str) -> str:
    """The form an address is hashed and stored in."""
    return email.lower().strip()


async def find_user_by_address(session: AsyncSession, email: str) -> User | None:
    """The account that signs in with ``email``, or ``None``.

    Reads ``user_emails`` first and falls back to the address ``users`` carries.
    """
    digest = hash_email(normalize(email))
    found = (
        await session.exec(
            select(User)
            .join(UserEmail, UserEmail.user_id == User.id)
            .where(UserEmail.email_hash == digest)
        )
    ).one_or_none()
    if found is not None:
        return found

    carried = (
        await session.exec(select(User).where(User.email_hash == digest))
    ).one_or_none()
    if carried is not None:
        logger.warning(
            "address lookup fell back to users.email_hash (account %s): "
            "user_emails holds no row for the address presented",
            carried.id,
        )
    return carried


async def note_sign_in(
    session: AsyncSession, *, email: str, now: datetime | None = None
) -> None:
    """Stamp the address a sign-in resolved through.

    Staged in the caller's transaction, beside the session the sign-in opens.
    An address that resolved through the fallback has no row to stamp, and the
    statement matches nothing — which is the same thing the fallback log says.
    """
    await session.exec(
        update(UserEmail)
        .where(UserEmail.email_hash == hash_email(normalize(email)))
        .values(last_login_at=now or datetime.now(timezone.utc))
    )


def record_address(
    session: AsyncSession,
    *,
    user_id: int,
    email: str,
    source: str,
    verified: bool,
    is_primary: bool = True,
    now: datetime | None = None,
) -> UserEmail:
    """Stage an address for ``user_id`` in ``session``'s own transaction.

    Staged rather than committed so the address lands with whatever created the
    account — an account that exists without its address would sign in only
    through the fallback.
    """
    moment = now or datetime.now(timezone.utc)
    normalized = normalize(email)
    row = UserEmail(
        user_id=user_id,
        email_hash=hash_email(normalized),
        email_encrypted=encrypt_field(normalized, SALT_EMAIL),
        verified_at=moment if verified else None,
        is_primary=is_primary,
        source=source,
        created_at=moment,
    )
    session.add(row)
    return row


async def replace_all(
    session: AsyncSession, *, user_id: int, email: str, source: str
) -> UserEmail:
    """Drop every address this account has and leave it holding ``email``.

    What erasure needs: the addresses are the personal data, and a husk keeps
    one unusable stand-in so the account still has a primary.
    """
    await session.exec(delete(UserEmail).where(UserEmail.user_id == user_id))
    return record_address(
        session,
        user_id=user_id,
        email=email,
        source=source,
        verified=False,
    )
