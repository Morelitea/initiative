"""Tests for per-guild schema provisioning.

Use a synthetic, high guild id so the temporary ``guild_<id>`` schema can't
collide with real data, and drop it in teardown. Runs against the test DB as
the owning role (the ``engine`` fixture), which has DDL privileges.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.db.schema_provisioning import (
    drop_guild_schema,
    guild_role_name,
    guild_schema_name,
    provision_guild_schema,
)
from app.db.tenancy import GUILD_SCOPED_TABLES

pytestmark = pytest.mark.database

# Synthetic ids well above any real guild; each test uses its own.
_GID_COMPLETE = 990_101
_GID_ISOLATION = 990_102
_GID_IDEMPOTENT = 990_103
_GID_ROLE_A = 990_104
_GID_ROLE_B = 990_105
_GID_ROLE_DROP = 990_106
_GID_ROLE_WRITE = 990_107
_GID_BACKFILL = 990_108
_GID_REPROVISION = 990_109
_GID_DROP_ABSENT = 990_110


async def _insert_public_guild(conn, gid: int, name: str) -> None:
    """Insert a public.guilds row so guild-scoped FKs (-> public.guilds) hold."""
    await conn.execute(
        text(
            "INSERT INTO public.guilds (id, name, created_at, updated_at) "
            "VALUES (:id, :n, now(), now())"
        ),
        {"id": gid, "n": name},
    )


async def test_provision_creates_every_guild_scoped_table(engine):
    schema = guild_schema_name(_GID_COMPLETE)
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, _GID_COMPLETE)
        async with engine.connect() as conn:
            res = await conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = :s"
                ),
                {"s": schema},
            )
            created = {row[0] for row in res}
        assert created == set(GUILD_SCOPED_TABLES)
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, _GID_COMPLETE)


async def test_writes_route_to_guild_schema_not_public(engine):
    """A row inserted under the guild schema lands there, not in public."""
    gid = _GID_ISOLATION
    schema = guild_schema_name(gid)
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, gid)
            await _insert_public_guild(conn, gid, "provision-iso-test")
            # Same unqualified INSERT, but routed via the guild search_path.
            await conn.exec_driver_sql(f'SET search_path TO "{schema}", public')
            # 9-char alpha color also exercises the widened tags.color column.
            await conn.execute(
                text(
                    "INSERT INTO tags (guild_id, name, color, created_at, updated_at) "
                    "VALUES (:g, :n, '#abcdef80', now(), now())"
                ),
                {"g": gid, "n": "iso-tag"},
            )
            await conn.exec_driver_sql("SET search_path TO public")

            in_guild = await conn.scalar(text(f'SELECT count(*) FROM "{schema}".tags'))
            in_public = await conn.scalar(
                text("SELECT count(*) FROM public.tags WHERE guild_id = :g"), {"g": gid}
            )
        assert in_guild == 1, "row should be in the guild schema"
        assert in_public == 0, "row must NOT leak into public.tags"
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, gid)
            await conn.execute(
                text("DELETE FROM public.guilds WHERE id = :id"), {"id": gid}
            )


async def test_provision_is_idempotent(engine):
    """Calling provision twice is a no-op, not an error."""
    gid = _GID_IDEMPOTENT
    schema = guild_schema_name(gid)
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, gid)
            await provision_guild_schema(conn, gid)  # must not raise
        async with engine.connect() as conn:
            count = await conn.scalar(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema = :s"
                ),
                {"s": schema},
            )
        assert count == len(GUILD_SCOPED_TABLES)
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, gid)


async def test_guild_role_is_scoped_to_its_own_schema(engine):
    """The per-guild role can reach its own schema but is denied another's.

    This is the fail-closed boundary: Postgres denies a role access to any
    schema it lacks USAGE on, *before* any RLS evaluates.
    """
    a, b = _GID_ROLE_A, _GID_ROLE_B
    role_a = guild_role_name(a)
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, a)
            await provision_guild_schema(conn, b)

        # Assuming guild A's role, its own schema is readable.
        async with engine.connect() as conn:
            await conn.exec_driver_sql(f'SET ROLE "{role_a}"')
            own = await conn.scalar(
                text(f'SELECT count(*) FROM "{guild_schema_name(a)}".tags')
            )
            await conn.exec_driver_sql("RESET ROLE")
        assert own == 0

        # ...but guild B's schema is denied at the catalog layer.
        async with engine.connect() as conn:
            await conn.exec_driver_sql(f'SET ROLE "{role_a}"')
            with pytest.raises(ProgrammingError) as exc:
                await conn.scalar(
                    text(f'SELECT count(*) FROM "{guild_schema_name(b)}".tags')
                )
            assert "permission denied" in str(exc.value).lower()
            await conn.rollback()  # clear the aborted txn before resetting role
            await conn.exec_driver_sql("RESET ROLE")
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, a)
            await drop_guild_schema(conn, b)


async def test_drop_guild_schema_removes_role(engine):
    """Tearing down a guild drops its role too, not just the schema."""
    gid = _GID_ROLE_DROP
    role = guild_role_name(gid)
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, gid)
        async with engine.connect() as conn:
            before = await conn.scalar(
                text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}
            )
        async with engine.begin() as conn:
            await drop_guild_schema(conn, gid)
        async with engine.connect() as conn:
            after = await conn.scalar(
                text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}
            )
        assert before == 1, "role should exist after provisioning"
        assert after is None, "role should be gone after drop"
    finally:
        # Defensive: ensure no leftover role/schema if an assertion failed early.
        async with engine.begin() as conn:
            await drop_guild_schema(conn, gid)


async def test_guild_role_can_write_in_its_own_schema(engine):
    """The role's DML grant actually works — it can INSERT, not just SELECT."""
    gid = _GID_ROLE_WRITE
    schema = guild_schema_name(gid)
    role = guild_role_name(gid)
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, gid)
            await _insert_public_guild(conn, gid, "role-write")
        async with engine.begin() as conn:
            await conn.exec_driver_sql(f'SET ROLE "{role}"')
            await conn.exec_driver_sql(f'SET search_path TO "{schema}", public')
            await conn.execute(
                text(
                    "INSERT INTO tags (guild_id, name, color, created_at, updated_at) "
                    "VALUES (:g, :n, '#112233', now(), now())"
                ),
                {"g": gid, "n": "written-by-role"},
            )
            written = await conn.scalar(text("SELECT count(*) FROM tags"))
            await conn.exec_driver_sql("SET search_path TO public")
            await conn.exec_driver_sql("RESET ROLE")
        assert written == 1
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, gid)
            await conn.execute(text("DELETE FROM public.guilds WHERE id = :id"), {"id": gid})


