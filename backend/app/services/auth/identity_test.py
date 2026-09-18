"""Tests for OIDC identity resolution.

Pins the resolution ladder — (provider, subject) link first, verified-email
match surfaced but never written, JIT last and gated — and that refusals are
outcomes, not exceptions.
"""

from __future__ import annotations

import secrets

import pytest
from sqlmodel import select

from app.core.config import settings
from app.core.encryption import hash_email
from app.models.platform.auth_provider import AuthProvider, AuthProviderKind
from app.models.platform.federated_identity import FederatedIdentity
from app.models.platform.user import User, UserRole, UserStatus
from app.models.platform.user_email import UserEmail
from app.services.auth import addresses
from app.services.auth.identity import (
    IdentityResolution,
    ResolutionOutcome,
    link_identity,
    resolve_oidc_identity,
)
from app.testing import create_user

pytestmark = [pytest.mark.integration, pytest.mark.database]


async def _create_provider(session, *, allow_jit: bool = True) -> AuthProvider:
    provider = AuthProvider(
        slug=f"idp-{secrets.token_hex(4)}",
        display_name="Test IdP",
        kind=AuthProviderKind.oidc.value,
        enabled=True,
        issuer="https://idp.example.com",
        client_id="client-123",
        allow_jit=allow_jit,
    )
    session.add(provider)
    await session.commit()
    await session.refresh(provider)
    return provider


async def _address(session, user_id: int) -> UserEmail | None:
    """The account's primary address row — where an address lives."""
    return (
        await session.exec(
            select(UserEmail).where(UserEmail.user_id == user_id, UserEmail.is_primary)
        )
    ).one_or_none()


async def _resolve(session, provider, **overrides) -> IdentityResolution:
    kwargs = {
        "subject": "sub-1",
        "email": "alice@example.com",
        "email_verified": True,
        "full_name": "Alice",
    }
    kwargs.update(overrides)
    return await resolve_oidc_identity(session, provider=provider, **kwargs)


async def _identities_for(session, provider) -> list[FederatedIdentity]:
    return list(
        (
            await session.exec(
                select(FederatedIdentity).where(
                    FederatedIdentity.provider_id == provider.id
                )
            )
        ).all()
    )


# --- linked -------------------------------------------------------------------


async def test_existing_link_resolves_to_user(session):
    provider = await _create_provider(session)
    user = await create_user(session)
    await link_identity(
        session, user=user, provider=provider, subject="sub-1", email_verified=True
    )

    result = await _resolve(session, provider)
    assert result.outcome is ResolutionOutcome.LINKED
    assert result.user.id == user.id
    assert result.identity.last_login_at is not None
    # The returned user must be usable past its PK: the wiring endpoint reads
    # user.status for the active/deactivated gate. Sessions are expire_on_commit
    # =False (db/session.py + the fixture), so the SELECT-loaded user stays
    # populated after the identity commit — no lazy IO, no MissingGreenlet. This
    # access would raise if that ever regressed to expire-on-commit.
    assert result.user.status == UserStatus.active
    assert result.user.id == user.id


async def test_link_is_scoped_to_its_provider(session):
    """The same subject at a different provider is a different identity."""
    provider_a = await _create_provider(session)
    provider_b = await _create_provider(session, allow_jit=False)
    user = await create_user(session)
    await link_identity(
        session, user=user, provider=provider_a, subject="sub-1", email_verified=True
    )

    result = await _resolve(
        session, provider_b, email="nobody@example.com", subject="sub-1"
    )
    assert result.outcome is ResolutionOutcome.JIT_DISABLED


async def test_linked_login_refreshes_email_verified_snapshot(session):
    provider = await _create_provider(session)
    user = await create_user(session)
    await link_identity(
        session, user=user, provider=provider, subject="sub-1", email_verified=False
    )

    result = await _resolve(session, provider, email_verified=True)
    assert result.outcome is ResolutionOutcome.LINKED
    assert result.identity.email_verified is True


# --- email match (no link) ------------------------------------------------------


async def test_verified_email_match_is_surfaced_but_not_linked(session):
    """An unlinked account matched by verified email is the caller's policy
    decision — resolution itself must not write a link."""
    provider = await _create_provider(session)
    user = await create_user(session, email="alice@example.com")

    result = await _resolve(session, provider, email="alice@example.com")
    assert result.outcome is ResolutionOutcome.EMAIL_MATCH
    assert result.user.id == user.id
    assert result.identity is None
    assert await _identities_for(session, provider) == []


async def test_unverified_email_match_is_refused(session):
    provider = await _create_provider(session)
    await create_user(session, email="victim@example.com")

    result = await _resolve(
        session, provider, email="victim@example.com", email_verified=False
    )
    assert result.outcome is ResolutionOutcome.EMAIL_UNVERIFIED
    assert await _identities_for(session, provider) == []


# --- JIT provisioning -----------------------------------------------------------


async def test_unknown_user_is_provisioned_and_linked(session):
    provider = await _create_provider(session)

    result = await _resolve(session, provider, email="new@example.com")
    assert result.outcome is ResolutionOutcome.PROVISIONED
    user = result.user
    assert await addresses.holds_address(
        session, user_id=user.id, email="new@example.com"
    )
    assert user.role == UserRole.member
    assert user.status == UserStatus.active
    assert (await _address(session, user.id)).verified_at is not None
    assert user.full_name == "Alice"
    # SSO-only: no password is set — a NULL hash never verifies, so this
    # account signs in exclusively through its provider.
    assert user.hashed_password is None
    assert result.identity.subject == "sub-1"

    # The very next login resolves via the link.
    again = await _resolve(session, provider, email="new@example.com")
    assert again.outcome is ResolutionOutcome.LINKED
    assert again.user.id == user.id


