"""Provision and tear down a per-guild PostgreSQL schema.

`provision_guild_schema` creates `guild_<id>` with every guild-scoped table
(from `app.db.tenancy.GUILD_SCOPED_TABLES`) plus a Postgres role scoped to that
schema; `drop_guild_schema` removes both. Idempotent — re-running back-fills any
guild-scoped table added to the manifest since the schema was created. A
building block for schema-per-guild tenancy — not wired into the request path
yet.
"""

from __future__ import annotations

from sqlalchemy import MetaData, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.schema import CreateIndex, CreateTable
from sqlmodel import SQLModel

from app.core.config import settings
from app.db import base  # noqa: F401  # ensure SQLModel.metadata holds every table
from app.db import session as db_session
from app.db.tenancy import GUILD_SCOPED_TABLES

# The roles the app connects as must reach the guild schema, since per-request
# routing (search_path) sends guild-scoped queries there: app_user for the RLS
# request path, app_admin for guild creation / seeding / background jobs.
# (Tightening to per-guild roles + SET ROLE is the fail-closed step.)
APP_LOGIN_ROLE = make_url(settings.DATABASE_URL_APP).username
ADMIN_LOGIN_ROLE = make_url(settings.DATABASE_URL_ADMIN).username


def guild_schema_name(guild_id: int) -> str:
    """Schema name for a guild, e.g. ``guild_42``."""
    return f"guild_{int(guild_id)}"


def guild_role_name(guild_id: int) -> str:
    """Role name for a guild, e.g. ``guild_42`` (separate namespace from the schema)."""
    return f"guild_{int(guild_id)}"


def _guild_scoped_tables() -> list:
    return [t for t in SQLModel.metadata.sorted_tables if t.name in GUILD_SCOPED_TABLES]


# TODO(post-v1): once existing guilds have migrated and provisioning volume
# actually matters, consider cloning a prebuilt `guild_template` schema
# (pg_dump --schema | rename) instead of generating per-table DDL here — much
# faster at scale, but it doesn't cover back-fill, so keep this path for that.
def _guild_metadata(schema: str) -> tuple[MetaData, list]:
    """Build a schema-qualified copy of the model and the guild tables to create.

    Every table is copied so FK targets resolve: guild-scoped tables go to
    ``schema``, shared tables (and the named enum types) stay in ``public``. Only
    the guild-scoped copies are returned for creation. Being schema-explicit lets
    ``create_all(checkfirst=True)`` check existence in *this* schema (not via the
    search path, where the public copies would mask it) — which is what makes
    re-provisioning back-fill newly-added tables.
    """
    md = MetaData()

    def referred_schema_fn(table, to_schema, constraint, referred_schema):
        return schema if constraint.referred_table.name in GUILD_SCOPED_TABLES else None

    guild_tables = []
    for t in SQLModel.metadata.sorted_tables:
        is_guild = t.name in GUILD_SCOPED_TABLES
        copy = t.to_metadata(
            md, schema=(schema if is_guild else None), referred_schema_fn=referred_schema_fn
        )
        if is_guild:
            guild_tables.append(copy)
    # Strip cross-schema FKs in a second pass — after every table is in ``md`` so
    # each FK's referred_table resolves (intra-schema targets exist by now).
    for copy in guild_tables:
        _strip_cross_schema_fks(copy)
    return md, guild_tables


def _strip_cross_schema_fks(table) -> None:
    """Drop FK constraints from a guild table that reference a shared (public)
    table; keep intra-schema (guild -> guild) ones.

    In the schema-per-guild model the schema IS the tenant boundary, so a guild
    schema's references to shared tables (guilds, users, ...) are intentionally
    *soft* — no FK constraint. This keeps the columns but removes the constraint
    so that:
      - DROP SCHEMA (guild deletion) doesn't take locks on public.guilds/users
        (which the live app is constantly reading), and
      - deleting the guild row isn't blocked by the schema's NO ACTION FKs.
    """
    for fkc in list(table.foreign_key_constraints):
        if fkc.referred_table.name not in GUILD_SCOPED_TABLES:
            table.constraints.discard(fkc)
            for fk in list(fkc.elements):
                fk.parent.foreign_keys.discard(fk)


def _guild_schema_ddl(schema: str) -> str:
    """One batch of ``CREATE TABLE/INDEX IF NOT EXISTS`` for the guild schema.

    Built from the model so it always matches the manifest, and idempotent
    (``IF NOT EXISTS``) so a re-run back-fills any newly-manifested table. Enums
    are shared from public (``create_type=False`` — no per-schema type creation),
    so it must run with public on the search path. Returned as a single string
    to execute in one round-trip (per-statement round-trips are what made the
    old create_all path ~4x slower).
    """
    _, tables = _guild_metadata(schema)
    dialect = postgresql.dialect()
    stmts: list[str] = []
    for t in tables:
        for col in t.columns:
            if hasattr(col.type, "create_type"):
                col.type.create_type = False
        stmts.append(str(CreateTable(t, if_not_exists=True).compile(dialect=dialect)).strip())
        for idx in t.indexes:
            stmts.append(str(CreateIndex(idx, if_not_exists=True).compile(dialect=dialect)).strip())
    return ";\n".join(stmts) + ";"


