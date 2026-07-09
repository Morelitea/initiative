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
from app.core.encryption import SALT_EMAIL, encrypt_field, hash_email
from app.core.security import get_password_hash
from app.models.platform.auth_provider import AuthProvider
from app.models.platform.federated_identity import FederatedIdentity
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
) -> IdentityResolution:
    """Resolve ``(provider, subject)`` to a user.

    ``email`` is the IdP-asserted address (``None`` when the IdP returns no
    email claim — a synthetic ``{subject}@oidc.local`` address is used for
    provisioning, mirroring the existing flow). Account-status checks (active,
    deactivated) stay with the caller, as they do today.
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
    # caller's policy decision (and requires the IdP to have verified the
    # address; an unverified match is refused outright to keep a mintable
    # unverified token from touching a victim's pre-registered account).
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

    # Unknown user: JIT-provision if the provider and the instance allow it.
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
    # No email claim: a synthetic address keyed off the IdP-controlled subject
    # (not attacker-choosable), as in the existing flow. It is not a mailbox,
    # so it is never marked verified.
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
    session.add(user)
    try:
        # User + identity land in ONE transaction: flush assigns the user id
        # without committing, then both commit together. So a failure can never
        # leave a committed, login-less user with no identity (the orphan case),
        # and there is no window where the user exists but the link doesn't.
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
        await session.commit()
        await session.refresh(user)
        await session.refresh(identity)
        return IdentityResolution(
            outcome=ResolutionOutcome.PROVISIONED, user=user, identity=identity
        )
    except IntegrityError:
        # Lost a provisioning race: a concurrent login inserted the same subject
        # (or email) first. Its conflicting unique insert blocked ours until it
        # committed, so the winner is now committed and visible — re-resolve to
        # it instead of failing the login. The rollback discards our uncommitted
        # user, so no orphan is left behind.
        await session.rollback()
        winner = await _find_identity(session, provider_id=provider.id, subject=subject)
        if winner is not None:
            user = (
                await session.exec(select(User).where(User.id == winner.user_id))
            ).one_or_none()
            if user is not None:
                return IdentityResolution(
                    outcome=ResolutionOutcome.LINKED, user=user, identity=winner
                )
        raise
