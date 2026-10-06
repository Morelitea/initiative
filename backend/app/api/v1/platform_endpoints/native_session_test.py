"""The session a native client is given.

The phone and desktop apps sign in like a browser does, and are told apart by
the origin they present. A device's session stands longer unused, and the app
is handed its refresh token in the body as well as the cookie, because it keeps
the token in the platform's secure storage rather than in a jar the browser
manages — so the refresh also has to work without a cookie.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.security import decode_session_token
from app.models.platform.auth_session import AuthSession
from app.testing import create_user


PASSWORD = "testpassword123"
PLUGIN_ORIGIN = {"Origin": "https://studio.beyonders.initiative"}


async def _sign_in_native(client: AsyncClient, email: str) -> dict:
    response = await client.post(
        "/api/v1/auth/token",
        data={"username": email, "password": PASSWORD, "device_name": "test-phone"},
        headers=PLUGIN_ORIGIN,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_a_native_sign_in_opens_a_device_session(
    client: AsyncClient, session: AsyncSession
):
    """The app's origin marks the session as a device's and hands the refresh
    token back in the body; a browser's sign-in gets neither."""
    await create_user(session, email="native-signin@example.com")

    body = await _sign_in_native(client, "native-signin@example.com")

    assert body["refresh_token"]
    # The access token names the account and the session it belongs to.
    claims = decode_session_token(body["access_token"])
    device = await session.get(AuthSession, uuid.UUID(claims["sid"]))
    assert device is not None
    assert device.device is True
    assert device.device_name == "test-phone"

    browser = await client.post(
        "/api/v1/auth/token",
        data={
            "username": "native-signin@example.com",
            "password": PASSWORD,
            "device_name": "not-a-device",
        },
    )
    assert browser.status_code == 200, browser.text
    assert not browser.json().get("refresh_token")
    sid = decode_session_token(browser.json()["access_token"])["sid"]
    opened = await session.get(AuthSession, uuid.UUID(sid))
    assert opened is not None
    assert opened.device is False
    # The label is a device's; a browser's session is named by its user agent.
    assert opened.device_name is None


async def test_the_session_renews_without_a_cookie(
    client: AsyncClient, session: AsyncSession
):
    """The refresh token presented in the body, because there is no cookie to
    read it from — and the rotated one comes back the same way."""
    await create_user(session, email="native-refresh@example.com")
    body = await _sign_in_native(client, "native-refresh@example.com")

    # A jar of its own, so nothing the sign-in set can stand in for the body.
    async with AsyncClient(
        transport=client._transport, base_url=str(client.base_url)
    ) as bare:
        renewed = await bare.post(
            "/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]}
        )

    assert renewed.status_code == 200, renewed.text
    payload = renewed.json()
    assert payload["access_token"]
    # Rotation: a different token comes back, and it comes back in the body.
    assert payload["refresh_token"]
    assert payload["refresh_token"] != body["refresh_token"]

    # Nobody has touched the app for longer than a device's window: the
    # renewal ends the session rather than extending it.
    async with AsyncClient(
        transport=client._transport, base_url=str(client.base_url)
    ) as bare:
        idle = await bare.post(
            "/api/v1/auth/refresh",
            json={
                "refresh_token": payload["refresh_token"],
                "idle_seconds": 91 * 86400,
            },
        )
    assert idle.status_code == 401

    # An idle time no window could hold is refused as a bad request, not a fault.
    async with AsyncClient(
        transport=client._transport, base_url=str(client.base_url)
    ) as bare:
        absurd = await bare.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": payload["refresh_token"], "idle_seconds": 10**12},
        )
    assert absurd.status_code == 422


async def test_a_narrowed_session_narrows_the_token_the_plugin_is_handed(
    client: AsyncClient, session: AsyncSession
):
    """A session that ends sooner than the deployment's access-token lifetime
    ends its tokens with it, on the app's way in as on the browser's."""
    from app.services.platform import app_settings as app_settings_service

    row = await app_settings_service.get_app_settings(session)
    row.session_idle_minutes = 5
    session.add(row)
    await create_user(session, email="native-narrowed@example.com")
    await session.commit()
    ceiling = timedelta(minutes=5).total_seconds()

    signed_in = await _sign_in_native(client, "native-narrowed@example.com")
    claims = decode_session_token(signed_in["access_token"])
    assert claims["exp"] - claims["iat"] <= ceiling
