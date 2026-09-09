"""What the per-guild query role can and cannot do.

The SQL query surface runs a reader's own statement, so the role it runs as is
the layer that does not depend on the validator being right. These assertions
*attempt* each operation and require an error, rather than reading a grant —
a grant can be read correctly and still not be the whole answer, because
ownership, defaults and PUBLIC all grant on their own.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.db.schema_provisioning import (
    drop_guild_schema,
    guild_query_role_name,
    guild_schema_name,
    provision_guild_schema,
)

pytestmark = pytest.mark.database

_GID = 990_140
_GID_OTHER = 990_141


@pytest.fixture
async def provisioned(engine):
    """Two provisioned guilds, so "another guild's schema" is a real place."""
    async with engine.begin() as conn:
        await provision_guild_schema(conn, _GID)
        await provision_guild_schema(conn, _GID_OTHER)
    try:
        yield guild_schema_name(_GID), guild_schema_name(_GID_OTHER)
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, _GID)
            await drop_guild_schema(conn, _GID_OTHER)


async def _as_query_role(conn, statement: str):
    """Run one statement as the query role, routed as a request would be.

    The search path matters: the initiative-RLS policies defer to
    ``public.initiative_access``, whose body names ``initiative_members``
    without a schema so it resolves against the caller's path — the guild's own
    membership table. Without the path the policy cannot be evaluated at all,
    which is a different failure from the one each test is about.
    """
    schema = guild_schema_name(_GID)
    await conn.exec_driver_sql(f'SET ROLE "{guild_query_role_name(_GID)}"')
    await conn.exec_driver_sql(f'SET search_path = "{schema}", public')
    try:
        return await conn.execute(text(statement))
    finally:
        await conn.rollback()
        await conn.exec_driver_sql("RESET ROLE")
        await conn.exec_driver_sql("RESET search_path")


async def test_it_can_read_its_own_schema(engine, provisioned):
    schema, _ = provisioned
    async with engine.connect() as conn:
        result = await _as_query_role(conn, f"SELECT count(*) FROM {schema}.tasks")
        assert result.scalar() == 0


async def test_initiative_rls_still_applies_to_it(engine, provisioned):
    """The policies read the request's identity, not its role, so a query runs
    under the same initiative scoping as any other read.

    ``projects`` is initiative-scoped; ``initiatives`` itself deliberately is
    not, being guild-scoped by the schema boundary. With no identity set the
    row-level answer is none — and the owning role seeing the row is what
    shows the difference is the policy rather than an empty table.
    """
    schema, _ = provisioned
    async with engine.begin() as conn:
        initiative_id = await conn.scalar(
            text(
                f"INSERT INTO {schema}.initiatives (name, guild_id, "
                "is_default, created_at, updated_at) "
                "VALUES ('i', :g, false, now(), now()) RETURNING id"
            ),
            {"g": _GID},
        )
        await conn.execute(
            text(
                f"INSERT INTO {schema}.projects (name, guild_id, initiative_id, "
                "is_archived, is_template, comments_enabled, "
                "created_at, updated_at) "
                "VALUES ('p', :g, :i, false, false, true, now(), now())"
            ),
            {"g": _GID, "i": initiative_id},
        )

    async with engine.connect() as conn:
        owner_sees = await conn.scalar(text(f"SELECT count(*) FROM {schema}.projects"))
        result = await _as_query_role(conn, f"SELECT count(*) FROM {schema}.projects")
        assert owner_sees == 1
        assert result.scalar() == 0


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO {schema}.tasks (title) VALUES ('x')",
        "UPDATE {schema}.tasks SET title = 'x'",
        "DELETE FROM {schema}.tasks",
        "TRUNCATE {schema}.tasks",
    ],
)
async def test_it_cannot_write(engine, provisioned, statement):
    """Refused by the role, before any policy is consulted."""
    schema, _ = provisioned
    async with engine.connect() as conn:
        with pytest.raises((ProgrammingError, DBAPIError)):
            await _as_query_role(conn, statement.format(schema=schema))


async def test_it_cannot_create_anything(engine, provisioned):
    schema, _ = provisioned
    async with engine.connect() as conn:
        with pytest.raises((ProgrammingError, DBAPIError)):
            await _as_query_role(conn, f"CREATE TABLE {schema}.evil (id int)")


async def test_it_cannot_read_another_guilds_schema(engine, provisioned):
    """The tenancy boundary, from the role's side: one guild's query role has
    no reach into another guild's schema at all."""
    _, other = provisioned
    async with engine.connect() as conn:
        with pytest.raises((ProgrammingError, DBAPIError)):
            await _as_query_role(conn, f"SELECT count(*) FROM {other}.tasks")


async def test_the_login_role_holds_no_standing_access(engine, provisioned):
    """Membership in the query role is granted WITH INHERIT FALSE, so reaching
    the schema takes an explicit SET ROLE rather than merely being the app."""
    schema, _ = provisioned
    role = guild_query_role_name(_GID)
    async with engine.connect() as conn:
        inherited = await conn.scalar(
            text(
                "SELECT pg_has_role(:login, :role, 'USAGE') "
                "AND NOT pg_has_role(:login, :role, 'MEMBER')"
            ),
            {"login": "app_user", "role": role},
        )
        # USAGE without MEMBER would mean standing access; the grant is the
        # other way round, so this is false.
        assert inherited is False


async def test_the_catalogs_are_readable_like_any_role(engine, provisioned):
    """PostgreSQL grants the system catalogs to PUBLIC, so this role reads
    names from them as every role does. Recorded rather than assumed: the
    catalogs are not where a query is kept away from other schemas — the
    validator is, resolving every relation through the field registry and
    refusing a schema-qualified name outright."""
    async with engine.connect() as conn:
        result = await _as_query_role(conn, "SELECT count(*) FROM pg_catalog.pg_class")
        assert result.scalar() > 0


@pytest.mark.parametrize(
    ("what", "statement"),
    [
        ("password hashes", "SELECT count(*) FROM pg_catalog.pg_authid"),
        ("raw column statistics", "SELECT count(*) FROM pg_catalog.pg_statistic"),
        ("the filesystem", "SELECT pg_read_file('/etc/hostname')"),
    ],
)
async def test_the_privileged_catalogs_stay_privileged(
    engine, provisioned, what, statement
):
    """Where the line actually falls. Reading catalog *names* is one thing;
    these are the parts PostgreSQL keeps for a superuser, and this role is not
    one."""
    async with engine.connect() as conn:
        with pytest.raises((ProgrammingError, DBAPIError)):
            await _as_query_role(conn, statement)


async def test_another_guilds_statistics_are_not_readable(engine, provisioned):
    """``pg_stats`` reports only columns the reader may select, so the value
    distributions of a schema this role cannot read are absent from it."""
    _, other = provisioned
    async with engine.connect() as conn:
        result = await _as_query_role(
            conn,
            "SELECT count(*) FROM pg_stats WHERE schemaname = :s".replace(
                ":s", f"'{other}'"
            ),
        )
        assert result.scalar() == 0
