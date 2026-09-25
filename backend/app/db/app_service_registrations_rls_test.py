"""Role-security test for the app service registry.

The table holds each app's shared-secret ciphertext and is written on the
system engine alone: the schema's default privileges are wound back,
``app_admin`` carries every verb, and no person's request-path role holds a
grant or a policy on it. The one other reader is the install floor, whose
standing statement reads four columns of the registration its token names.

Style mirrors ``auth_provider_secrets_rls_test``: ``SET ROLE platform_<tier>``
drops to a non-superuser role so table GRANTs and policies are enforced exactly
as they are on a real request.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.schema_provisioning import platform_role_name
from app.db.public_rls import PUBLIC_RLS, SELECT
from app.db.system_grants import (
    SHARED_TABLE_APP_USER_GRANTS,
    SHARED_TABLE_SYSTEM_GRANTS,
    SHARED_TABLE_TIER_GRANTS,
)
from app.models.platform.user import UserRole
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
            "INSERT INTO public.publishers (prefix, display_name, verified, enabled, "
            "created_at) VALUES ('acme', 'Acme', false, true, now()) "
            "ON CONFLICT (prefix) DO NOTHING"
        )
    )
    await session.exec(
        text(
            f"INSERT INTO {TABLE} "
            "(public_id, publisher_id, base_url, allowed_origins, grants, jwks, "
            " mandatory, enabled, created_at, updated_at) "
            "SELECT :pid, p.id, 'http://127.0.0.1:9100', '[]'::jsonb, '[]'::jsonb, "
            " '{\"keys\": []}'::jsonb, false, true, now(), now() "
            "FROM public.publishers p WHERE p.prefix = 'acme'"
        ),
        params={"pid": public_id},
    )


def test_registry_records_the_grant_decision():
    """The registries name this table for the system engine alone: it holds
    every verb, the bare pre-routing role and every tier hold nothing, and the
    one policy on the table is the install floor's read."""
    assert SHARED_TABLE_SYSTEM_GRANTS[TABLE] == frozenset(
        {"SELECT", "INSERT", "UPDATE", "DELETE"}
    )
    assert SHARED_TABLE_APP_USER_GRANTS[TABLE] is None
    assert TABLE not in SHARED_TABLE_TIER_GRANTS
    rls = PUBLIC_RLS[TABLE]
    assert rls.enabled and rls.forced
    assert [(p.command, p.roles) for p in rls.policies] == [
        (SELECT, ("app_install_base",))
    ]


async def test_no_platform_tier_reads_or_writes_registrations(session):
    """Every tier, the owner included, is refused at the grant layer."""
    user = await create_user(session)
    await _make_row(session)

    for tier in UserRole:
        for statement in (
            f"SELECT jwks FROM {TABLE}",
            f"UPDATE {TABLE} SET enabled = false",
            f"DELETE FROM {TABLE}",
        ):
            await _assume(session, tier.value, user.id)
            with pytest.raises(DBAPIError):
                async with session.begin_nested():
                    await session.exec(text(statement))
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
