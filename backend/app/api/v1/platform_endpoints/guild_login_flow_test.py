"""The guild-addressed login flow: public per-guild provider discovery, the
``/auth/g/{guild_id}/{slug}/login`` + ``/callback`` relying-party routes, the
guild-namespaced flow-state binding, JIT suppression for guild providers, and
the step-up session union (satisfying one guild never un-satisfies another).

Runs against the same fake IdP harness as the operator flow tests."""

from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.v1.platform_endpoints.auth_test import _wire_fake_idp
from app.core.security import REFRESH_COOKIE_NAME
from app.models.platform.auth_session import AuthSession
from app.models.platform.guild import GuildMembership, GuildRole
from app.services.auth import sessions as session_service
from app.testing.factories import (
    create_auth_provider,
    create_federated_identity,
    create_user,
    set_auth_scope,
)
from app.testing.oidc import ISSUER as OIDC_ISSUER, FakeIdp, mint_id_token

pytestmark = [pytest.mark.integration, pytest.mark.auth]


async def _guild_provider(session: AsyncSession, **overrides):
    """A login-ready guild-scoped provider in a fresh guild, with the platform
    flipped to per-guild posture."""
    from app.testing.factories import create_guild

    await set_auth_scope(session)
    guild = await create_guild(session)
    provider = await create_auth_provider(
        session, slug="corp", guild_id=guild.id, **overrides
    )
    return guild, provider


async def _begin_guild_login(
    client: AsyncClient, guild_id: int, slug: str = "corp", params: dict | None = None
) -> tuple[str, str]:
    response = await client.get(
        f"/api/v1/auth/g/{guild_id}/{slug}/login",
        params=params or {},
        follow_redirects=False,
    )
    assert response.status_code in (302, 307), response.text
    location = response.headers["location"]
    assert location.startswith(f"{OIDC_ISSUER}/authorize?")
    query = {k: v[0] for k, v in parse_qs(urlsplit(location).query).items()}
    return query["state"], query["nonce"]


async def _run_guild_flow(
    client: AsyncClient,
    idp: FakeIdp,
    guild_id: int,
    *,
    slug: str = "corp",
    callback_guild_id: int | None = None,
    id_token_claims: dict | None = None,
):
    """Begin at one guild's login, complete at (by default) the same guild's
    callback; returns the callback response."""
    state, nonce = await _begin_guild_login(client, guild_id, slug)
    idp.token_response = httpx.Response(
        200,
        json={
            "access_token": "at-1",
            "refresh_token": "rt-1",
            "id_token": mint_id_token(nonce=nonce, **(id_token_claims or {})),
            "token_type": "Bearer",
        },
    )
    return await client.get(
        f"/api/v1/auth/g/{callback_guild_id or guild_id}/{slug}/callback",
        params={"code": "code-1", "state": state},
        follow_redirects=False,
    )


async def _latest_session(session: AsyncSession) -> AuthSession | None:
    session.expire_all()
    rows = (
        await session.exec(select(AuthSession).order_by(AuthSession.created_at.desc()))
    ).all()
    return rows[0] if rows else None


async def test_guild_listing_serves_guild_login_urls(
    client: AsyncClient, session: AsyncSession
):
    guild, provider = await _guild_provider(session)
    await create_auth_provider(session, slug="off", enabled=False, guild_id=guild.id)

    guild_name = guild.name
    response = await client.get(f"/api/v1/auth/g/{guild.id}/providers")
    assert response.status_code == 200
    body = response.json()
    entries = body["providers"]
    assert [e["slug"] for e in entries] == ["corp"]
    assert entries[0]["id"] == provider.id
    assert entries[0]["login_url"] == f"/api/v1/auth/g/{guild.id}/corp/login"
    # The guild's display name rides along exactly when providers do — its
    # login page is meant to be shared.
    assert body["guild_name"] == guild_name

    # An unknown guild is indistinguishable from an empty registry.
    empty = await client.get("/api/v1/auth/g/999999/providers")
    assert empty.json() == {"providers": [], "guild_name": None}


async def test_guild_listing_empty_in_platform_posture(
    client: AsyncClient, session: AsyncSession
):
    guild, _provider = await _guild_provider(session)
    await set_auth_scope(session, scope="platform")

    response = await client.get(f"/api/v1/auth/g/{guild.id}/providers")
    assert response.json()["providers"] == []


