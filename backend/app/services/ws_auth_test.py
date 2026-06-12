"""Tests for the shared WebSocket auth helper (``authenticate_ws_token``).

Regression coverage for SEC-4: the realtime WebSocket authenticators must
honour ``token_version`` so that logout / password reset / password change
(which revoke purely by bumping the counter) also close realtime sockets.
"""

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.security import create_access_token
from app.models.user import UserStatus
from app.services import user_tokens
from app.services.ws_auth import authenticate_ws_token
from app.testing import create_user, get_auth_token

pytestmark = pytest.mark.asyncio


async def test_valid_token_authenticates(session: AsyncSession):
    user = await create_user(session)
    token = get_auth_token(user)

    result = await authenticate_ws_token(token, session)

    assert result is not None
    assert result.id == user.id


async def test_token_version_bump_revokes_token(session: AsyncSession):
    """A token minted at the old version must be rejected after the user's
    ``token_version`` is bumped (the logout / reset revocation mechanism)."""
    user = await create_user(session)
    token = get_auth_token(user)

    # Sanity: the freshly minted token works.
    assert await authenticate_ws_token(token, session) is not None

    # Logout / password reset / password change bumps the counter.
    user.token_version += 1
    session.add(user)
    await session.commit()
    await session.refresh(user)

    assert await authenticate_ws_token(token, session) is None


async def test_token_with_stale_version_claim_rejected(session: AsyncSession):
    """A token carrying an out-of-date ``ver`` (here 0 vs the user's 5) must
    never authenticate, even if the signature is otherwise valid."""
    user = await create_user(session)
    user.token_version = 5
    session.add(user)
    await session.commit()
    await session.refresh(user)

    stale_token = create_access_token(subject=str(user.id), token_version=0)

    assert await authenticate_ws_token(stale_token, session) is None


async def test_inactive_user_rejected(session: AsyncSession):
    user = await create_user(session, status=UserStatus.deactivated)
    token = get_auth_token(user)

    assert await authenticate_ws_token(token, session) is None


async def test_garbage_token_rejected(session: AsyncSession):
    assert await authenticate_ws_token("not-a-jwt", session) is None


async def test_device_token_still_authenticates(session: AsyncSession):
    """Device tokens are revoked separately (consumed / expired in the DB),
    not via ``token_version``; they must keep working through the helper."""
    user = await create_user(session)
    device_token = await user_tokens.create_device_token(
        session, user_id=user.id, device_name="pytest-device"
    )

    result = await authenticate_ws_token(device_token, session)

    assert result is not None
    assert result.id == user.id


async def test_token_without_version_claim_rejected(session: AsyncSession):
    """A valid-signature JWT with NO ``ver`` claim at all (e.g. a legacy token
    minted before versioning existed) exercises the ``ver is not None`` guard
    and must be rejected."""
    from datetime import datetime, timedelta, timezone

    import jwt as pyjwt

    from app.core.config import settings

    user = await create_user(session)
    legacy_token = pyjwt.encode(
        {
            "sub": str(user.id),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
        },
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )

    assert await authenticate_ws_token(legacy_token, session) is None


async def test_jwt_without_sub_does_not_fall_through_to_device_lookup(
    session: AsyncSession, monkeypatch
):
    """A valid-signature JWT carrying no ``sub`` is still a session token: it
    must be rejected outright, never re-interpreted as a device credential."""
    from datetime import datetime, timedelta, timezone

    import jwt as pyjwt

    from app.core.config import settings
    from app.services import ws_auth as ws_auth_module

    async def _must_not_be_called(*args, **kwargs):  # pragma: no cover
        raise AssertionError("device-token lookup must not run for a JWT bearer")

    monkeypatch.setattr(
        ws_auth_module.user_tokens, "get_device_token", _must_not_be_called
    )

    subless_token = pyjwt.encode(
        {"exp": datetime.now(timezone.utc) + timedelta(minutes=10)},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )

    assert await authenticate_ws_token(subless_token, session) is None