async def test_provisioned_user_with_unverified_email_not_marked_verified(session):
    provider = await _create_provider(session)
    result = await _resolve(
        session, provider, email="fresh@example.com", email_verified=False
    )
    assert result.outcome is ResolutionOutcome.PROVISIONED
    assert (await _address(session, result.user.id)).verified_at is None


async def test_missing_email_claim_uses_synthetic_address(session):
    provider = await _create_provider(session)
    result = await _resolve(session, provider, email=None, subject="opaque-7")
    assert result.outcome is ResolutionOutcome.PROVISIONED
    row = await _address(session, result.user.id)
    assert row.email_hash == hash_email("opaque-7@oidc.local")
    # A synthetic address is not a mailbox; it is never marked verified.
    assert row.verified_at is None


async def test_jit_disabled_provider_refuses_unknown_user(session):
    provider = await _create_provider(session, allow_jit=False)
    result = await _resolve(session, provider, email="stranger@example.com")
    assert result.outcome is ResolutionOutcome.JIT_DISABLED
    assert result.user is None
    assert await _identities_for(session, provider) == []


async def test_provision_recovers_from_subject_race_without_orphan(session):
    """Case (a): a concurrent login committed our (provider, subject) first.
    _provision must resolve to the winner (LINKED) and leave no orphaned user.
    (The winner is created via a prior commit, which survives the service's
    rollback; _provision is called directly since the top-level resolve would
    short-circuit to LINKED before ever provisioning.)"""
    from app.services.auth.identity import _provision

    provider = await _create_provider(session)
    winner = await create_user(session, email="winner@example.com")
    await link_identity(
        session, user=winner, provider=provider, subject="sub-1", email_verified=True
    )

    result = await _provision(
        session,
        provider=provider,
        subject="sub-1",
        email="loser@example.com",
        email_verified=True,
        full_name="Loser",
        avatar_url=None,
    )
    assert result.outcome is ResolutionOutcome.LINKED
    assert result.user.id == winner.id
    # Our uncommitted user was rolled back — no orphan.
    loser = (
        await session.exec(
            select(User)
            .join(UserEmail, UserEmail.user_id == User.id)
            .where(UserEmail.email_hash == hash_email("loser@example.com"))
        )
    ).one_or_none()
    assert loser is None


async def test_provision_recovers_from_email_race_as_email_match(session):
    """Case (b): a *different* subject with the same email won the email_hash
    unique race. The loser must surface EMAIL_MATCH (never a silent link), not
    re-raise a 500."""
    from app.services.auth.identity import _provision

    provider = await _create_provider(session)
    winner = await create_user(session, email="shared@example.com")

    result = await _provision(
        session,
        provider=provider,
        subject="sub-new",
        email="shared@example.com",
        email_verified=True,
        full_name="Loser",
        avatar_url=None,
    )
    assert result.outcome is ResolutionOutcome.EMAIL_MATCH
    assert result.user.id == winner.id
    assert await _identities_for(session, provider) == []  # no link written


async def test_provision_email_race_unverified_is_refused(session):
    """Case (b) with an unverified asserted email → EMAIL_UNVERIFIED, mirroring
    the non-raced account-takeover guard."""
    from app.services.auth.identity import _provision

    provider = await _create_provider(session)
    winner = await create_user(session, email="victim@example.com")

    result = await _provision(
        session,
        provider=provider,
        subject="sub-new",
        email="victim@example.com",
        email_verified=False,
        full_name="Attacker",
        avatar_url=None,
    )
    assert result.outcome is ResolutionOutcome.EMAIL_UNVERIFIED
    assert result.user.id == winner.id
    assert await _identities_for(session, provider) == []


async def test_closed_registration_refuses_unknown_user(session, monkeypatch):
    provider = await _create_provider(session)
    await create_user(session)  # instance is not empty → no bootstrap exception
    monkeypatch.setattr(settings, "ENABLE_PUBLIC_REGISTRATION", False)

    result = await _resolve(session, provider, email="stranger@example.com")
    assert result.outcome is ResolutionOutcome.REGISTRATION_DISABLED
    assert await _identities_for(session, provider) == []


async def test_a_guilds_pkce_provider_counts_as_a_way_in(session):
    """A guild's provider needs no client secret, and may carry any slug —
    including the one the operator-global row uses in its own namespace.

    The secret requirement belongs to the operator-global row, which is
    identified by ``guild_id IS NULL`` and not by its slug. A guild row sharing
    that slug answers logins, so it counts as a way in like any other.
    """
    from app.services.auth.identity import (
        federated_only_user_count,
        password_only_user_count,
    )
    from app.testing.factories import (
        create_auth_provider,
        create_federated_identity,
        create_guild,
        create_user,
    )

    guild = await create_guild(session)
    provider = await create_auth_provider(
        session, slug="oidc", guild_id=guild.id
    )  # no client secret: PKCE-only, which a guild provider may be
    member = await create_user(session, hashed_password=None)
    await create_federated_identity(session, member, provider=provider)

    # Their only way in is that provider, so withdrawing SSO concerns them.
    assert await federated_only_user_count(session) == 1

    # And somebody holding a password *and* that provider is not an account the
    # password is holding up. Measured as a delta: creating the guild above
    # made its own creator, who holds a password and no identity.
    baseline = await password_only_user_count(session)
    holder = await create_user(session)
    await create_federated_identity(session, holder, provider=provider)
    assert await password_only_user_count(session) == baseline
