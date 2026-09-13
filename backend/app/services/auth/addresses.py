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
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.encryption import SALT_EMAIL, encrypt_field, hash_email
from app.core.messages import AddressMessages
from app.models.platform.user import User
from app.models.platform.user_email import UserEmail
from app.models.platform.user_email_assertion import UserEmailAssertion

logger = logging.getLogger(__name__)

# Where an address came from, for whoever reads the row.
SOURCE_SIGNUP = "signup"
SOURCE_ADDED = "added"
SOURCE_OIDC = "oidc"
SOURCE_SYNTHETIC = "synthetic"

#: How many addresses one account keeps. A person collects a handful; a
#: listing that grows without end is nobody's account page.
MAX_ADDRESSES_PER_ACCOUNT = 10


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
            .where(
                UserEmail.email_hash == digest,
                # Proven only (§6.2 rule 2). An unproven row is a claim
                # somebody is in the middle of making, and it signs in nobody.
                UserEmail.verified_at.is_not(None),
            )
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
    row = _build_address(
        user_id=user_id,
        email=email,
        source=source,
        verified=verified,
        is_primary=is_primary,
        now=now,
    )
    session.add(row)
    return row


def _build_address(
    *,
    user_id: int,
    email: str,
    source: str,
    verified: bool,
    is_primary: bool,
    now: datetime | None = None,
) -> UserEmail:
    """The row, unattached — so a caller can stage it inside a savepoint."""
    moment = now or datetime.now(timezone.utc)
    normalized = normalize(email)
    return UserEmail(
        user_id=user_id,
        email_hash=hash_email(normalized),
        email_encrypted=encrypt_field(normalized, SALT_EMAIL),
        verified_at=moment if verified else None,
        is_primary=is_primary,
        source=source,
        created_at=moment,
    )


async def note_assertion(
    session: AsyncSession,
    *,
    user_email_id: int,
    provider_id: int,
    now: datetime | None = None,
) -> None:
    """Record that ``provider_id`` asserts this address, or refresh when it
    last did. Providers do not displace one another — two directories can name
    the same address and each keeps its own standing claim."""
    moment = now or datetime.now(timezone.utc)
    await session.exec(
        pg_insert(UserEmailAssertion)
        .values(
            user_email_id=user_email_id,
            provider_id=provider_id,
            first_asserted_at=moment,
            last_asserted_at=moment,
        )
        .on_conflict_do_update(
            index_elements=["user_email_id", "provider_id"],
            set_={"last_asserted_at": moment},
        )
    )


async def ensure_address(
    session: AsyncSession,
    *,
    user_id: int,
    email: str,
    source: str,
    verified: bool,
    provider_id: int | None = None,
    now: datetime | None = None,
) -> UserEmail | None:
    """Make sure ``user_id`` holds ``email``, adding it if it does not, and
    record ``provider_id``'s claim on it.

    What a provider login needs. An account that is *provisioned* by a provider
    gets its address with it; one that is *linked* already existed, and the
    address the provider asserts for it is new information — a work address
    beside a personal one.

    Idempotent, because it runs on every sign-in: an address already on this
    account gains the verification it arrived with and this provider's claim,
    and keeps everything else. An address on a **different** account is left
    alone and ``None`` comes back — an address belongs to one account, and a
    provider naming somebody else's does not move it.

    Never primary. Which address receives account mail is its owner's to
    choose, not a directory's.
    """
    moment = now or datetime.now(timezone.utc)
    digest = hash_email(normalize(email))
    existing = await _by_hash(session, digest)

    if existing is None:
        row = _build_address(
            user_id=user_id,
            email=email,
            source=source,
            verified=verified,
            is_primary=False,
            now=moment,
        )
        try:
            # Staged and flushed entirely inside a savepoint: losing the race
            # to a concurrent sign-in for the same address rolls back to here
            # and leaves the outer transaction usable, holding no dead row.
            async with session.begin_nested():
                session.add(row)
                await session.flush()
        except IntegrityError:
            existing = await _by_hash(session, digest)
            if existing is None:  # pragma: no cover - the conflict implies a row
                raise
        else:
            if provider_id is not None and row.id is not None:
                await note_assertion(
                    session,
                    user_email_id=row.id,
                    provider_id=provider_id,
                    now=moment,
                )
            return row

    if existing.user_id != user_id:
        logger.warning(
            "provider asserted an address held by account %s for account %s; "
            "left where it is",
            existing.user_id,
            user_id,
        )
        return None

    if verified and existing.verified_at is None:
        existing.verified_at = moment
        session.add(existing)
    if provider_id is not None and existing.id is not None:
        await note_assertion(
            session,
            user_email_id=existing.id,
            provider_id=provider_id,
            now=moment,
        )
    return existing


