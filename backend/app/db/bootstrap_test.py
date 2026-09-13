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


def _guc_keys(sql: str, call: str) -> set[str]:
    """The ``app._bootstrap_*`` settings ``sql`` names in ``call('<key>'``."""
    keys: set[str] = set()
    marker = f"{call}('app._bootstrap"
    start = 0
    while (opened := sql.find(marker, start)) != -1:
        key_at = opened + len(call) + 2
        closed = sql.index("'", key_at)
        keys.add(sql[key_at:closed])
        start = closed
    return keys


def test_the_printed_sql_sets_every_setting_it_reads():
    """``--print-sql`` has to run unattended.

    Its statements read their inputs from session settings, so each one has to
    be emitted alongside them; a statement whose setting is missing stops the
    script on ``unrecognized configuration parameter``.
    """
    body = bootstrap_sql()
    read = _guc_keys(body, "current_setting")
    written = _guc_keys(body, "set_config")
    assert read <= written, f"read but never set: {sorted(read - written)}"


def test_the_bootstrap_keeps_the_functions_it_installs():
    """The handover's exclusion list names functions the bootstrap creates.

    The two have to agree: a function the bootstrap re-asserts on every boot
    but hands away can no longer be replaced by the login doing the asserting.
    """
    from app.db.bootstrap import BOOTSTRAP_OWNED_FUNCTIONS

    installed = "\n".join(search_operator_sql())
    for name in BOOTSTRAP_OWNED_FUNCTIONS:
        assert f"public.{name}(" in installed, (
            f"{name} is excluded from the ownership handover but the bootstrap "
            f"does not install it"
        )


@pytest.mark.integration
async def test_the_handover_claims_every_function_the_outgoing_login_owns(session):
    """A database moved to the provisioning role hands over all of its own
    ``public`` functions, not only the ones a trigger or policy points at.

    A plpgsql body records no dependency on what it calls, so a helper reached
    only from another function's body — ``search_entry_write``, called from
    inside ``refresh_search_entry`` — looks unreferenced in the catalog. The
    probe below stands for one. Left behind, it keeps the outgoing owner and
    the next boot cannot replace it.

    A fresh database has nothing to hand over, which is why the probe is
    created here rather than looked for: this is the case CI never builds.
    """
    from sqlalchemy import text

    from app.db.bootstrap import _TRANSFER_STATEMENTS, BOOTSTRAP_OWNED_FUNCTIONS
    from app.db.system_grants import GRANTABLE_SHARED_TABLES
    from conftest import RUN_ID

    async def set_local(key: str, value: str) -> None:
        await session.exec(
            text("SELECT set_config(:k, :v, true)").bindparams(k=key, v=value)
        )

    probe = f"test_{RUN_ID}_unreferenced_helper"
    await session.exec(
        text(
            f"CREATE FUNCTION public.{probe}() RETURNS void "
            f"LANGUAGE plpgsql AS $probe$ BEGIN END $probe$"
        )
    )
    try:
        await set_local("app._bootstrap_role", "handover_target")
        await set_local(
            "app._bootstrap_tables", ",".join(sorted(GRANTABLE_SHARED_TABLES))
        )
        await set_local(
            "app._bootstrap_functions", ",".join(sorted(BOOTSTRAP_OWNED_FUNCTIONS))
        )

        claimed = {
            label.removeprefix("function ")
            for label, _stmt in (await session.exec(text(_TRANSFER_STATEMENTS))).all()
            if label.startswith("function ")
        }
        owned = {
            row[0]
            for row in (
                await session.exec(
                    text(
                        "SELECT p.oid::regprocedure::text FROM pg_proc p "
                        " WHERE p.pronamespace = 'public'::regnamespace "
                        "   AND p.proowner = current_user::regrole "
                        "   AND NOT p.proname = ANY(:kept) "
                        "   AND NOT EXISTS (SELECT 1 FROM pg_depend d "
                        "                    WHERE d.objid = p.oid AND d.deptype = 'e')"
                    ).bindparams(kept=list(BOOTSTRAP_OWNED_FUNCTIONS))
                )
            ).all()
        }

        assert f"{probe}()" in owned, "the probe did not land where the query looks"
        assert owned - claimed == set(), f"left behind: {sorted(owned - claimed)}"
    finally:
        await session.exec(text(f"DROP FUNCTION IF EXISTS public.{probe}()"))


@pytest.mark.integration
async def test_the_handover_leaves_the_bootstraps_own_functions_alone(session):
    """The match function is installed over the bootstrap connection and
    re-asserted from it on every boot, so it stays with that login."""
    from sqlalchemy import text

    from app.db.bootstrap import (
        _TRANSFER_STATEMENTS,
        BOOTSTRAP_OWNED_FUNCTIONS,
        SEARCH_MATCH_FUNCTION,
    )
    from app.db.system_grants import GRANTABLE_SHARED_TABLES

    async def set_local(key: str, value: str) -> None:
        await session.exec(
            text("SELECT set_config(:k, :v, true)").bindparams(k=key, v=value)
        )

    await set_local("app._bootstrap_role", "handover_target")
    await set_local("app._bootstrap_tables", ",".join(sorted(GRANTABLE_SHARED_TABLES)))
    await set_local(
        "app._bootstrap_functions", ",".join(sorted(BOOTSTRAP_OWNED_FUNCTIONS))
    )

    owner = (
        await session.exec(
            text(
                "SELECT pg_get_userbyid(p.proowner) = current_user FROM pg_proc p "
                " WHERE p.pronamespace = 'public'::regnamespace "
                "   AND p.proname = :match_fn"
            ).bindparams(match_fn=SEARCH_MATCH_FUNCTION)
        )
    ).first()
    assert owner is not None and owner[0], (
        f"{SEARCH_MATCH_FUNCTION} is not owned by this login, so this proves nothing"
    )

    labels = [
        label for label, _stmt in (await session.exec(text(_TRANSFER_STATEMENTS))).all()
    ]
    assert not any(SEARCH_MATCH_FUNCTION in label for label in labels)
