"""Provision and tear down a per-guild PostgreSQL schema.

`provision_guild_schema` creates `guild_<id>` with every guild-scoped table
(from `app.db.tenancy.GUILD_SCOPED_TABLES`) plus a Postgres role scoped to that
schema; `drop_guild_schema` removes both. Idempotent. A building block for
schema-per-guild tenancy — not wired into the request path yet.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlmodel import SQLModel

from app.db import base  # noqa: F401  # ensure SQLModel.metadata holds every table
from app.db.tenancy import GUILD_SCOPED_TABLES


def guild_schema_name(guild_id: int) -> str:
    """Schema name for a guild, e.g. ``guild_42``."""
    return f"guild_{int(guild_id)}"


def guild_role_name(guild_id: int) -> str:
    """Role name for a guild, e.g. ``guild_42`` (separate namespace from the schema)."""
    return f"guild_{int(guild_id)}"


def _guild_scoped_tables() -> list:
    return [t for t in SQLModel.metadata.sorted_tables if t.name in GUILD_SCOPED_TABLES]


def _create_tables_in_schema(sync_conn: Connection, schema: str) -> None:
    # search_path puts new tables/enums in the guild schema while FKs to shared
    # tables resolve via public. checkfirst=False so it doesn't skip on seeing
    # the public copies through the search path.
    sync_conn.exec_driver_sql(f'SET search_path TO "{schema}", public')
    try:
        SQLModel.metadata.create_all(
            sync_conn, tables=_guild_scoped_tables(), checkfirst=False
        )
    finally:
        sync_conn.exec_driver_sql("SET search_path TO public")


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
    await conn.exec_driver_sql(
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "{schema}" TO "{role}"'
    )
    await conn.exec_driver_sql(
        f'GRANT USAGE ON ALL SEQUENCES IN SCHEMA "{schema}" TO "{role}"'
    )


async def provision_guild_schema(conn: AsyncConnection, guild_id: int) -> str:
    """Create ``guild_<id>`` (schema + tables + scoped role). Idempotent.

    Needs a privileged connection (CREATEROLE + CREATE on the database).
    """
    schema = guild_schema_name(guild_id)
    role = guild_role_name(guild_id)

    await conn.exec_driver_sql(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    await _ensure_role(conn, role)

    # Create tables only if missing; always (re)apply the idempotent grants.
    already = await conn.scalar(text("SELECT to_regclass(:rc)"), {"rc": f"{schema}.tasks"})
    if already is None:
        await conn.run_sync(_create_tables_in_schema, schema)

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
