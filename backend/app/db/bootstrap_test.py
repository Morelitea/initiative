"""The privileged bootstrap declares what the app's own logins cannot create.

The module is the single source for two things a deployment needs before the
app can connect as its least-privilege roles: the login roles themselves, and
the guild-search match operator. These cover what that SQL must contain and how
the roles are read from the connection URLs; ``search_operator_test`` covers the
objects actually landing in a database.
"""

from __future__ import annotations

import pytest

from app.db.bootstrap import (
    LoginRole,
    bootstrap_sql,
    login_roles,
    search_operator_sql,
)

pytestmark = pytest.mark.unit


def test_roles_come_from_the_connection_urls(monkeypatch):
    """A deployment is free to name its logins; the bootstrap maintains
    whichever ones the URLs actually connect as."""
    from app.core.config import settings

    monkeypatch.setattr(
        settings, "DATABASE_URL", "postgresql+asyncpg://prov:pw1@h:5432/d"
    )
    monkeypatch.setattr(
        settings, "DATABASE_URL_APP", "postgresql+asyncpg://req:pw2@h:5432/d"
    )
    monkeypatch.setattr(
        settings, "DATABASE_URL_ADMIN", "postgresql+asyncpg://sys:pw3@h:5432/d"
    )
    provisioner, app_login, system = login_roles()
    assert (provisioner.name, provisioner.password) == ("prov", "pw1")
    assert (app_login.name, app_login.password) == ("req", "pw2")
    assert (system.name, system.password) == ("sys", "pw3")


def test_role_attributes_are_the_documented_ones():
    provisioner, app_login, system = login_roles()
    assert "CREATEROLE" in provisioner.attributes
    assert "NOSUPERUSER" in provisioner.attributes
    assert "NOBYPASSRLS" in provisioner.attributes
    assert "NOINHERIT" in app_login.attributes
    assert "BYPASSRLS" in system.attributes


def test_a_url_without_credentials_falls_back_to_the_canonical_name(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "DATABASE_URL_APP", "postgresql+asyncpg://h/d")
    _provisioner, app_login, _system = login_roles()
    assert app_login.name == "app_user"
    assert app_login.password is None


def test_printed_sql_covers_both_halves():
    body = bootstrap_sql()
    # Roles, database and schema ownership.
    assert "CREATE" in body and "ALTER" in body
    assert "GRANT CREATE, CONNECT ON DATABASE" in body
    assert "ALTER SCHEMA public OWNER TO" in body
    assert "WITH ADMIN OPTION" in body
    # The search operator.
    assert "LEAKPROOF" in body
    assert "tsvector_search_ops" in body


def test_printed_sql_is_wrapped_in_one_transaction():
    body = bootstrap_sql()
    assert body.startswith("--")
    assert "\nBEGIN;\n" in body
    assert body.rstrip().endswith("COMMIT;")


def test_the_match_function_is_declared_leakproof():
    """Postgres accepts the attribute only from a superuser, and the planner
    needs it to use the index here."""
    statements = search_operator_sql()
    function = next(s for s in statements if "CREATE OR REPLACE FUNCTION" in s)
    assert "LEAKPROOF" in function
    assert "LANGUAGE plpgsql" in function


def test_the_stock_operator_is_not_touched():
    joined = "\n".join(search_operator_sql())
    assert "public.@@@" in joined
    assert "CREATE OPERATOR pg_catalog" not in joined


def test_a_role_that_is_already_a_superuser_keeps_what_it_has():
    """The provisioner's shape is applied to an existing superuser without the
    clauses that would take privileges off it.

    An install predating ``app_provisioner`` names the same role in
    ``DATABASE_URL`` and ``DATABASE_URL_BOOTSTRAP`` — the cluster's own
    bootstrap role, which Postgres will not let anyone demote.
    """
    provisioner, _app_login, _system = login_roles()
    kept = provisioner.attributes_if_superuser.split()
    assert kept == ["LOGIN", "CREATEROLE"]


def test_the_printed_sql_carries_both_shapes():
    """``--print-sql`` runs the same statements, so it needs the same settings."""
    body = bootstrap_sql()
    assert body.count("set_config('app._bootstrap_attrs'") == 3
    assert body.count("set_config('app._bootstrap_attrs_superuser'") == 3


@pytest.mark.integration
@pytest.mark.parametrize(
    ("created_with", "attribute", "expected"),
    [
        # An install predating app_provisioner names one role in both
        # DATABASE_URL and DATABASE_URL_BOOTSTRAP — the cluster's own bootstrap
        # role, which Postgres will not let anyone demote.
        ("SUPERUSER", "rolsuper", True),
        # The counterpart: an ordinary role still converges on the shape, so a
        # provisioner created with more than it needs gives it up.
        ("BYPASSRLS", "rolbypassrls", False),
    ],
)
async def test_the_provisioner_shape_on_an_existing_role(
    created_with, attribute, expected
):
    """What applying the provisioner's attributes does to a role that is
    already there, by what that role already holds."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from app.db.bootstrap import _ensure_role
    from conftest import RUN_ID, TEST_DATABASE_URL

    # Roles are cluster-global; key the probe to this run so concurrent
    # checkouts and xdist workers never drop each other's.
    name = f"test_{RUN_ID}_probe_{created_with.lower()}"
    provisioner, _app_login, _system = login_roles()
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP ROLE IF EXISTS "{name}"'))
            await conn.execute(text(f'CREATE ROLE "{name}" {created_with}'))
        try:
            async with engine.begin() as conn:
                await _ensure_role(conn, LoginRole(name, None, provisioner.attributes))
                held = await conn.scalar(
                    text(f"SELECT {attribute} FROM pg_roles WHERE rolname = :n"),
                    {"n": name},
                )
            assert held is expected
        finally:
            async with engine.begin() as conn:
                await conn.execute(text(f'DROP ROLE IF EXISTS "{name}"'))
    finally:
        await engine.dispose()
