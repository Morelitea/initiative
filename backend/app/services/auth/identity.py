"""Resolve a verified external identity to an Initiative user.

The step after :meth:`OidcProvider.complete`: given a provider row and the
verified ``(subject, email, email_verified)``, find — or, where allowed,
create — the user. Identity is keyed on **(provider, subject)** via
``federated_identities``; email is never a join key, only a hint that an
unlinked local account exists.

This module is mechanism, not policy: every path returns an
:class:`IdentityResolution` outcome and the caller (the login endpoint)
decides what each outcome means for the request. In particular
``EMAIL_MATCH`` — a verified email matching an existing, unlinked account —
performs **no write**; whether that becomes an automatic link or an explicit
confirmation flow is the caller's decision, made where the UX lives.
``link_identity`` is the one mechanism for creating the link.

Runs on the system engine (``federated_identities`` writes and cross-user
reads are app_admin surfaces); callers pass their admin session. Never raises
for a policy refusal — refusals are outcomes (the pattern from the session
service: no raise-with-uncommitted-writes).
"""

from __future__ import annotations

import hashlib

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy.exc import IntegrityError
from sqlalchemy import false, or_
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.encryption import encrypt_token
from app.core.login_methods import LoginMethod
from app.services.auth import addresses
from app.core.security import USABLE_HASH_PREFIXES
from app.models.platform.auth_provider import AuthProvider
from app.models.platform.federated_identity import FederatedIdentity
from app.models.platform.federated_identity_secret import FederatedIdentitySecret
from app.models.platform.user import User, UserRole, UserStatus
from app.models.platform.user_passkey import UserPasskey
from app.services.auth.platform_provider import can_serve_login_clause
from app.services.platform import dm_settings as dm_settings_service
from app.services.platform import usernames as username_service

logger = logging.getLogger(__name__)


class ResolutionOutcome(str, Enum):
    """What identity resolution concluded; the caller maps these to behavior."""

    LINKED = "linked"  # (provider, subject) matched an existing link
    PROVISIONED = "provisioned"  # no user existed; JIT-created and linked
    EMAIL_MATCH = "email_match"  # verified email matches an UNLINKED account
    EMAIL_UNVERIFIED = "email_unverified"  # matching account, email not asserted
    JIT_DISABLED = "jit_disabled"  # unknown user; provider forbids JIT
    REGISTRATION_DISABLED = "registration_disabled"  # unknown user; instance closed


@dataclass(frozen=True)
class IdentityResolution:
    outcome: ResolutionOutcome
    user: User | None = None
    identity: FederatedIdentity | None = None


