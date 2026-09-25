"""The session a native client is given, beside the device token it already had.

The device token is not going anywhere yet: an installed build keeps sending
one and keeps working. What these cover is the way across — a sign-in that
hands back a session as well, an exchange for the clients whose token arrived
by some other route, and a refresh that works without a cookie, because a
native client keeps its refresh token in the platform's secure storage rather
than in a jar the browser manages.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

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
    """A token minted by a sign-in that recorded nothing buys a session that
    says nothing either."""
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


# --- the handoff -------------------------------------------------------------


async def _exchange(client: AsyncClient, device_token: str) -> list[str]:
    """The ``amr`` of the session a device token is traded for."""
    response = await client.post(
        "/api/v1/auth/device-token/exchange", json={"device_token": device_token}
    )
    assert response.status_code == 200, response.text
    return decode_session_token(response.json()["access_token"]).get("amr") or []


async def _age(session: AsyncSession, *, token_id: int, by: timedelta) -> None:
    """Move a token's mint back, so a window can be reached without waiting."""
    row = await session.get(UserToken, token_id)
    assert row is not None
    row.created_at = datetime.now(timezone.utc) - by
    session.add(row)
    await session.commit()


async def test_the_handoff_carries_the_sign_in_across(
    client: AsyncClient, session: AsyncSession
):
    """The relay sign-in hands the app a token rather than a session, so the
    exchange right after it is the rest of that sign-in: what the ceremony
    proved is what the session records."""
    user = await create_user(session, email="native-handoff@example.com")
    device_token = await user_tokens.create_device_token(
        session, user_id=user.id, device_name="phone", amr=["hwk", "mfa"]
    )
    await session.commit()

    assert sorted(await _exchange(client, device_token)) == ["hwk", "mfa"]


async def test_the_handoff_is_taken_once(client: AsyncClient, session: AsyncSession):
    """Every exchange after the first is the app resuming on a string it has
    been keeping, which proves nothing new — so the key is not re-asserted."""
    user = await create_user(session, email="native-handoff-once@example.com")
    device_token = await user_tokens.create_device_token(
        session, user_id=user.id, device_name="phone", amr=["hwk", "mfa"]
    )
    await session.commit()

    assert sorted(await _exchange(client, device_token)) == ["hwk", "mfa"]
    assert await _exchange(client, device_token) == []

    # And the token itself still works: only what it says about the sign-in is
    # spent.
    still_there = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"DeviceToken {device_token}"}
    )
    assert still_there.status_code == 200


async def test_a_token_never_traded_stops_offering_the_sign_in(
    client: AsyncClient, session: AsyncSession
):
    """The markers travel with the handoff, and the handoff is the moment after
    the sign-in. A token that sat unexchanged past the window carries the
    account, not the ceremony."""
    user = await create_user(session, email="native-handoff-late@example.com")
    device_token = await user_tokens.create_device_token(
        session, user_id=user.id, device_name="phone", amr=["hwk", "mfa"]
    )
    await session.commit()
    row = (
        await session.exec(select(UserToken).where(UserToken.user_id == user.id))
    ).one()
    await _age(
        session,
        token_id=row.id,
        by=user_tokens.DEVICE_TOKEN_HANDOFF_WINDOW + timedelta(minutes=1),
    )

    assert await _exchange(client, device_token) == []


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


async def test_a_narrowed_session_narrows_every_token_the_app_is_handed(
    client: AsyncClient, session: AsyncSession
):
    """A session that ends sooner than the deployment's access-token lifetime
    ends its tokens with it, on the app's two ways in as on the browser's."""
    from app.services.platform import app_settings as app_settings_service

    row = await app_settings_service.get_app_settings(session)
    row.session_idle_minutes = 5
    session.add(row)
    user = await create_user(session, email="native-narrowed@example.com")
    device_token = await user_tokens.create_device_token(
        session, user_id=user.id, device_name="old-phone"
    )
    await session.commit()
    ceiling = timedelta(minutes=5).total_seconds()

    signed_in = await _sign_in_native(client, "native-narrowed@example.com")
    assert signed_in["expires_in"] <= ceiling

    exchanged = await client.post(
        "/api/v1/auth/device-token/exchange", json={"device_token": device_token}
    )
    assert exchanged.status_code == 200, exchanged.text
    claims = decode_session_token(exchanged.json()["access_token"])
    assert claims["exp"] - claims["iat"] <= ceiling
