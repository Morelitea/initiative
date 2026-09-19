"""The scheduled sweep that re-reads group claims.

One test, about the thing that is invisible when it breaks: the sweep visits
every provider that asserts a claim path, and a provider it cannot finish is
skipped rather than taking the rest of the run with it.
"""

import pytest
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services import oidc_refresh
from app.testing.factories import create_auth_provider

pytestmark = pytest.mark.integration


async def _configured(session: AsyncSession, slug: str):
    """A provider the sweep will pick up: enabled, with a claim path."""
    return await create_auth_provider(
        session,
        slug=slug,
        enabled=True,
        issuer=f"https://{slug}.example.com",
        client_id=f"{slug}-client",
        role_claim_path="groups",
    )


async def test_every_configured_provider_is_visited(session, monkeypatch):
    await _configured(session, "corp")
    await _configured(session, "partner")
    # Enabled, but asserts no groups — nothing for this sweep to read.
    await create_auth_provider(
        session, slug="social", enabled=True, role_claim_path=None
    )
    await session.commit()

    seen: list[str] = []

    async def _record(_session, provider):
        seen.append(provider.slug)

    monkeypatch.setattr(oidc_refresh, "_sweep_provider", _record)
    await oidc_refresh.process_oidc_refresh_sync()

    assert sorted(seen) == ["corp", "partner"]


async def test_a_provider_that_fails_does_not_take_the_others_with_it(
    session, monkeypatch
):
    """Each provider is swept in a session of its own, so the one after a
    failure still has a usable transaction to work in."""
    await _configured(session, "aaa-broken")
    await _configured(session, "zzz-healthy")
    await session.commit()

    finished: list[str] = []

    async def _sometimes_fails(db_session, provider):
        if provider.slug == "aaa-broken":
            # A database error, not a network one — the server aborts the
            # transaction, which is the state a shared session would carry
            # into the provider swept next.
            await db_session.exec(text("SELECT this_is_not_a_column"))
        # Proves the session handed to this provider can still do work.
        await db_session.exec(text("SELECT 1"))
        finished.append(provider.slug)

    monkeypatch.setattr(oidc_refresh, "_sweep_provider", _sometimes_fails)
    await oidc_refresh.process_oidc_refresh_sync()

    assert finished == ["zzz-healthy"]