async def resolve_oidc_identity(
    session: AsyncSession,
    *,
    provider: AuthProvider,
    subject: str,
    email: str | None,
    email_verified: bool,
    full_name: str | None = None,
    avatar_url: str | None = None,
) -> IdentityResolution:
    """Resolve ``(provider, subject)`` to a user.

    ``email`` is the IdP-asserted address (``None`` when the IdP returns no
    email claim — a synthetic ``{subject}@oidc.local`` address is used for
    provisioning, mirroring the existing flow). Account-status checks (active,
    deactivated) stay with the caller, as they do today.

    JIT provisioning: operator-global providers require the instance's
    registration to be open (an unaffiliated self-registration channel);
    guild-scoped providers JIT under ``allow_jit`` **and** the guild having
    sign-in enabled (the operator entitlement toggle) — the guild admin
    configured the IdP, authentication there is the invitation, and the caller
    lands the new user in that guild (capacity-enforced) rather than leaving an
    unaffiliated account. Turning the guild toggle off stops NEW accounts here
    while existing linked identities keep resolving to ``LINKED`` above.
    """
    identity = await _find_identity(session, provider_id=provider.id, subject=subject)
    if identity is not None:
        user = (
            await session.exec(select(User).where(User.id == identity.user_id))
        ).one_or_none()
        if user is None:
            # FK is ON DELETE CASCADE, so this is unreachable outside a torn
            # backup; treat as unknown identity rather than 500ing a login.
            logger.error(
                "federated identity %s points at missing user %s",
                identity.id,
                identity.user_id,
            )
            return IdentityResolution(outcome=ResolutionOutcome.JIT_DISABLED)
        identity.last_login_at = datetime.now(timezone.utc)
        identity.email_verified = email_verified
        session.add(identity)
        await session.commit()
        await session.refresh(identity)
        return IdentityResolution(
            outcome=ResolutionOutcome.LINKED, user=user, identity=identity
        )

    # No link. A real asserted email may match an existing local account —
    # surface it, but never write: linking an email-matched account is the
    # caller's policy decision, and only a verified address may match an
    # existing account (an unverified match is refused outright).
    if email:
        normalized = email.lower().strip()
        existing = await addresses.account_holding(session, normalized)
        if existing is not None:
            if not email_verified:
                logger.warning(
                    "OIDC login: unverified email matches existing account "
                    "(user_id=%s, provider=%s)",
                    existing.id,
                    provider.slug,
                )
                return IdentityResolution(
                    outcome=ResolutionOutcome.EMAIL_UNVERIFIED, user=existing
                )
            return IdentityResolution(
                outcome=ResolutionOutcome.EMAIL_MATCH, user=existing
            )

    # Unknown user: JIT-provision if the provider allows it. A sign-in on the
    # deployment additionally requires open registration. There is one
    # sign-in, so there is one answer: a community does not decide whether
    # somebody may hold an account here, only whether an arrival is one of its
    # own. Existing linked identities (LINKED, above) are untouched either way.
    if not provider.allow_jit:
        return IdentityResolution(outcome=ResolutionOutcome.JIT_DISABLED)
    if not await _registration_open(session):
        return IdentityResolution(outcome=ResolutionOutcome.REGISTRATION_DISABLED)
    return await _provision(
        session,
        provider=provider,
        subject=subject,
        email=email,
        email_verified=email_verified,
        full_name=full_name,
        avatar_url=avatar_url,
    )


async def link_identity(
    session: AsyncSession,
    *,
    user: User,
    provider: AuthProvider,
    subject: str,
    email_verified: bool,
) -> FederatedIdentity:
    """Create the ``(provider, subject)`` link for an **existing** ``user`` —
    the mechanism behind any caller-approved linking flow (e.g. an
    ``EMAIL_MATCH`` the endpoint decides to link). JIT provisioning creates the
    user and link atomically in ``_provision`` instead, so a failure can't
    orphan a fresh user."""
    identity = FederatedIdentity(
        user_id=user.id,
        provider_id=provider.id,
        subject=subject,
        email_verified=email_verified,
        last_login_at=datetime.now(timezone.utc),
    )
    session.add(identity)
    await session.commit()
    await session.refresh(identity)
    return identity


async def set_identity_refresh_token(
    session: AsyncSession, *, identity_id: int, refresh_token: str | None
) -> None:
    """Store (or clear, with ``None``) the IdP refresh token for one identity
    link in its companion secret row. Stages only — the caller commits."""
    encrypted = encrypt_token(refresh_token) if refresh_token else None
    secret = await session.get(FederatedIdentitySecret, identity_id)
    if secret is None:
        if encrypted is None:
            return
        secret = FederatedIdentitySecret(
            identity_id=identity_id, refresh_token_encrypted=encrypted
        )
    else:
        secret.refresh_token_encrypted = encrypted
    session.add(secret)


async def has_federated_identity(session: AsyncSession, *, user_id: int) -> bool:
    """Whether the user has any linked external identity — the "SSO account"
    signal the password-confirmation gates and the profile UI read."""
    row = (
        await session.exec(
            select(FederatedIdentity.id)
            .where(FederatedIdentity.user_id == user_id)
            .limit(1)
        )
    ).first()
    return row is not None


