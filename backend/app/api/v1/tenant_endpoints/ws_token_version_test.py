"""Regression test for SEC-4: token revocation on realtime channels.

Every realtime WebSocket endpoint reads its first frame's credential through
``authenticate_ws_token``. A session token minted before a ``token_version``
bump (logout / password reset / password change) is refused afterwards.
"""

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.platform.ws_auth import authenticate_ws_token
from app.testing import create_user, get_auth_token


async def test_ws_authenticator_accepts_valid_token(session: AsyncSession):
    user = await create_user(session)
    token = get_auth_token(user)

    result = await authenticate_ws_token(token, session)

    assert result is not None
    assert result.id == user.id


async def test_ws_authenticator_rejects_after_token_version_bump(
    session: AsyncSession,
):
    user = await create_user(session)
    token = get_auth_token(user)

    # The token works before revocation.
    assert await authenticate_ws_token(token, session) is not None

    # Logout / password reset / password change bump token_version.
    user.token_version += 1
    session.add(user)
    await session.commit()
    await session.refresh(user)

    assert await authenticate_ws_token(token, session) is None
