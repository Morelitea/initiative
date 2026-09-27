"""Integration tests for /api/v1/push token registration.

These run through the real-role ``client`` (bare ``app_user`` login +
``SET ROLE platform_<tier>``), guarding the 0.54.0 regression where the
endpoints ran as the de-granted bare login role and failed with
``permission denied for table push_tokens``.
"""

from __future__ import annotations

from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.auth import sessions as session_service
from app.services.platform import push_tokens as push_tokens_service
from app.testing.factories import create_user, get_auth_headers, get_auth_token


async def test_register_and_unregister_push_token(
    client: AsyncClient, session: AsyncSession
):
    """The device is recorded against the session that registered it."""
    user = await create_user(session)
    signed_in = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[]
    )
    session_id = signed_in.session.id
    await session.commit()
    headers = {
        "Authorization": "Bearer "
        + get_auth_token(user, session_id=session_id, amr=["pwd"])
    }

    register = await client.post(
        "/api/v1/push/register",
        headers=headers,
        json={"push_token": "test-push-token-abc", "platform": "android"},
    )
    assert register.status_code == 200
    assert register.json() == {"status": "registered"}
    (row,) = await push_tokens_service.get_push_tokens_for_user(
        session, user_id=user.id
    )
    await session.refresh(row)
    assert row.session_id == session_id

    unregister = await client.request(
        "DELETE",
        "/api/v1/push/unregister",
        headers=headers,
        json={"push_token": "test-push-token-abc"},
    )
    assert unregister.status_code == 200
    assert unregister.json() == {"status": "unregistered"}


async def test_unregister_cannot_delete_other_users_token(
    client: AsyncClient, session: AsyncSession
):
    owner = await create_user(session)
    attacker = await create_user(session)
    token_value = "owner-push-token-xyz"

    register = await client.post(
        "/api/v1/push/register",
        headers=get_auth_headers(owner),
        json={"push_token": token_value, "platform": "ios"},
    )
    assert register.status_code == 200

    # A different authenticated user who learned the token value must not be
    # able to silence the owner's device.
    await client.request(
        "DELETE",
        "/api/v1/push/unregister",
        headers=get_auth_headers(attacker),
        json={"push_token": token_value},
    )

    remaining = await push_tokens_service.get_push_tokens_for_user(
        session, user_id=owner.id
    )
    assert [t.push_token for t in remaining] == [token_value]


async def test_a_traded_device_token_hands_its_device_to_the_session(
    client: AsyncClient, session: AsyncSession
):
    """Registered under a device token and then traded for a session, the
    device stands while that session does."""
    from app.services.platform import user_tokens

    user = await create_user(session)
    user_id = user.id
    device_token = await user_tokens.create_device_token(
        session, user_id=user_id, device_name="Phone"
    )
    await session.commit()
    register = await client.post(
        "/api/v1/push/register",
        headers={"Authorization": f"DeviceToken {device_token}"},
        json={"push_token": "phone-token", "platform": "android"},
    )
    assert register.status_code == 200, register.text

    exchanged = await client.post(
        "/api/v1/auth/device-token/exchange", json={"device_token": device_token}
    )
    assert exchanged.status_code == 200, exchanged.text

    (row,) = await push_tokens_service.get_push_tokens_for_user(
        session, user_id=user_id
    )
    await session.refresh(row)
    assert row.device_token_id is None
    assert row.session_id is not None
