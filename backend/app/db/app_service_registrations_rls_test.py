"""Role-security test for the app service registry.

The table holds each app's shared-secret ciphertext, so it is denied to the
request path at the *grant* layer and not only by policy: the schema's default
privileges are wound back, ``app_admin`` (the system engine) carries the writes,
and the platform owner carries a SELECT-only policy so an admin screen can be
served role-scoped.

Style mirrors ``auth_provider_secrets_rls_test``: ``SET ROLE platform_<tier>``
drops to a non-superuser role so table GRANTs and policies are enforced exactly
as they are on a real request.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.schema_provisioning import platform_role_name
from app.db.system_grants import (
    SHARED_TABLE_APP_USER_GRANTS,
    SHARED_TABLE_SYSTEM_GRANTS,
)
from app.testing import create_user

pytestmark = [pytest.mark.integration, pytest.mark.database]

TABLE = "app_service_registrations"


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


async def _make_row(session, public_id: str = "acme.widgets") -> None:
    await session.exec(
        text(
            f"INSERT INTO {TABLE} "
            "(public_id, base_url, allowed_origins, secret_encrypted, grants, "
            " mandatory, enabled, status, created_at, updated_at) "
            "VALUES (:pid, 'http://127.0.0.1:9100', '[]'::jsonb, 'ciphertext', "
            " '[]'::jsonb, false, true, 'unverified', now(), now())"
        ),
        params={"pid": public_id},
    )


def test_registry_records_the_grant_decision():
    """The shared-table registry names this table for both login roles — the
    system engine writes it, the bare pre-routing role holds nothing."""
    assert SHARED_TABLE_SYSTEM_GRANTS[TABLE] == frozenset(
        {"SELECT", "INSERT", "UPDATE", "DELETE"}
    )
    assert SHARED_TABLE_APP_USER_GRANTS[TABLE] is None


async def test_lower_platform_tiers_cannot_read_registrations(session):
    """Only the owner tier holds a grant; every tier below is denied at the
    grant layer, before any policy is consulted."""
    user = await create_user(session)
    await _make_row(session)

    for tier in ("member", "support", "moderator", "operator"):
        await _assume(session, tier, user.id)
        with pytest.raises(DBAPIError):
            async with session.begin_nested():
                await session.exec(text(f"SELECT secret_encrypted FROM {TABLE}"))
        await _reset(session)


async def test_owner_reads_but_cannot_write_registrations(session):
    """The owner tier reads the registry under its SELECT policy; writing runs
    on the system engine, so the owner role holds no write grant."""
    user = await create_user(session)
    await _make_row(session, public_id="acme.readable")

    await _assume(session, "owner", user.id)
    seen = (
        await session.exec(
            text(f"SELECT count(*) FROM {TABLE} WHERE public_id = 'acme.readable'")
        )
    ).scalar_one()
    assert seen == 1

    with pytest.raises(DBAPIError):
        async with session.begin_nested():
            await session.exec(
                text(f"UPDATE {TABLE} SET enabled = false WHERE public_id = :pid"),
                params={"pid": "acme.readable"},
            )
    await _reset(session)

    await _assume(session, "owner", user.id)
    with pytest.raises(DBAPIError):
        async with session.begin_nested():
            await session.exec(text(f"DELETE FROM {TABLE}"))
    await _reset(session)


async def test_registrations_table_forces_rls(session):
    """FORCE keeps even the owning role policy-bound."""
    row = (
        await session.exec(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relnamespace = 'public'::regnamespace AND relname = :name"
            ),
            params={"name": TABLE},
        )
    ).one()
    assert row[0] is True, f"{TABLE} must have RLS enabled"
    assert row[1] is True, f"{TABLE} must FORCE RLS"