def _grant_statements(schema: str) -> list[str]:
    """Fail-closed grants for a guild's schema.

    Only the per-guild role gets DML on the schema. It inherits shared/public
    access from ``app_guild_base``. The login roles are granted membership in the
    guild role ``WITH INHERIT FALSE`` — they can ``SET ROLE`` into it but hold no
    standing access to the schema, so a guild's data is reachable only by
    assuming its role.
    """
    role = schema  # the per-guild role shares the schema's name (guild_<id>)
    return [
        # The per-guild role owns DML on its schema...
        f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"',
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" '
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{role}"',
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" GRANT USAGE ON SEQUENCES TO "{role}"',
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "{schema}" TO "{role}"',
        f'GRANT USAGE ON ALL SEQUENCES IN SCHEMA "{schema}" TO "{role}"',
        # ...and inherits shared/public access (users, guilds, ...) from the base role.
        f'GRANT app_guild_base TO "{role}"',
        # The login roles may assume the guild role but inherit nothing from it.
        f'GRANT "{role}" TO "{APP_LOGIN_ROLE}", "{ADMIN_LOGIN_ROLE}" WITH INHERIT FALSE',
    ]


async def _exec_batch(conn: AsyncConnection, statements: list[str]) -> None:
    """Run many DDL/GRANT statements in a single round-trip.

    SQLAlchemy's exec_driver_sql uses asyncpg's extended (single-statement)
    protocol; dropping to the raw connection's simple-query path runs the whole
    batch at once, on the same (transactional) connection.
    """
    await conn.exec_driver_sql("SET search_path TO public")  # enums resolve in public
    raw = await conn.get_raw_connection()
    await raw.driver_connection.execute(";\n".join(statements) + ";")


async def _role_exists(conn: AsyncConnection, role: str) -> bool:
    return (
        await conn.scalar(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role})
    ) is not None


async def _ensure_role(conn: AsyncConnection, role: str) -> None:
    if not await _role_exists(conn, role):
        await conn.exec_driver_sql(f'CREATE ROLE "{role}" NOLOGIN')


async def provision_guild_schema(conn: AsyncConnection, guild_id: int) -> str:
    """Create/refresh ``guild_<id>`` (schema + tables + scoped role). Idempotent.

    Needs a privileged connection (CREATEROLE + CREATE on the database). The
    table DDL and grants run as a single round-trip; ``IF NOT EXISTS`` makes a
    re-run back-fill any newly-manifested table and re-apply grants harmlessly.
    """
    schema = guild_schema_name(guild_id)
    role = guild_role_name(guild_id)

    await conn.exec_driver_sql(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    await _ensure_role(conn, role)
    # Tables (IF NOT EXISTS) + grants, in one round-trip.
    await _exec_batch(conn, [_guild_schema_ddl(schema), *_grant_statements(schema)])
    return schema


async def drop_guild_schema(conn: AsyncConnection, guild_id: int) -> None:
    """Drop ``guild_<id>`` (schema + role). Safe if either is already absent."""
    schema = guild_schema_name(guild_id)
    role = guild_role_name(guild_id)

    # DROP SCHEMA needs an exclusive lock on the schema's tables (and on
    # public.guilds to drop their FKs); concurrent app sessions can hold it. Fail
    # fast rather than hang — the caller treats a failure as "retry later", and
    # this drop is idempotent so a retry recovers cleanly.
    await conn.exec_driver_sql("SET lock_timeout = '10s'")
    await conn.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    if await _role_exists(conn, role):
        await conn.exec_driver_sql(f'DROP OWNED BY "{role}"')  # clear grants first
        await conn.exec_driver_sql(f'DROP ROLE "{role}"')


async def provision_guild(guild_id: int) -> str:
    """Provision a guild's schema + role on the superuser engine, atomically.

    Opens its own transaction on the provisioning (superuser) engine — the
    request-path session can't run this DDL. Looked up via the module so tests
    can point it at the test database.
    """
    async with db_session.provisioning_engine.begin() as conn:
        return await provision_guild_schema(conn, guild_id)


async def deprovision_guild(guild_id: int) -> None:
    """Drop a guild's schema + role on the superuser engine."""
    async with db_session.provisioning_engine.begin() as conn:
        await drop_guild_schema(conn, guild_id)