async def test_reprovision_backfills_missing_tables_with_grants(engine):
    """Re-provisioning recreates a table missing from the schema and grants it.

    Stands in for "a new guild-scoped table was added to the manifest": the
    table is absent from an existing schema, and a re-provision must create it
    *and* extend the role's access to it.
    """
    gid = _GID_BACKFILL
    schema = guild_schema_name(gid)
    role = guild_role_name(gid)
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, gid)
            # Simulate a table that didn't exist when the schema was first made.
            await conn.exec_driver_sql(f'DROP TABLE "{schema}".subtasks CASCADE')

        async with engine.connect() as conn:
            gone = await conn.scalar(text(f"SELECT to_regclass('{schema}.subtasks')"))
        assert gone is None, "precondition: subtasks dropped"

        async with engine.begin() as conn:
            await provision_guild_schema(conn, gid)  # back-fill

        async with engine.connect() as conn:
            recreated = await conn.scalar(text(f"SELECT to_regclass('{schema}.subtasks')"))
            # and the role's grant reaches the back-filled table
            await conn.exec_driver_sql(f'SET ROLE "{role}"')
            readable = await conn.scalar(text(f'SELECT count(*) FROM "{schema}".subtasks'))
            await conn.exec_driver_sql("RESET ROLE")
        assert recreated is not None, "subtasks should be back-filled"
        assert readable == 0, "role should be able to read the back-filled table"
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, gid)


async def test_reprovision_preserves_existing_rows(engine):
    """Idempotency must not wipe data: a second provision keeps existing rows."""
    gid = _GID_REPROVISION
    schema = guild_schema_name(gid)
    try:
        async with engine.begin() as conn:
            await provision_guild_schema(conn, gid)
            await _insert_public_guild(conn, gid, "reprovision")
            await conn.exec_driver_sql(f'SET search_path TO "{schema}", public')
            await conn.execute(
                text(
                    "INSERT INTO tags (guild_id, name, color, created_at, updated_at) "
                    "VALUES (:g, :n, '#445566', now(), now())"
                ),
                {"g": gid, "n": "survivor"},
            )
            await conn.exec_driver_sql("SET search_path TO public")
        async with engine.begin() as conn:
            await provision_guild_schema(conn, gid)  # second time
        async with engine.connect() as conn:
            count = await conn.scalar(text(f'SELECT count(*) FROM "{schema}".tags'))
        assert count == 1, "existing row must survive a re-provision"
    finally:
        async with engine.begin() as conn:
            await drop_guild_schema(conn, gid)
            await conn.execute(text("DELETE FROM public.guilds WHERE id = :id"), {"id": gid})


async def test_drop_guild_schema_is_safe_when_absent(engine):
    """Dropping a guild that was never provisioned is a no-op, not an error."""
    async with engine.begin() as conn:
        await drop_guild_schema(conn, _GID_DROP_ABSENT)  # must not raise
