"""A sign-in held between the thing it has proved and the thing it has not.

A password can be correct and the sign-in still unfinished, because the account
holds a second factor. Something has to carry that across two requests.

It is carried as a row: ``consumed_at`` spends it, ``attempts`` counts refused
answers against it, ``expires_at`` ends it, and :func:`revoke_for_user` drops
it when what it rests on moves. It has its own table because every row in
``auth_sessions`` means somebody is signed in, and this is the state of
somebody who is not.

The value handed to the client is random and stored only as a SHA-256 digest,
following ``auth_sessions.refresh_token_hash``: full entropy already, so the
digest is a single indexed lookup rather than a scan.

Everything here runs on the system engine — a challenge is resolved before
there is an authenticated request to scope.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.platform.auth_challenge import AuthChallenge

#: Bytes of randomness behind the value handed to the client.
_CHALLENGE_BYTES = 32

#: How long a challenge stands. Long enough to open an authenticator app and
#: read a code from it, and no longer.
CHALLENGE_TTL = timedelta(minutes=5)

#: Wrong codes one challenge will take before it is finished. A sixth attempt
#: does not extend it: the challenge goes and the password is presented again.
MAX_ATTEMPTS = 5


class ChallengePurpose(str, Enum):
    """What a challenge is waiting for. Carried on the row so one table serves
    more than one unfinished thing."""

    #: A password was accepted and the account's second factor is outstanding.
    sign_in = "sign_in"


@dataclass(frozen=True)
class IssuedChallenge:
    """A stored challenge and the value that names it.

    ``value`` is the only time the raw value exists — hand it to the client and
    drop it; only its digest is kept.
    """

    challenge: AuthChallenge
    value: str


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


async def create(
    session: AsyncSession, *, user_id: int, purpose: ChallengePurpose
) -> IssuedChallenge:
    """Open a challenge for one account. The caller commits."""
    value = secrets.token_urlsafe(_CHALLENGE_BYTES)
    challenge = AuthChallenge(
        challenge_hash=_hash(value),
        user_id=user_id,
        purpose=purpose.value,
        expires_at=_now() + CHALLENGE_TTL,
    )
    session.add(challenge)
    await session.flush()
    return IssuedChallenge(challenge=challenge, value=value)


async def claim_attempt(
    session: AsyncSession, *, value: str, purpose: ChallengePurpose
) -> AuthChallenge | None:
    """Take one of the challenge's attempts, and hand back the challenge.

    ``None`` when there is nothing to take one from: no such challenge, not for
    this purpose, already spent, expired, or out of attempts. Every one of those
    reads the same from here.

    Taking the attempt *is* the lookup, and it is one statement, so two answers
    arriving together take two attempts rather than reading the same count and
    each writing it back. The count is why this is a write and not a read.
    """
    digest = _hash(value)
    result = await session.exec(
        update(AuthChallenge)
        .where(
            AuthChallenge.challenge_hash == digest,
            AuthChallenge.purpose == purpose.value,
            AuthChallenge.consumed_at.is_(None),
            AuthChallenge.expires_at > _now(),
            AuthChallenge.attempts < MAX_ATTEMPTS,
        )
        .values(attempts=AuthChallenge.attempts + 1)
    )
    if not result.rowcount:
        return None
    return (
        await session.exec(
            select(AuthChallenge).where(AuthChallenge.challenge_hash == digest)
        )
    ).first()


async def consume(session: AsyncSession, challenge: AuthChallenge) -> bool:
    """Spend the challenge, once.

    Returns whether this call is the one that spent it: the update carries its
    own ``consumed_at IS NULL``, so of two requests answering the same challenge
    at the same moment, one goes on to make a session.
    """
    result = await session.exec(
        update(AuthChallenge)
        .where(
            AuthChallenge.id == challenge.id,
            AuthChallenge.consumed_at.is_(None),
        )
        .values(consumed_at=_now())
    )
    return bool(result.rowcount)


async def revoke_for_user(session: AsyncSession, *, user_id: int) -> int:
    """Drop every challenge standing for one account, spent or not.

    Called where what a challenge rests on has moved — a changed password, a
    factor removed. Returns how many went. The caller commits.
    """
    result = await session.exec(
        delete(AuthChallenge).where(AuthChallenge.user_id == user_id)
    )
    return int(result.rowcount or 0)


async def purge_expired(session: AsyncSession) -> int:
    """Clear out challenges nothing can use again. The caller commits."""
    result = await session.exec(
        delete(AuthChallenge).where(AuthChallenge.expires_at <= _now())
    )
    return int(result.rowcount or 0)
