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
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlmodel import SQLModel

from app.db import base  # noqa: F401  # ensure SQLModel.metadata holds every table
from app.db import session as db_session
from app.db.tenancy import GUILD_SCOPED_TABLES


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
    return md, guild_tables


def _create_tables(sync_conn: Connection, schema: str, names: set[str]) -> None:
    # public on the search path so unqualified enum types resolve to the shared
    # public types; checkfirst still guards (skips the shared enum types).
    sync_conn.exec_driver_sql("SET search_path TO public")
    md, guild_tables = _guild_metadata(schema)
    to_create = [t for t in guild_tables if t.name in names]
    md.create_all(sync_conn, tables=to_create, checkfirst=True)


async def _existing_tables(conn: AsyncConnection, schema: str) -> set[str]:
    rows = await conn.execute(
        text("SELECT table_name FROM information_schema.tables WHERE table_schema = :s"),
        {"s": schema},
    )
    return {row[0] for row in rows}


async def _role_exists(conn: AsyncConnection, role: str) -> bool:
    return (
        await conn.scalar(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role})
    ) is not None


async def _ensure_role(conn: AsyncConnection, role: str) -> None:
    if not await _role_exists(conn, role):
        await conn.exec_driver_sql(f'CREATE ROLE "{role}" NOLOGIN')


async def _grant_schema_to_role(conn: AsyncConnection, schema: str, role: str) -> None:
    # USAGE + DML on its own schema and nothing else — the guild boundary.
    await conn.exec_driver_sql(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"')
    # Default privileges cover objects created later; the explicit grants cover
    # what already exists (including tables back-filled by this same call).
    await conn.exec_driver_sql(
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" '
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{role}"'
    )
    await conn.exec_driver_sql(
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" GRANT USAGE ON SEQUENCES TO "{role}"'
    )
    await conn.exec_driver_sql(
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "{schema}" TO "{role}"'
    )
    await conn.exec_driver_sql(
        f'GRANT USAGE ON ALL SEQUENCES IN SCHEMA "{schema}" TO "{role}"'
    )


async def provision_guild_schema(conn: AsyncConnection, guild_id: int) -> str:
    """Create/refresh ``guild_<id>`` (schema + tables + scoped role). Idempotent.

    Needs a privileged connection (CREATEROLE + CREATE on the database). A
    re-run back-fills any newly-manifested tables and re-applies grants.
    """
    schema = guild_schema_name(guild_id)
    role = guild_role_name(guild_id)

    await conn.exec_driver_sql(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    await _ensure_role(conn, role)

    # One round-trip to find what's missing; skip the metadata build + per-table
    # checkfirst probes entirely when the schema is already complete (the common
    # re-provision case). Only newly-manifested tables get created.
    missing = {t.name for t in _guild_scoped_tables()} - await _existing_tables(conn, schema)
    if missing:
        await conn.run_sync(_create_tables, schema, missing)

    await _grant_schema_to_role(conn, schema, role)
    return schema


async def drop_guild_schema(conn: AsyncConnection, guild_id: int) -> None:
    """Drop ``guild_<id>`` (schema + role). Safe if either is already absent."""
    schema = guild_schema_name(guild_id)
    role = guild_role_name(guild_id)

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
