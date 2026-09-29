"""Role-security test for the auth_provider_secrets store.

Locks in the app_admin-only wall (migration 20260706_0133): the request path
holds no grant on the table, so a client secret can never be read off an
authenticated (``platform_<tier>``) request — even the highest tier is denied at
the grant layer. Secret reads/writes run only on the system engine (provider CRUD
via ``SystemSessionDep`` + ``config.manage``).

Style mirrors ``auth_sessions_rls_test``: SET ROLE platform_<tier> drops to a
non-superuser role so table GRANTs are enforced like the request path.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.schema_provisioning import platform_role_name
from app.testing import as_role, create_user


async def _make_secret_row(session) -> None:
    provider_id = (
        await session.exec(
            text(
                "INSERT INTO auth_providers "
                "(slug, display_name, kind, enabled, allow_jit, created_at, updated_at) "
                "VALUES ('oidc', 'SSO', 'oidc', true, true, now(), now()) RETURNING id"
            )
        )
    ).scalar_one()
    await session.exec(
        text(
            "INSERT INTO auth_provider_secrets "
            "(provider_id, client_secret_encrypted, created_at, updated_at) "
            "VALUES (:pid, 'ciphertext', now(), now())"
        ),
        params={"pid": provider_id},
    )


async def test_auth_provider_secrets_unreadable_on_request_path(session):
    """No request-path grant: even the highest platform tier is denied at the
    grant layer, so a client secret can never be read off the request path. The
    superuser setup session (like the system engine) still sees the row."""
    u1 = await create_user(session)
    await _make_secret_row(session)

    # Positive control: the privileged path sees the secret it just wrote.
    seen = (
        await session.exec(text("SELECT count(*) FROM auth_provider_secrets"))
    ).scalar_one()
    assert seen >= 1

    async with as_role(session, platform_role_name("owner"), u1.id):
        with pytest.raises(DBAPIError):
            async with session.begin_nested():
                await session.exec(
                    text("SELECT client_secret_encrypted FROM auth_provider_secrets")
                )
