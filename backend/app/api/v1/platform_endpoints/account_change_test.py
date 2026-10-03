"""Answering an account letter: "This wasn't me".

The link reads without spending, and signs the account out everywhere once,
on a token of its own purpose that is still good.
"""

from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.auth_session import AuthSession
from app.models.platform.user import User
from app.models.platform.user_token import UserTokenPurpose
from app.services.auth import sessions as session_service
from app.services.platform import user_tokens
from app.testing import create_user

READ = "/api/v1/auth/account-change/read"
SIGN_OUT = "/api/v1/auth/account-change/sign-out"


async def _link(
    session: AsyncSession,
    user: User,
    *,
    purpose: UserTokenPurpose = UserTokenPurpose.account_change,
    minutes: int = 60,
) -> str:
    return await user_tokens.create_token(
        session,
        user_id=user.id,
        purpose=purpose,
        expires_minutes=minutes,
        change={"notice": "passkey.added", "recipient": "hash"},
    )


async def test_reading_a_link_says_what_it_answers_and_spends_nothing(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="reads@example.com")
    token = await _link(session, user)

    for _ in range(2):
        response = await client.post(READ, json={"token": token})
        assert response.status_code == 200, response.text
        assert response.json() == {"notice": "passkey.added"}

    assert (await client.post(SIGN_OUT, json={"token": token})).status_code == 200


async def test_a_link_signs_the_account_out_everywhere_once(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="not-me@example.com")
    user_id, version = user.id, user.token_version
    opened = await session_service.create_session(
        session, user_id=user_id, amr=["pwd"], satisfied_providers=[]
    )
    session_id = opened.session.id
    await session.commit()
    token = await _link(session, user)

    response = await client.post(SIGN_OUT, json={"token": token})
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "signed_out"}

    session.expire_all()
    assert (await session.get(User, user_id)).token_version == version + 1
    assert (await session.get(AuthSession, session_id)).revoked_at is not None

    again = await client.post(SIGN_OUT, json={"token": token})
    assert again.status_code == 400
    assert again.json()["detail"] == "INVALID_OR_EXPIRED_TOKEN"


async def test_only_a_live_link_of_its_own_purpose_answers(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="stale@example.com")
    expired = await _link(session, user, minutes=-1)
    reset = await _link(session, user, purpose=UserTokenPurpose.password_reset)

    for token in (expired, reset):
        for route in (READ, SIGN_OUT):
            response = await client.post(route, json={"token": token})
            assert response.status_code == 400, response.text
            assert response.json()["detail"] == "INVALID_OR_EXPIRED_TOKEN"
