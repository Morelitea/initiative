"""The dependencies a route resolves before it runs."""

import pytest
from starlette.requests import Request

from app.api.deps import get_current_active_user
from app.models.platform.user import User, UserStatus

pytestmark = [pytest.mark.unit, pytest.mark.auth]


def _request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": []})


async def test_the_request_is_told_whose_it_is():
    """Some things run before the endpoint does and have only the request to
    read — the per-account rate limit key among them — so the caller is put on
    it here."""
    request = _request()
    user = User(id=7, username="someone", discriminator=1234, status=UserStatus.active)

    assert await get_current_active_user(request, user) is user
    assert request.state.user_id == 7
