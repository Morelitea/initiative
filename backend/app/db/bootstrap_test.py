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