async def test_guild_login_begins_flow_and_carries_next(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    guild, _provider = await _guild_provider(session)
    _wire_fake_idp(monkeypatch, FakeIdp())

    response = await client.get(
        f"/api/v1/auth/g/{guild.id}/corp/login",
        params={"next": f"/g/{guild.id}/projects/3"},
        follow_redirects=False,
    )
    assert response.status_code in (302, 307)
    assert response.headers["location"].startswith(f"{OIDC_ISSUER}/authorize?")
    assert "oidc_next=" in response.headers.get("set-cookie", "")


async def test_guild_login_absent_in_platform_posture(
    client: AsyncClient, session: AsyncSession
):
    guild, _provider = await _guild_provider(session)
    await set_auth_scope(session, scope="platform")

    response = await client.get(
        f"/api/v1/auth/g/{guild.id}/corp/login", follow_redirects=False
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "OIDC_NOT_ENABLED"


async def test_guild_callback_signs_in_linked_user_with_sat(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    guild, provider = await _guild_provider(session)
    user = await create_user(session)
    await create_federated_identity(
        session, user, subject="idp-subject-1", provider=provider
    )
    user_id, provider_id, provider_slug = user.id, provider.id, provider.slug
    idp = FakeIdp()
    _wire_fake_idp(monkeypatch, idp)

    response = await _run_guild_flow(client, idp, guild.id)
    assert response.status_code in (302, 307), response.text
    assert "/oidc/callback" in response.headers["location"]
    assert "error=" not in response.headers["location"]
    assert REFRESH_COOKIE_NAME in response.headers.get("set-cookie", "")

    row = await _latest_session(session)
    assert row is not None
    assert row.user_id == user_id
    assert row.satisfied_providers == [provider_id]
    assert f"oidc:{provider_slug}" in row.amr


async def test_guild_callback_jit_provisions_user_and_membership(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """An unknown user completing a guild-provider login is JIT-provisioned
    AND admitted to the guild — under ``allow_jit`` alone, independent of the
    platform's registration setting (the guild's IdP is the invitation)."""
    from app.core.config import settings as app_config

    monkeypatch.setattr(app_config, "ENABLE_PUBLIC_REGISTRATION", False)
    guild, provider = await _guild_provider(session)
    guild_id, provider_id = guild.id, provider.id
    idp = FakeIdp()
    _wire_fake_idp(monkeypatch, idp)

    response = await _run_guild_flow(
        client,
        idp,
        guild_id,
        id_token_claims={
            "sub": "new-hire",
            "email": "new@example.com",
            "email_verified": True,
        },
    )
    assert response.status_code in (302, 307), response.text
    assert "error=" not in response.headers["location"]

    row = await _latest_session(session)
    assert row is not None
    assert row.satisfied_providers == [provider_id]
    membership = (
        await session.exec(
            select(GuildMembership).where(
                GuildMembership.guild_id == guild_id,
                GuildMembership.user_id == row.user_id,
            )
        )
    ).one_or_none()
    assert membership is not None
    assert membership.role == GuildRole.member


async def test_guild_callback_admits_existing_user_to_guild(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """A linked existing user who isn't yet a member gains a plain-member
    membership by signing in through the guild's provider."""
    guild, provider = await _guild_provider(session)
    user = await create_user(session)
    await create_federated_identity(
        session, user, subject="idp-subject-1", provider=provider
    )
    guild_id, user_id = guild.id, user.id
    idp = FakeIdp()
    _wire_fake_idp(monkeypatch, idp)

    response = await _run_guild_flow(client, idp, guild_id)
    assert response.status_code in (302, 307), response.text
    assert "error=" not in response.headers["location"]

    session.expire_all()
    membership = (
        await session.exec(
            select(GuildMembership).where(
                GuildMembership.guild_id == guild_id,
                GuildMembership.user_id == user_id,
            )
        )
    ).one_or_none()
    assert membership is not None
    assert membership.role == GuildRole.member


async def test_guild_callback_refused_when_guild_full(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    guild, provider = await _guild_provider(session)
    guild.max_users = 0
    session.add(guild)
    await session.commit()
    guild_id = guild.id
    idp = FakeIdp()
    _wire_fake_idp(monkeypatch, idp)

    response = await _run_guild_flow(
        client,
        idp,
        guild_id,
        id_token_claims={
            "sub": "late-arrival",
            "email": "late@example.com",
            "email_verified": True,
        },
    )
    assert response.status_code in (302, 307)
    assert "error=GUILD_USER_LIMIT_REACHED" in response.headers["location"]
    assert await _latest_session(session) is None
    assert (
        await session.exec(
            select(GuildMembership).where(GuildMembership.guild_id == guild_id)
        )
    ).all() == []


async def test_guild_callback_refuses_unknown_user_when_jit_off(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """With the provider's JIT switch off, an unknown user is refused —
    existing accounts only."""
    guild, _provider = await _guild_provider(session, allow_jit=False)
    idp = FakeIdp()
    _wire_fake_idp(monkeypatch, idp)

    response = await _run_guild_flow(
        client,
        idp,
        guild.id,
        id_token_claims={"sub": "nobody", "email": "nobody@example.com"},
    )
    assert response.status_code in (302, 307)
    assert "error=OIDC_REGISTRATION_DISABLED" in response.headers["location"]
    assert await _latest_session(session) is None


async def test_state_bound_to_one_guilds_provider(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """A flow begun with guild A's provider cannot complete against guild B's
    same-slug provider — the state is namespaced to the guild."""
    guild_a, provider_a = await _guild_provider(session)
    from app.testing.factories import create_guild

    guild_b = await create_guild(session)
    await create_auth_provider(session, slug="corp", guild_id=guild_b.id)
    user = await create_user(session)
    await create_federated_identity(
        session, user, subject="idp-subject-1", provider=provider_a
    )
    idp = FakeIdp()
    _wire_fake_idp(monkeypatch, idp)

    response = await _run_guild_flow(
        client, idp, guild_a.id, callback_guild_id=guild_b.id
    )
    assert response.status_code in (302, 307)
    assert "error=" in response.headers["location"]
    assert await _latest_session(session) is None


async def test_step_up_unions_satisfied_providers(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """Completing a guild step-up carries the live session's satisfied set
    forward and revokes the session it replaces."""
    guild, provider = await _guild_provider(session)
    user = await create_user(session)
    await create_federated_identity(
        session, user, subject="idp-subject-1", provider=provider
    )
    issued = await session_service.create_session(
        session,
        user_id=user.id,
        amr=["pwd"],
        satisfied_providers=[41414],
    )
    await session.commit()
    prior_id = issued.session.id
    provider_id, provider_slug = provider.id, provider.slug
    refresh_token = issued.refresh_token
    idp = FakeIdp()
    _wire_fake_idp(monkeypatch, idp)

    client.cookies.set(REFRESH_COOKIE_NAME, refresh_token)
    try:
        response = await _run_guild_flow(client, idp, guild.id)
    finally:
        client.cookies.delete(REFRESH_COOKIE_NAME)
    assert response.status_code in (302, 307), response.text
    assert "error=" not in response.headers["location"]

    row = await _latest_session(session)
    assert row is not None
    assert row.id != prior_id
    assert row.satisfied_providers == sorted([41414, provider_id])
    assert set(row.amr) >= {"pwd", f"oidc:{provider_slug}"}

    prior = await session.get(AuthSession, prior_id)
    assert prior is not None and prior.revoked_at is not None


async def test_step_up_revokes_racing_rotation_child(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """A /auth/refresh that rotates the presented session between the
    callback's read and its write must not leave the rotation child running
    beside the stepped-up session: the replacement chain-revokes. Simulated
    by rotating for real and pinning the callback's read to the original
    row (the pre-rotation interleaving)."""
    import app.api.v1.platform_endpoints.auth as auth_module

    guild, provider = await _guild_provider(session)
    user = await create_user(session)
    await create_federated_identity(
        session, user, subject="idp-subject-1", provider=provider
    )
    issued = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[41414]
    )
    await session.commit()
    prior_id = issued.session.id
    provider_id = provider.id

    rotation = await session_service.rotate_session(
        session, raw_refresh_token=issued.refresh_token
    )
    await session.commit()
    assert rotation.ok and rotation.issued is not None
    child_id = rotation.issued.session.id

    async def _read_prior(admin_session, raw):
        return await admin_session.get(AuthSession, prior_id)

    monkeypatch.setattr(
        auth_module.session_service, "get_live_session_by_refresh_token", _read_prior
    )
    idp = FakeIdp()
    _wire_fake_idp(monkeypatch, idp)

    client.cookies.set(REFRESH_COOKIE_NAME, issued.refresh_token)
    try:
        response = await _run_guild_flow(client, idp, guild.id)
    finally:
        client.cookies.delete(REFRESH_COOKIE_NAME)
    assert response.status_code in (302, 307), response.text
    assert "error=" not in response.headers["location"]

    row = await _latest_session(session)
    assert row is not None
    assert row.id not in (prior_id, child_id)
    assert row.satisfied_providers == sorted([41414, provider_id])
    assert row.revoked_at is None

    child = await session.get(AuthSession, child_id)
    assert child is not None and child.revoked_at is not None
