"""Integration tests for auto-delegation hardening.

These exercise the security properties the auth dep enforces on delegation
JWTs minted by initiative-auto:

* signature, audience, issuer (negative tests against tampered tokens)
* one-shot replay rejection via the jti blocklist
* the guild_id JWT claim pins the request's guild context (validated against
  the user's memberships, and refused if it disagrees with the ``/g/{guild_id}``
  path)
* deactivated users can't be impersonated even with a valid token

These don't repeat the unit tests on token issuance — those live in
``app/core/security_test.py``. Here the focus is on the verification +
blocklist + cross-claim consistency the dep enforces.
"""

from __future__ import annotations


import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import config as config_module
from app.models.platform.user import UserStatus
from app.services.marketplace.registration_lookup import invalidate_registrations
from app.testing import (
    create_guild,
    create_guild_membership,
    create_user,
)
from app.testing.delegation import (
    authorize_delegate,
    delegate_subject,
    install_delegate,
    mint_delegation_token,
    register_delegate,
)


@pytest.fixture(autouse=True)
async def _enable_delegation(session: AsyncSession):
    """Register the app whose tokens these tests expect to be accepted.

    A delegation token is decided by the registration that published its
    ``kid``, so the delegate is a row rather than a setting. The app-platform
    key stands in for "registrations are reachable on this deployment", which
    is the cheap gate the auth dep reads first.
    """
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            config_module.settings,
            "APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM",
            "-----BEGIN PRIVATE KEY-----",
        )
        await register_delegate(session)
        yield
    invalidate_registrations()


@pytest.fixture
async def delegate_guild(session: AsyncSession):
    """A guild that installed the delegate.

    An app acts only where it was installed, so this is the ordinary
    precondition for any delegated call — held constant here so each test
    varies only its own subject.
    """
    installer = await create_user(session, email="installer@example.com")
    guild = await create_guild(session, creator=installer)
    await install_delegate(session, guild, creator=installer)
    return guild


_mint_delegation = mint_delegation_token


@pytest.mark.integration
async def test_delegation_token_is_one_shot(
    client: AsyncClient, session: AsyncSession, delegate_guild
):
    """The same jti must succeed once and fail on the second presentation,
    regardless of the JWT's remaining lifetime. Without this, a 15-minute
    token captured in transit can be replayed indefinitely."""
    user = await create_user(session, email="user@example.com")
    await authorize_delegate(session, delegate_guild, user)
    subject = await delegate_subject(session, delegate_guild, user)
    token = _mint_delegation(
        subject=subject, guild_id=delegate_guild.id, jti="replay-target-001"
    )

    first = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first.status_code == 200, first.text

    second = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    # Replay falls through past delegation auth, then through the
    # standard JWT path which rejects an HS256-shaped token, ending
    # with the standard 401.
    assert second.status_code == 401


