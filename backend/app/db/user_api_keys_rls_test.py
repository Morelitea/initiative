"""RLS / role-security test for the user_api_keys table.

Locks in the arrangement from migration 20260803_0156: ``user_api_keys`` has no
request-path grant and no policy, so request roles have no access to it — the
table is reached only on the system engine (the lookup is a pre-auth match by
``token_hash``, before the user is resolved). Asserts the request-path denial at
the DB layer.

Style mirrors ``auth_sessions_rls_test``: SET ROLE platform_<tier> drops to a
non-superuser role so RLS + table GRANTs are enforced like the request path.
"""

import hashlib

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.schema_provisioning import platform_role_name
from app.testing import as_role, create_user

pytestmark = [pytest.mark.integration, pytest.mark.database]


async def _make_key_row(session, user_id: int, token: str) -> None:
    await session.exec(
        text(
            "INSERT INTO user_api_keys "
            "(user_id, name, token_prefix, token_hash, is_active, "
            " read_only, created_at) "
            "VALUES (:u, 'k', :p, :h, true, false, now())"
        ),
        params={
            "u": user_id,
            "p": token[:12],
            "h": hashlib.sha256(token.encode()).hexdigest(),
        },
    )


async def test_user_api_keys_unreadable_on_request_path(session):
    """No request-path grant and no policy: every platform tier is denied at the
    DB layer, the key's own user included. The superuser setup session (like the
    system engine) still sees the row."""
    owner = await create_user(session)
    other = await create_user(session)
    await _make_key_row(session, owner.id, "ppk_secret-token-1")

    # Positive control: the privileged path sees the key it just wrote.
    seen = (await session.exec(text("SELECT count(*) FROM user_api_keys"))).scalar_one()
    assert seen >= 1

    # A different user, at the highest tier, is denied at the DB layer.
    async with as_role(session, platform_role_name("owner"), other.id):
        with pytest.raises(DBAPIError):
            async with session.begin_nested():
                await session.exec(text("SELECT token_hash FROM user_api_keys"))

    # The key's own user is denied too — the request path never touches this
    # table (auth resolves it on the system engine).
    async with as_role(session, platform_role_name("owner"), owner.id):
        with pytest.raises(DBAPIError):
            async with session.begin_nested():
                await session.exec(text("SELECT id FROM user_api_keys"))
