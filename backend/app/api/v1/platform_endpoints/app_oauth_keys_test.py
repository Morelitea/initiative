"""Which registrations the token endpoint answers: live ones, and whatever
key set they keep.

A registration is live while it is switched on, its publisher is switched on,
and it has a key set — pasted, or published at its key set address. The key
set's fetch is stood in for here; ``app_keys_test`` covers it.
"""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.marketplace import app_keys, app_oauth
from app.services.marketplace.registration_lookup import invalidate_registrations
from app.testing.app_clients import (
    CLIENT,
    client_jwks,
    install_app,
    mint_client_assertion,
)


TOKEN_URL = "/api/v1/app-platform/oauth/token"
ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
APP_BASE = "https://tracker.example.test"


async def _ask(client: AsyncClient):
    return await client.post(
        TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_assertion_type": ASSERTION_TYPE,
            "client_assertion": mint_client_assertion(
                audience=app_oauth.token_endpoint_url()
            ),
        },
    )


async def _update(session: AsyncSession, sql: str, **params) -> None:
    await session.exec(text(sql).bindparams(client=CLIENT, **params))
    await session.commit()
    invalidate_registrations()


async def test_a_key_set_published_at_its_address_authenticates(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    role_session,
    monkeypatch,
):
    await install_app(session, acting_user, role_session, granted=["documents:read"])
    await _update(
        session,
        "UPDATE public.app_service_registrations "
        "SET jwks = NULL, base_url = :base, jwks_uri = :uri WHERE public_id = :client",
        base=APP_BASE,
        uri=f"{APP_BASE}/.well-known/jwks.json",
    )
    fetched: list[str] = []

    async def _fetch(jwks_uri, transport):
        fetched.append(jwks_uri)
        return app_keys._parse(client_jwks(), jwks_uri)

    monkeypatch.setattr(app_keys, "_fetch", _fetch)
    app_keys.clear_fetched_keys()

    response = await _ask(client)

    assert response.status_code == 200, response.text
    assert fetched == [f"{APP_BASE}/.well-known/jwks.json"]


async def test_a_registration_with_no_key_set_is_an_invalid_client(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    await install_app(session, acting_user, role_session, granted=["documents:read"])
    await _update(
        session,
        "UPDATE public.app_service_registrations SET jwks = NULL "
        "WHERE public_id = :client",
    )

    response = await _ask(client)

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_client"


async def test_a_switched_off_publisher_is_an_invalid_client(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    await install_app(session, acting_user, role_session, granted=["documents:read"])
    await _update(
        session,
        "UPDATE public.publishers SET enabled = false WHERE id = "
        "(SELECT publisher_id FROM public.app_service_registrations "
        "WHERE public_id = :client)",
    )

    response = await _ask(client)

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_client"