async def _by_hash(session: AsyncSession, digest: str) -> UserEmail | None:
    return (
        await session.exec(select(UserEmail).where(UserEmail.email_hash == digest))
    ).one_or_none()


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


class AddressError(Exception):
    """A refused address operation, carrying the code the endpoint reports."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


async def list_for_user(session: AsyncSession, *, user_id: int) -> list[UserEmail]:
    """The addresses an account has, oldest first.

    Synthetic placeholders are left out: ``{subject}@oidc.local`` is not a
    mailbox and there is nothing its owner can do with it.
    """
    rows = (
        await session.exec(
            select(UserEmail)
            .where(
                UserEmail.user_id == user_id,
                UserEmail.source != SOURCE_SYNTHETIC,
            )
            .order_by(UserEmail.created_at, UserEmail.id)
        )
    ).all()
    return list(rows)


async def add_for_user(
    session: AsyncSession, *, user_id: int, email: str, now: datetime | None = None
) -> UserEmail | None:
    """Start holding ``email`` for this account, unproven — or return the claim
    this account already has on it, so the letter can go out again.

    Returns ``None`` only when somebody has **proven** the address. An unproven
    claim belongs to nobody yet: the person who holds the mailbox can still
    claim it, and proving it is what settles the matter.

    The caller answers the same way whatever comes back. What it is for is
    deciding whether to write, and to which pending claim.
    """
    digest = hash_email(normalize(email))
    mine = await _pending_for_user(session, user_id=user_id, digest=digest)
    if mine is not None:
        return mine

    # How full this account is, before the address is looked at. It is a fact
    # about the account and not about who holds what, so settling it first
    # keeps the answer the same either way — the same reason the endpoint
    # settles whether the deployment can send before it gets here.
    #
    # The lock makes two additions arriving together take turns, so they count
    # each other. An account with no addresses yet has nothing to lock, and
    # nothing near the limit either.
    await _lock_addresses(session, user_id)
    if await _address_count(session, user_id) >= MAX_ADDRESSES_PER_ACCOUNT:
        raise AddressError(AddressMessages.TOO_MANY_ADDRESSES)

    if await _proven_holder(session, digest) is not None:
        return None

    row = _build_address(
        user_id=user_id,
        email=email,
        source=SOURCE_ADDED,
        verified=False,
        is_primary=False,
        now=now,
    )
    try:
        # Two additions of one address race to here; the proven-uniqueness
        # index settles nothing between two unproven rows, so this is only
        # about the account's own duplicate.
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        return await _pending_for_user(session, user_id=user_id, digest=digest)
    return row


async def verify_for_user(
    session: AsyncSession,
    *,
    user_id: int,
    address_id: int,
    now: datetime | None = None,
) -> UserEmail:
    """Mark one address proven. Idempotent — proving it twice is proving it."""
    row = await _owned(session, user_id=user_id, address_id=address_id)
    if row.verified_at is not None:
        return row

    holder = await _proven_holder(session, row.email_hash)
    if holder is not None and holder.user_id != user_id:
        raise AddressError(AddressMessages.ADDRESS_TAKEN)

    row.verified_at = now or datetime.now(timezone.utc)
    session.add(row)
    try:
        # Two claims on one address can be proven at the same moment; the
        # proven-uniqueness index settles which, inside a savepoint so the
        # loser leaves the outer transaction usable.
        async with session.begin_nested():
            await session.flush()
    except IntegrityError:
        raise AddressError(AddressMessages.ADDRESS_TAKEN) from None

    # Proving it settles every other claim on the same address.
    await session.exec(
        delete(UserEmail).where(
            UserEmail.email_hash == row.email_hash,
            UserEmail.id != row.id,
            UserEmail.verified_at.is_(None),
        )
    )
    return row


async def remove_for_user(
    session: AsyncSession, *, user_id: int, address_id: int
) -> UserEmail:
    """Stop holding one address.

    The primary stays until another address is made primary, and the last
    verified address stays full stop — an account has to keep a way back in
    and a place to be written to.
    """
    row = await _owned(session, user_id=user_id, address_id=address_id)
    if row.is_primary:
        raise AddressError(AddressMessages.PRIMARY_ADDRESS)
    if row.verified_at is not None and await _verified_count(session, user_id) <= 1:
        raise AddressError(AddressMessages.LAST_VERIFIED_ADDRESS)
    await session.delete(row)
    return row


async def set_primary_for_user(
    session: AsyncSession, *, user_id: int, address_id: int
) -> UserEmail:
    """Move the address account mail goes to.

    Only to one this account has proved it holds: the primary is where a
    password reset lands, so moving it is a change of that destination.
    """
    row = await _owned(session, user_id=user_id, address_id=address_id)
    if row.verified_at is None:
        raise AddressError(AddressMessages.ADDRESS_NOT_VERIFIED)
    if row.is_primary:
        return row
    # One primary per account is a partial unique index, so two promotions
    # arriving together would both stand the old one down and then raise two.
    # The lock makes them take turns; the second reads the first's result.
    await _lock_addresses(session, user_id)
    for other in await list_for_user(session, user_id=user_id):
        if other.is_primary and other.id != row.id:
            other.is_primary = False
            session.add(other)
    await session.flush()
    row.is_primary = True
    session.add(row)
    return row


async def _owned(session: AsyncSession, *, user_id: int, address_id: int) -> UserEmail:
    row = await session.get(UserEmail, address_id)
    if row is None or row.user_id != user_id or row.source == SOURCE_SYNTHETIC:
        raise AddressError(AddressMessages.ADDRESS_NOT_FOUND)
    return row


async def _lock_addresses(session: AsyncSession, user_id: int) -> None:
    """Hold this account's address rows for the rest of the transaction, so
    two requests changing the set take turns rather than both acting on the
    same reading."""
    await session.exec(
        select(UserEmail.id)
        .where(UserEmail.user_id == user_id)
        .order_by(UserEmail.id)
        .with_for_update()
    )


async def _pending_for_user(
    session: AsyncSession, *, user_id: int, digest: str
) -> UserEmail | None:
    """This account's own unproven claim on an address, if it has one."""
    return (
        await session.exec(
            select(UserEmail).where(
                UserEmail.user_id == user_id,
                UserEmail.email_hash == digest,
                UserEmail.verified_at.is_(None),
            )
        )
    ).one_or_none()


async def _proven_holder(session: AsyncSession, digest: str) -> UserEmail | None:
    """The row that has proven this address, if anybody has."""
    return (
        await session.exec(
            select(UserEmail).where(
                UserEmail.email_hash == digest,
                UserEmail.verified_at.is_not(None),
            )
        )
    ).one_or_none()


async def _address_count(session: AsyncSession, user_id: int) -> int:
    return (
        await session.exec(
            select(func.count())
            .select_from(UserEmail)
            .where(
                UserEmail.user_id == user_id,
                UserEmail.source != SOURCE_SYNTHETIC,
            )
        )
    ).one()


async def _verified_count(session: AsyncSession, user_id: int) -> int:
    return (
        await session.exec(
            select(func.count())
            .select_from(UserEmail)
            .where(
                UserEmail.user_id == user_id,
                UserEmail.verified_at.is_not(None),
            )
        )
    ).one()