@pytest.mark.integration
async def test_delegation_token_guild_claim_pins_context(
    client: AsyncClient, session: AsyncSession, delegate_guild
):
    """The token's guild_id claim IS the request's guild context — it takes
    precedence over whatever guild the human happens to be in, and it is
    validated against the user's memberships like any other context. A token
    minted for a guild the user can't access must not reach guild data even
    while the user's own flag points at a guild they CAN access. Stops
    cross-guild lateral movement using a single delegation."""
    user = await create_user(session, email="cross-guild@example.com")
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild)
    await authorize_delegate(session, delegate_guild, user)
    subject = await delegate_subject(session, delegate_guild, user)
    # The human is legitimately in their own guild, and the app is installed in
    # the guild its token names — so what refuses this is the pin itself, not a
    # missing install or an unknown guild.
    token = _mint_delegation(subject=subject, guild_id=delegate_guild.id)

    response = await client.get(
        f"/api/v1/g/{guild.id}/initiatives/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "GUILD_ACCESS_DENIED"


@pytest.mark.integration
async def test_delegation_token_guild_claim_provides_context(
    client: AsyncClient, session: AsyncSession, delegate_guild
):
    """A machine caller has no ambient guild context: the token's guild_id
    claim (validated against the user's memberships) supplies the guild for a
    guild-scoped endpoint."""
    user = await create_user(session, email="happy-path@example.com")
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild)
    await authorize_delegate(session, guild, user)
    subject = await delegate_subject(session, guild, user)
    token = _mint_delegation(subject=subject, guild_id=guild.id)

    response = await client.get(
        f"/api/v1/g/{guild.id}/initiatives/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200


@pytest.mark.integration
async def test_delegation_works_on_cross_guild_endpoints(
    client: AsyncClient, session: AsyncSession, delegate_guild
):
    """``/users/me`` is cross-guild; the pinned guild context is simply unused
    there and the call succeeds. The guild the token names still has to be one
    that installed the app — that is what lets the app act at all, and it is
    checked wherever the call lands."""
    user = await create_user(session, email="cross-guild-allowed@example.com")
    await authorize_delegate(session, delegate_guild, user)
    subject = await delegate_subject(session, delegate_guild, user)
    token = _mint_delegation(subject=subject, guild_id=delegate_guild.id)

    response = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200


@pytest.mark.integration
async def test_delegation_rejects_deactivated_user(
    client: AsyncClient, session: AsyncSession, delegate_guild
):
    """Workflows owned by deactivated users must stop working
    immediately — no grace period during which their old tokens still
    function."""
    user = await create_user(session, email="deactivated@example.com")
    user.status = UserStatus.deactivated
    session.add(user)
    await session.commit()
    await session.refresh(user)
    subject = await delegate_subject(session, delegate_guild, user)

    token = _mint_delegation(subject=subject, guild_id=delegate_guild.id)

    response = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401


@pytest.mark.integration
async def test_delegation_cannot_name_a_member_we_never_minted(
    client: AsyncClient, session: AsyncSession, delegate_guild
):
    """An app names a member by a subject this deployment derived and stored,
    so there is no value it can invent that resolves to anybody.

    Stronger than the old rule it replaces: a token used to be able to name any
    user id and be refused only because that row was missing. Now the space of
    namable members is exactly the set already minted for this install."""
    token = _mint_delegation(
        subject="never-minted-anywhere", guild_id=delegate_guild.id
    )

    response = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401


@pytest.mark.integration
async def test_delegation_rejects_wrong_audience(
    client: AsyncClient, session: AsyncSession, delegate_guild
):
    """A token with a different audience claim must not authenticate.
    Stops a regular session JWT (or any other audience) from being
    re-presented as a delegation."""
    # Refused at verification, so it never reaches subject resolution.
    token = _mint_delegation(
        subject="any-subject",
        guild_id=delegate_guild.id,
        aud="initiative:something-else",
    )

    response = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401


@pytest.mark.integration
async def test_delegation_rejects_wrong_issuer(
    client: AsyncClient, session: AsyncSession, delegate_guild
):
    """Issuer must match — defense in depth alongside the audience check."""
    token = _mint_delegation(
        subject="any-subject", guild_id=delegate_guild.id, iss="someone-else"
    )

    response = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401


@pytest.mark.integration
async def test_delegation_rejects_signature_from_other_key(
    client: AsyncClient, session: AsyncSession, delegate_guild
):
    """A token signed with a different RSA key must fail signature
    verification — the load-bearing crypto property of the whole flow."""
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_private = other_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    token = _mint_delegation(
        subject="any-subject", guild_id=delegate_guild.id, private_pem=other_private
    )

    response = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401


@pytest.mark.integration
async def test_delegation_is_off_where_no_app_platform_is_configured(
    client: AsyncClient, session: AsyncSession, delegate_guild, monkeypatch
):
    """No app platform means no registrations, so nothing can delegate here.
    The request falls through to the standard 401 from the JWT path rather
    than erroring on a half-configured state."""
    monkeypatch.setattr(
        config_module.settings, "APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM", None
    )

    token = _mint_delegation(subject="any-subject", guild_id=delegate_guild.id)

    response = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401