async def sole_credential_user_count(
    session: AsyncSession, *, provider_id: int, permitted: frozenset[LoginMethod]
) -> int:
    """How many accounts hold this provider as their only credential.

    An account counts when every identity link it holds belongs to this
    provider — the provider's links cascade with it, so this account's last
    credential goes too — and nothing else ``permitted`` names opens a session
    for them.

    ``permitted`` is what the deployment offers today: a credential is a way in
    only while its method is in that set, so a password counts where passwords
    are offered and a registered passkey where passkeys are.

    "No usable password" is read from the stored hash rather than from NULL
    alone: an account can carry a value no scheme verifies (the ``'!'`` marker
    the 0152 downgrade writes), and that is not a password. What it cannot read
    is an account provisioned before 0152, whose throwaway hash is a real argon2
    value indistinguishable from a chosen one; that account is not counted here
    and reaches its account through password reset instead.

    An alternate link only counts when its provider could actually answer a
    login — a disabled or half-configured row is not a way in, and neither is
    the platform row without its client secret.
    """
    if LoginMethod.sso not in permitted:
        # An identity link opens no session where single sign-on is not
        # offered, so no account's way in rides on this provider.
        return 0
    holds_this = select(FederatedIdentity.id).where(
        FederatedIdentity.user_id == User.id,
        FederatedIdentity.provider_id == provider_id,
    )
    holds_another = (
        select(FederatedIdentity.id)
        .join(AuthProvider, AuthProvider.id == FederatedIdentity.provider_id)
        .where(
            FederatedIdentity.user_id == User.id,
            FederatedIdentity.provider_id != provider_id,
            can_serve_login_clause(),
        )
    )
    conditions = [holds_this.exists(), ~holds_another.exists()]
    if LoginMethod.password in permitted:
        conditions.append(_no_usable_password_clause())
    if LoginMethod.passkey in permitted:
        conditions.append(~_holds_a_passkey_clause())
    return (
        await session.exec(select(func.count()).select_from(User).where(*conditions))
    ).one()


def _no_usable_password_clause():
    """Accounts whose stored hash is not one any scheme verifies.

    Reads the hash rather than NULL alone: an account can carry a value no
    scheme verifies (the ``'!'`` marker a 0152 downgrade writes), and that is
    not a password. What it cannot read is an account provisioned before 0152,
    whose throwaway hash is a real argon2 value indistinguishable from a chosen
    one — that account reads as having a password, which is the conservative
    direction for the account, and it reaches itself through password reset.
    """
    return or_(
        User.hashed_password.is_(None),
        ~or_(
            *(
                User.hashed_password.startswith(prefix)
                for prefix in USABLE_HASH_PREFIXES
            )
        ),
    )


def _holds_a_passkey_clause():
    """Accounts holding at least one registered WebAuthn credential.

    A passkey opens a session by itself, so an account holding one has a way in
    that neither a password nor an identity provider accounts for.
    """
    return select(UserPasskey.id).where(UserPasskey.user_id == User.id).exists()


def _holds_login_ready_identity_clause():
    """Accounts holding an identity link some provider could answer a login for.

    A disabled or half-configured row is not a way in, and neither is the
    platform row without its client secret.
    """
    return (
        select(FederatedIdentity.id)
        .join(AuthProvider, AuthProvider.id == FederatedIdentity.provider_id)
        .where(
            FederatedIdentity.user_id == User.id,
            can_serve_login_clause(),
        )
        .exists()
    )


def _can_sign_in_clause(permitted: frozenset[LoginMethod]):
    """Accounts that can begin a session while ``permitted`` is what is offered.

    A credential is a way in only while its method is in the set: a password
    where passwords are offered, an identity link where single sign-on is, a
    registered passkey where passkeys are. A second factor accompanies a
    sign-in rather than beginning one, so it is none of these.
    """
    ways_in = []
    if LoginMethod.password in permitted:
        ways_in.append(~_no_usable_password_clause())
    if LoginMethod.sso in permitted:
        ways_in.append(_holds_login_ready_identity_clause())
    if LoginMethod.passkey in permitted:
        ways_in.append(_holds_a_passkey_clause())
    if not ways_in:
        return false()
    return or_(*ways_in)


async def stranded_between(
    session: AsyncSession,
    *,
    current: frozenset[LoginMethod],
    requested: frozenset[LoginMethod],
) -> int:
    """How many accounts can begin a session under ``current`` and not under
    ``requested``.

    One query over both sets rather than one per method, so an account holding
    two credentials whose methods go together is counted for the pair — which
    asking about each method on its own cannot do, since each of the two is a
    way in while the other is still offered.
    """
    return (
        await session.exec(
            select(func.count())
            .select_from(User)
            .where(
                _can_sign_in_clause(current),
                ~_can_sign_in_clause(requested),
            )
        )
    ).one()


