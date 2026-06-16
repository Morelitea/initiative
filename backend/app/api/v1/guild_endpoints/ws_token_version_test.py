"""Regression test for SEC-4: token revocation on realtime channels.

Each of the four realtime WebSocket endpoints authenticates its first
message through an endpoint-local wrapper that delegates to the shared
``authenticate_ws_token`` helper. This test parametrizes across all four
wrappers and asserts that a session JWT minted before a ``token_version``
bump (logout / password reset / password change) is rejected afterwards —
the acceptance criterion is that the old token is rejected by *every* WS
endpoint.
"""

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.v1.guild_endpoints.collaboration import (
    _get_user_from_token as collaboration_authenticate,
)
from app.api.v1.guild_endpoints.counters import (
    _ws_authenticate as counters_authenticate,
)
from app.api.v1.guild_endpoints.events import _user_from_token as events_authenticate
from app.api.v1.guild_endpoints.queues import _ws_authenticate as queues_authenticate
from app.testing import create_user, get_auth_token

pytestmark = pytest.mark.asyncio

# Each entry is the endpoint-local WS authenticator under test.
WS_AUTHENTICATORS = [
    pytest.param(events_authenticate, id="events"),
    pytest.param(counters_authenticate, id="counters"),
    pytest.param(queues_authenticate, id="queues"),
    pytest.param(collaboration_authenticate, id="collaboration"),
]


@pytest.mark.parametrize("authenticate", WS_AUTHENTICATORS)
async def test_ws_authenticator_accepts_valid_token(
    authenticate, session: AsyncSession
):
    user = await create_user(session)
    token = get_auth_token(user)

    result = await authenticate(token, session)

    assert result is not None
    assert result.id == user.id


@pytest.mark.parametrize("authenticate", WS_AUTHENTICATORS)
async def test_ws_authenticator_rejects_after_token_version_bump(
    authenticate, session: AsyncSession
):
    user = await create_user(session)
    token = get_auth_token(user)

    # The token works before revocation.
    assert await authenticate(token, session) is not None

    # Logout / password reset / password change bump token_version.
    user.token_version += 1
    session.add(user)
    await session.commit()
    await session.refresh(user)

    # The stolen-but-unexpired token must now be rejected by every endpoint.
    assert await authenticate(token, session) is None
