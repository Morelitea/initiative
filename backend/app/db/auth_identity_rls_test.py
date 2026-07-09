"""RLS / role-security tests for the auth identity foundation.

Locks in two deliberate least-privilege decisions (see the migration
20260705_0131 and history/auth-detailed-design.md §6):

* ``federated_identities`` is **own-row** on the request path — a platform tier
  sees only its own links, and there is NO admin-read-all policy (platform user
  management runs on the system engine, not the request path).
* ``auth_providers`` carries **no permissive policy and no request-path grant**,
  so the request role cannot read provider config at all — guild-scoped SSO
  metadata can never leak cross-tenant. Only ``app_admin`` (BYPASSRLS) reaches it.

Style mirrors ``platform_role_rls_test``: the ``session`` fixture connects as the
superuser, but ``SET ROLE platform_<tier>`` drops to a non-superuser role so RLS
and table GRANTs are enforced exactly like the production request path.
"""

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


async def _make_provider(session, slug: str) -> int:
    return (
        await session.exec(
            text(
                "INSERT INTO auth_providers "
                "(slug, display_name, kind, enabled, allow_jit, created_at, updated_at) "
                "VALUES (:s, :s, 'oidc', true, true, now(), now()) RETURNING id"
            ),
            params={"s": slug},
        )
    ).scalar_one()


async def _link(session, user_id: int, provider_id: int, subject: str) -> None:
    await session.exec(
        text(
            "INSERT INTO federated_identities "
            "(user_id, provider_id, subject, email_verified, created_at) "
            "VALUES (:u, :p, :sub, true, now())"
        ),
        params={"u": user_id, "p": provider_id, "sub": subject},
    )


async def test_federated_identity_is_own_row_on_request_path(session):
    provider = await _make_provider(session, "acme")
    u1 = await create_user(session)
    u2 = await create_user(session)
    await _link(session, u1.id, provider, "sub-1")
    await _link(session, u2.id, provider, "sub-2")

    await _assume(session, "member", u1.id)
    rows = {
        r[0]
        for r in (
            await session.exec(text("SELECT user_id FROM federated_identities"))
        ).fetchall()
    }
    await _reset(session)
    assert rows == {u1.id}, "a member must see only their own federated identities"


async def test_no_platform_tier_reads_all_identities(session):
    """No admin-read-all policy: even platform_admin sees only its own links on
    the request path — cross-user identity reads run on the system engine."""
    provider = await _make_provider(session, "acme2")
    u1 = await create_user(session)
    u2 = await create_user(session)
    await _link(session, u1.id, provider, "sub-a")
    await _link(session, u2.id, provider, "sub-b")

    await _assume(session, "admin", u1.id)
    rows = {
        r[0]
        for r in (
            await session.exec(text("SELECT user_id FROM federated_identities"))
        ).fetchall()
    }
    await _reset(session)
    assert rows == {u1.id}, (
        "platform_admin must not read-all identities via the request path"
    )


async def test_auth_providers_unreadable_on_request_path(session):
    """No permissive policy + no request-path grant: the request role cannot read
    provider config at all, so guild-scoped SSO metadata can't leak cross-tenant."""
    await _make_provider(session, "acme3")
    u1 = await create_user(session)

    await _assume(session, "owner", u1.id)
    with pytest.raises(DBAPIError):
        async with session.begin_nested():
            await session.exec(text("SELECT id FROM auth_providers"))
    await _reset(session)
