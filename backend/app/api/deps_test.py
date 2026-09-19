"""The dependencies a route resolves before it runs."""

import pytest
from starlette.requests import Request

from app.api.deps import get_active_user_exempt_from_factor
from app.models.platform.user import User, UserStatus

pytestmark = [pytest.mark.unit, pytest.mark.auth]


def _request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": []})


async def test_the_request_is_told_whose_it_is():
    """Some things run before the endpoint does and have only the request to
    read — the per-account rate limit key among them — so the caller is put on
    it here.

    Asked of the exempt dependency because it needs no database: both it and
    ``get_current_active_user`` resolve the caller through the same body, and
    this is that body's job."""
    request = _request()
    user = User(id=7, username="someone", discriminator=1234, status=UserStatus.active)

    assert await get_active_user_exempt_from_factor(request, user) is user
    assert request.state.user_id == 7