async def password_only_user_count(
    session: AsyncSession, *, permitted: frozenset[LoginMethod]
) -> int:
    """How many accounts can begin a session only with a password.

    What withdrawing the password would leave stranded on a deployment
    offering ``permitted`` today. Nobody, where the password is not among them.
    """
    return await stranded_between(
        session, current=permitted, requested=permitted - {LoginMethod.password}
    )


async def federated_only_user_count(
    session: AsyncSession, *, permitted: frozenset[LoginMethod]
) -> int:
    """How many accounts can begin a session only through an identity provider.

    Every provider counts. Withdrawing the method closes all of them at once,
    so an account whose only way in is any one of them is one this has to
    report.
    """
    return await stranded_between(
        session, current=permitted, requested=permitted - {LoginMethod.sso}
    )


async def passkey_only_user_count(
    session: AsyncSession, *, permitted: frozenset[LoginMethod]
) -> int:
    """How many accounts can begin a session only with a passkey.

    Nobody, on a deployment that does not offer them — the method is not a way
    in there, so withdrawing it takes nothing away.
    """
    return await stranded_between(
        session, current=permitted, requested=permitted - {LoginMethod.passkey}
    )


async def delete_user_identities(session: AsyncSession, *, user_id: int) -> None:
    """Remove every identity link (and, via cascade, its stored refresh token)
    for a user — the anonymize/delete-account cleanup. Stages only."""
    identities = (
        await session.exec(
            select(FederatedIdentity).where(FederatedIdentity.user_id == user_id)
        )
    ).all()
    for identity in identities:
        secret = await session.get(FederatedIdentitySecret, identity.id)
        if secret is not None:
            await session.delete(secret)
        await session.delete(identity)


async def _find_identity(
    session: AsyncSession, *, provider_id: int, subject: str
) -> FederatedIdentity | None:
    return (
        await session.exec(
            select(FederatedIdentity).where(
                FederatedIdentity.provider_id == provider_id,
                FederatedIdentity.subject == subject,
            )
        )
    ).one_or_none()


async def _registration_open(session: AsyncSession) -> bool:
    """Mirrors the existing OIDC flow's gate: a closed instance still admits
    the very first user (fresh-install bootstrap)."""
    if settings.ENABLE_PUBLIC_REGISTRATION and not settings.DISABLE_GUILD_CREATION:
        return True
    user_count = (await session.exec(select(func.count(User.id)))).one()
    return user_count == 0


def _address_lock_key(normalized: str) -> int:
    """A stable 64-bit key naming one address, for ``pg_advisory_xact_lock``.

    Not the stored hash: a lock key is an integer visible in ``pg_locks``, and
    this one only has to be the same number for the same address on every
    connection.
    """
    digest = hashlib.blake2b(normalized.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)


class _AddressTaken(Exception):
    """Another account already holds the asserted address, proven.

    Raised inside the provisioning savepoint so the recovery below handles a
    lost race the same way whether a constraint or a re-read found it.
    """


