"""The database-level grants the bootstrap applies.

The request path creates no temporary objects, so the bootstrap revokes the
TEMPORARY grant PUBLIC carries by default on a new database. The provisioning
role, which runs migrations, holds every database privilege by its own grant,
so a migration has the same rights whether or not that role owns the database.
Only a database's owner can change its ACL, so this belongs to
``app.db.bootstrap`` — which connects as the owner — rather than to a
migration, which runs as the provisioning role.

These assert against the module rather than a deployment file: the bootstrap is
the one place the statement lives now, and an operator's own compose file is
free to differ.
"""

from __future__ import annotations

from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.db.bootstrap import (
    PROVISIONER_DATABASE_PRIVILEGES,
    bootstrap_sql,
    login_roles,
)


_REVOKE = "REVOKE TEMPORARY ON DATABASE"


def test_the_bootstrap_revokes_it():
    assert _REVOKE in bootstrap_sql()


def test_the_revoke_is_verified_rather_than_assumed():
    """A REVOKE issued by a non-owner reports success and changes nothing, so
    the bootstrap reads the ACL back instead of trusting the exit."""
    body = bootstrap_sql()
    assert "aclexplode" in body
    assert "RAISE EXCEPTION" in body


def test_the_verification_follows_the_revoke():
    body = bootstrap_sql()
    assert body.index(_REVOKE) < body.index("aclexplode")


async def test_the_provisioner_holds_every_database_privilege_by_name(session):
    """Read from the ACL rather than ``has_database_privilege``, which would
    also count PUBLIC's grant and the owner's."""
    provisioner = login_roles()[0].name
    rows = await session.exec(
        text(
            "SELECT a.privilege_type FROM pg_database d,"
            " aclexplode(d.datacl) a"
            " WHERE d.datname = current_database()"
            " AND a.grantee = CAST(:role AS regrole)"
        ),
        params={"role": provisioner},
    )
    assert set(PROVISIONER_DATABASE_PRIVILEGES) <= {privilege for (privilege,) in rows}


async def test_the_provisioner_makes_a_temporary_table_without_public_s_grant():
    """The single-URL shape: the provisioning login does not own the database,
    and PUBLIC holds no TEMPORARY. A migration's temporary table still works."""
    from conftest import TEST_DATABASE_URL, TEST_DB_NAME

    owner = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    provisioner = create_async_engine(
        make_url(settings.DATABASE_URL).set(database=TEST_DB_NAME),
        poolclass=NullPool,
    )
    database = f'DATABASE "{TEST_DB_NAME}"'
    try:
        async with owner.begin() as conn:
            await conn.execute(text(f"REVOKE TEMPORARY ON {database} FROM PUBLIC"))
        try:
            async with provisioner.begin() as conn:
                assert not await conn.scalar(
                    text(
                        "SELECT datdba = CAST(session_user AS regrole)"
                        " FROM pg_database WHERE datname = current_database()"
                    )
                )
                await conn.execute(
                    text("CREATE TEMP TABLE _probe (x int) ON COMMIT DROP")
                )
        finally:
            async with owner.begin() as conn:
                await conn.execute(text(f"GRANT TEMPORARY ON {database} TO PUBLIC"))
    finally:
        await owner.dispose()
        await provisioner.dispose()
