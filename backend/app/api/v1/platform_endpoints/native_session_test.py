"""The session a native client is given, beside the device token it already had.

The device token is not going anywhere yet: an installed build keeps sending
one and keeps working. What these cover is the way across — a sign-in that
hands back a session as well, an exchange for the clients whose token arrived
by some other route, and a refresh that works without a cookie, because a
native client keeps its refresh token in the platform's secure storage rather
than in a jar the browser manages.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.security import decode_session_token
from app.models.platform.user_token import UserToken, UserTokenPurpose
from app.services.platform import user_tokens
from app.testing import create_user, emitted

pytestmark = [pytest.mark.integration, pytest.mark.auth]

PASSWORD = "testpassword123"


async def _sign_in_native(client: AsyncClient, email: str) -> dict:
    response = await client.post(
        "/api/v1/auth/device-token",
        json={"email": email, "password": PASSWORD, "device_name": "test-phone"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _events(capfd, user_id: int) -> list[str]:
    return [
        envelope["event_type"]
        for envelope in emitted(capfd)
        if envelope["actor_user_id"] == user_id
    ]


async def test_a_native_sign_in_hands_back_a_session_too(
    client: AsyncClient, session: AsyncSession, capfd
):
    """Both credentials, so a build that prefers the session has one from the
    first sign-in and a build that does not is unaffected."""
    user = await create_user(session, email="native-signin@example.com")
    user_id = user.id
    capfd.readouterr()

    body = await _sign_in_native(client, "native-signin@example.com")

    assert body["device_token"]
    assert body["refresh_token"]
    assert body["expires_in"] > 0
    # The access token names the account and the session it belongs to.
    claims = decode_session_token(body["access_token"])
    assert claims["sid"]

    assert AuditEventType.AUTH_DEVICE_TOKEN_ISSUED.value in _events(capfd, user_id)


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


async def test_a_device_token_buys_a_session_and_survives_it(
    client: AsyncClient, session: AsyncSession
):
    """The way across for a client that already holds a token — the one the
    OIDC flow hands out in a redirect, where a refresh token cannot go."""
    user = await create_user(session, email="native-exchange@example.com")
    device_token = await user_tokens.create_device_token(
        session, user_id=user.id, device_name="old-phone"
    )
    await session.commit()

    response = await client.post(
        "/api/v1/auth/device-token/exchange", json={"device_token": device_token}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["access_token"] and body["refresh_token"]

    # The token it traded is still good: the client decides when to stop
    # sending it, not this call.
    still_there = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"DeviceToken {device_token}"}
    )
    assert still_there.status_code == 200


async def test_an_exchanged_session_claims_no_factors(
    client: AsyncClient, session: AsyncSession
):
    """A device token does not record what was presented when it was minted, so
    the session it buys asserts nothing about that either."""
    user = await create_user(session, email="native-amr@example.com")
    device_token = await user_tokens.create_device_token(
        session, user_id=user.id, device_name="old-phone"
    )
    await session.commit()

    response = await client.post(
        "/api/v1/auth/device-token/exchange", json={"device_token": device_token}
    )
    assert response.status_code == 200, response.text

    claims = decode_session_token(response.json()["access_token"])
    assert not claims.get("amr")


async def test_a_session_that_cannot_be_opened_leaves_no_token_behind(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """Both credentials are minted on one transaction, so the refusal takes the
    device token with it. A token committed on its own would be live for its
    whole window, in the account's device list, and in nobody's hands."""
    from app.api.v1.platform_endpoints import auth as auth_module

    user = await create_user(session, email="native-atomic@example.com")
    # Read before anything expires it: the endpoint rolls back the session this
    # test shares with it, and a later attribute access would refresh lazily.
    user_id = user.id

    async def _no_session(*args, **kwargs):
        raise RuntimeError("session store is away")

    monkeypatch.setattr(auth_module.session_service, "create_session", _no_session)
    response = await client.post(
        "/api/v1/auth/device-token",
        json={
            "email": "native-atomic@example.com",
            "password": PASSWORD,
            "device_name": "test-phone",
        },
    )
    assert response.status_code == 503, response.text

    session.expire_all()
    left = (
        await session.exec(
            select(func.count())
            .select_from(UserToken)
            .where(
                UserToken.user_id == user_id,
                UserToken.purpose == UserTokenPurpose.device_auth,
            )
        )
    ).one()
    assert left == 0


async def test_an_exchange_is_not_counted_as_an_issue(
    client: AsyncClient, session: AsyncSession, capfd
):
    """Nothing was issued — the token already existed. The two are counted
    apart so one of them can read as movement onto the session path."""
    user = await create_user(session, email="native-counted@example.com")
    user_id = user.id
    device_token = await user_tokens.create_device_token(
        session, user_id=user_id, device_name="old-phone"
    )
    await session.commit()
    capfd.readouterr()

    response = await client.post(
        "/api/v1/auth/device-token/exchange", json={"device_token": device_token}
    )
    assert response.status_code == 200, response.text

    recorded = _events(capfd, user_id)
    assert AuditEventType.AUTH_DEVICE_TOKEN_EXCHANGED.value in recorded
    assert AuditEventType.AUTH_DEVICE_TOKEN_ISSUED.value not in recorded


async def test_an_unknown_device_token_buys_nothing(client: AsyncClient):
    response = await client.post(
        "/api/v1/auth/device-token/exchange", json={"device_token": "not-a-token"}
    )
    assert response.status_code == 401