async def _provision(
    session: AsyncSession,
    *,
    provider: AuthProvider,
    subject: str,
    email: str | None,
    email_verified: bool,
    full_name: str | None,
    avatar_url: str | None,
) -> IdentityResolution:
    # No email claim: a synthetic address keyed off the IdP-controlled subject,
    # as in the existing flow. It is not a mailbox, so it is never marked
    # verified.
    if email:
        normalized = email.lower().strip()
        verified = email_verified
    else:
        normalized = f"{subject}@oidc.local"
        verified = False

    if email:
        # One provisioning at a time per address, for as long as this
        # transaction runs. Uniqueness covers proven rows, so two sign-ins
        # asserting the same *unproven* address conflict over nothing and
        # neither sees the other's uncommitted row; whichever waits here reads
        # the other's account in the check below and is answered the way a
        # sign-in that did not race is.
        await session.exec(
            select(func.pg_advisory_xact_lock(_address_lock_key(normalized)))
        )

    # A random handle, not one built from the claims. The claims feed the
    # suggestions on the pick screen instead, so an account abandoned partway
    # through is left holding nothing that identifies its owner — and a
    # corporate IdP's ``preferred_username`` is offered rather than imposed.
    handle, discriminator = await username_service.allocate_from_seed(session)

    user = User(
        username=handle,
        discriminator=discriminator,
        # Assigned, not picked: its owner chooses one on their next sign-in.
        username_chosen=False,
        # An address is not a display name. With no name claim there is simply
        # no name, and the handle carries the display.
        full_name=full_name,
        # SSO-only account: no password. Verification treats a NULL hash as
        # never-a-match, so this account signs in only through its provider.
        hashed_password=None,
        role=UserRole.member,
        status=UserStatus.active,
        avatar_url=avatar_url,
    )
    try:
        # User + identity are inserted inside ONE savepoint: flush assigns the
        # user id, then both are staged together. A conflict rolls the savepoint
        # back (discarding our user — no orphan) while leaving the outer
        # transaction usable for the recovery reads below. (A plain flush +
        # session.rollback() would instead poison the connection and expire every
        # object, so the recovery SELECT couldn't run — hence the savepoint, the
        # same pattern the billing idempotency insert uses.)
        async with session.begin_nested():
            session.add(user)
            await session.flush()
            if user.id is None:  # populated by flush; guard also narrows the type
                raise RuntimeError("user id not assigned after flush")
            addresses.record_address(
                session,
                user_id=user.id,
                email=normalized,
                source=(addresses.SOURCE_OIDC if email else addresses.SOURCE_SYNTHETIC),
                verified=verified,
            )
            identity = FederatedIdentity(
                user_id=user.id,
                provider_id=provider.id,
                subject=subject,
                email_verified=verified,
                last_login_at=datetime.now(timezone.utc),
            )
            session.add(identity)
            await session.flush()
            # Asked again now the row is in: a login that committed between the
            # caller's check and this insert is visible here, and an unproven
            # claim collides with nothing, so there is no constraint to raise
            # for it. A proven holder means this account is not the one the
            # address belongs to, and the block below decides what to do about
            # that — the same decision a login that did not race makes.
            if email:
                holder = await addresses.account_holding(session, email)
                if holder is not None and holder.id != user.id:
                    raise _AddressTaken
        # Outside the savepoint, and before the commit: a lost race raises out
        # of the block above and never reaches this, so there is no row for an
        # account that was discarded.
        await dm_settings_service.seed_for_new_account(session, user_id=user.id)
        await session.commit()
        await session.refresh(user)
        await session.refresh(identity)
        return IdentityResolution(
            outcome=ResolutionOutcome.PROVISIONED, user=user, identity=identity
        )
    except (IntegrityError, _AddressTaken):
        # Lost a JIT race with a concurrent login. A conflicting unique insert
        # blocks until the other transaction commits, so by the time we're here
        # the winner is committed and visible; the savepoint has already discarded
        # our user (no orphan) and the outer transaction is intact. Resolve to
        # whatever the winner left — the two unique constraints give two races:
        # (a) (provider, subject) — a double-submit of the *same* login. The
        #     winner's link is ours to use.
        winner = await _find_identity(session, provider_id=provider.id, subject=subject)
        if winner is not None:
            user = (
                await session.exec(select(User).where(User.id == winner.user_id))
            ).one_or_none()
            if user is not None:
                return IdentityResolution(
                    outcome=ResolutionOutcome.LINKED, user=user, identity=winner
                )
        # (b) the address — a *different* subject with the same email (a
        #     second provider, or the IdP issuing a new subject) got there first.
        #     That is now an existing, unlinked account matched by email: the same
        #     EMAIL_MATCH / EMAIL_UNVERIFIED decision a non-raced login makes,
        #     never a silent link. Only a real asserted email can collide here —
        #     the synthetic {subject}@oidc.local address is subject-unique, so its
        #     only race is (a).
        if email:
            matched = await addresses.account_holding(session, email)
            if matched is not None:
                outcome = (
                    ResolutionOutcome.EMAIL_MATCH
                    if email_verified
                    else ResolutionOutcome.EMAIL_UNVERIFIED
                )
                return IdentityResolution(outcome=outcome, user=matched)
        raise
