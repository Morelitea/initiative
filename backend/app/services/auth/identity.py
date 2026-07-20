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

import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy.exc import IntegrityError
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.encryption import SALT_EMAIL, encrypt_field, encrypt_token, hash_email
from app.core.security import get_password_hash
from app.models.platform.auth_provider import AuthProvider
from app.models.platform.federated_identity import FederatedIdentity
from app.models.platform.federated_identity_secret import FederatedIdentitySecret
from app.models.platform.user import User, UserRole, UserStatus

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
    jit: bool = True,
) -> IdentityResolution:
    """Resolve ``(provider, subject)`` to a user.

    ``email`` is the IdP-asserted address (``None`` when the IdP returns no
    email claim — a synthetic ``{subject}@oidc.local`` address is used for
    provisioning, mirroring the existing flow). Account-status checks (active,
    deactivated) stay with the caller, as they do today. ``jit=False`` limits
    resolution to existing users regardless of the provider's ``allow_jit``
    (a caller whose flow can't finish onboarding a brand-new user yet).
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
        existing = (
            await session.exec(
                select(User).where(User.email_hash == hash_email(normalized))
            )
        ).one_or_none()
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

    # Unknown user: JIT-provision if the caller, the provider, and the
    # instance all allow it.
    if not (jit and provider.allow_jit):
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

    user = User(
        email_hash=hash_email(normalized),
        email_encrypted=encrypt_field(normalized, SALT_EMAIL),
        full_name=full_name or normalized,
        # No usable password: random throwaway until hashed_password turns
        # nullable in the final cutover phase.
        hashed_password=get_password_hash(secrets.token_urlsafe(32)),
        role=UserRole.member,
        status=UserStatus.active,
        avatar_url=avatar_url,
        email_verified=verified,
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
            identity = FederatedIdentity(
                user_id=user.id,
                provider_id=provider.id,
                subject=subject,
                email_verified=verified,
                last_login_at=datetime.now(timezone.utc),
            )
            session.add(identity)
            await session.flush()
        await session.commit()
        await session.refresh(user)
        await session.refresh(identity)
        return IdentityResolution(
            outcome=ResolutionOutcome.PROVISIONED, user=user, identity=identity
        )
    except IntegrityError:
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
        # (b) users.email_hash — a *different* subject with the same email (a
        #     second provider, or the IdP issuing a new subject) got there first.
        #     That is now an existing, unlinked account matched by email: the same
        #     EMAIL_MATCH / EMAIL_UNVERIFIED decision a non-raced login makes,
        #     never a silent link. Only a real asserted email can collide here —
        #     the synthetic {subject}@oidc.local address is subject-unique, so its
        #     only race is (a).
        if email:
            matched = (
                await session.exec(
                    select(User).where(
                        User.email_hash == hash_email(email.lower().strip())
                    )
                )
            ).one_or_none()
            if matched is not None:
                outcome = (
                    ResolutionOutcome.EMAIL_MATCH
                    if email_verified
                    else ResolutionOutcome.EMAIL_UNVERIFIED
                )
                return IdentityResolution(outcome=outcome, user=matched)
        raise
