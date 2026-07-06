"""RLS / role-security test for the auth_sessions store.

Locks in the app_admin-only wall (migration 20260706_0132): the request path
cannot touch sessions at all, so the refresh-token hash never leaks. Session
validation is a pre-auth lookup by hash (user unknown) and so runs on the system
engine — there is deliberately no own-row request-path access.

Style mirrors ``platform_role_rls_test``: SET ROLE platform_<tier> drops to a
non-superuser role so RLS + table GRANTs are enforced like the request path.
"""

import hashlib

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.schema_provisioning import platform_role_name
from app.testing import create_user

pytestmark = [pytest.mark.integration, pytest.mark.database]


async def _assume(session, tier: str, user_id: int) -> None:
    await session.exec(
        text(
            "SELECT set_config('app.current_user_id', :uid, false), "
            "set_config('role', :role, false)"
        ),
        params={"uid": str(user_id), "role": platform_role_name(tier)},
    )


async def _reset(session) -> None:
    await session.exec(
        text(
            "SELECT set_config('role', 'none', false), "
            "set_config('app.current_user_id', '', false)"
        )
    )


async def _make_session_row(session, user_id: int, token: str) -> None:
    await session.exec(
        text(
            "INSERT INTO auth_sessions "
            "(user_id, refresh_token_hash, expires_at, created_at) "
            "VALUES (:u, :h, now() + interval '1 day', now())"
        ),
        params={"u": user_id, "h": hashlib.sha256(token.encode()).digest()},
    )


async def test_auth_sessions_unreadable_on_request_path(session):
    """No request-path grant: even the highest platform tier is denied at the
    grant layer, so the refresh-token hash can never be read off the request path.
    The superuser setup session (like the system engine) still sees the row."""
    u1 = await create_user(session)
    await _make_session_row(session, u1.id, "refresh-token-1")

    # Positive control: the privileged path sees the session it just wrote.
    seen = (await session.exec(text("SELECT count(*) FROM auth_sessions"))).scalar_one()
    assert seen >= 1

    await _assume(session, "owner", u1.id)
    with pytest.raises(DBAPIError):
        async with session.begin_nested():
            await session.exec(text("SELECT id FROM auth_sessions"))
    await _reset(session)
