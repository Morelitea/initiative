"""Provision and tear down a per-guild PostgreSQL schema.

`provision_guild_schema` creates `guild_<id>` (tables via `apply_guild_schema`,
which RUNS the canonical Alembic-owned DDL in `alembic/guild/guild_schema.sql`)
plus per-guild Postgres roles; `drop_guild_schema` removes both. Idempotent —
re-running back-fills any guild-scoped table a later migration added. The model
is never used to build the DB: Alembic is the single source, applied per schema.
Per-request routing (search_path + SET ROLE in `set_rls_context`) sends
guild-scoped queries into the schema.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import settings
from app.db import session as db_session

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
    """Cluster-global role name for a guild, e.g. ``guild_42``.

    Carries ``settings.GUILD_ROLE_PREFIX`` (empty in prod/dev). Roles are
    cluster-global — unlike schemas, which are per-database — so the test suite
    sets a prefix (``test_``) to avoid colliding with a co-located dev DB's roles.
    Deliberately a separate name from the schema: a role and a schema are
    different objects with different collision scopes.
    """
    return f"{settings.GUILD_ROLE_PREFIX}guild_{int(guild_id)}"


def guild_readonly_role_name(guild_id: int) -> str:
    """Read-only role for a guild, e.g. ``guild_42_ro``.

    Assumed by PAM *read* grants: SELECT-only on the schema, so a write is denied
    at the role level — unlike the full guild role used for membership/writes.
    """
    return f"{settings.GUILD_ROLE_PREFIX}guild_{int(guild_id)}_ro"


# The single source for a guild schema's structure: schema-relative DDL generated
# from the public tables Alembic builds (regenerate with scripts/gen_guild_schema.py
# after any guild-scoped migration). The model is never used to build the DB.
GUILD_SCHEMA_SQL_PATH = (
    Path(__file__).resolve().parents[2] / "alembic" / "guild" / "guild_schema.sql"
)


async def apply_guild_schema(conn: AsyncConnection, schema: str) -> None:
    """Build/refresh ``schema``'s guild-scoped tables by RUNNING the canonical,
    Alembic-owned DDL with the search_path pointed at it.

    The same DDL builds ``guild_template`` (a migration) and every ``guild_<id>``
    (provisioning) — one source of truth, applied per schema. It's schema-relative
    (unqualified names resolve in ``schema``; shared types/tables fall through to
    ``public``) and idempotent (``IF NOT EXISTS`` / guarded constraints), so a
    re-run back-fills anything a later migration added. No model, no clone.
    """
    ddl = GUILD_SCHEMA_SQL_PATH.read_text()
    raw = await conn.get_raw_connection()
    # search_path so unqualified CREATEs land in the schema and intra-schema FKs
    # resolve there; reset to public so it doesn't leak onto the pooled connection.
    await raw.driver_connection.execute(
        f'SET search_path TO "{schema}", public;\n{ddl}\nSET search_path TO public;'
    )


def _grant_statements(schema: str, role: str, ro_role: str) -> list[str]:
    """Fail-closed grants tying a guild ``role`` (read/write) and ``ro_role``
    (read-only) to its ``schema``.

    Each role inherits shared/public access from ``app_guild_base``. The login
    roles are granted membership in both ``WITH INHERIT FALSE`` — they can
    ``SET ROLE`` into either but hold no standing access to the schema, so a
    guild's data is reachable only by assuming one of its roles. The read-only
    role (assumed by PAM read grants) gets SELECT only, so a write is denied.
    """
    return [
        # Full role: DML on its schema.
        f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"',
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" '
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{role}"',
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" GRANT USAGE ON SEQUENCES TO "{role}"',
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "{schema}" TO "{role}"',
        f'GRANT USAGE ON ALL SEQUENCES IN SCHEMA "{schema}" TO "{role}"',
        f'GRANT app_guild_base TO "{role}"',
        f'GRANT "{role}" TO "{APP_LOGIN_ROLE}", "{ADMIN_LOGIN_ROLE}" WITH INHERIT FALSE',
        # Read-only role: SELECT only on the schema (PAM read grants). Shared/public
        # access still comes from app_guild_base; public writes stay RLS-gated.
        f'GRANT USAGE ON SCHEMA "{schema}" TO "{ro_role}"',
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" GRANT SELECT ON TABLES TO "{ro_role}"',
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" GRANT SELECT ON SEQUENCES TO "{ro_role}"',
        f'GRANT SELECT ON ALL TABLES IN SCHEMA "{schema}" TO "{ro_role}"',
        f'GRANT SELECT ON ALL SEQUENCES IN SCHEMA "{schema}" TO "{ro_role}"',
        f'GRANT app_guild_base TO "{ro_role}"',
        f'GRANT "{ro_role}" TO "{APP_LOGIN_ROLE}", "{ADMIN_LOGIN_ROLE}" WITH INHERIT FALSE',
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
        await conn.scalar(
            text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}
        )
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
    ro_role = guild_readonly_role_name(guild_id)
    await conn.exec_driver_sql(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    await _ensure_role(conn, role)
    await _ensure_role(conn, ro_role)
    await apply_guild_schema(conn, schema)  # canonical Alembic-owned table DDL
    await _exec_batch(conn, _grant_statements(schema, role, ro_role))
    return schema


async def drop_guild_schema(conn: AsyncConnection, guild_id: int) -> None:
    """Drop ``guild_<id>`` (schema + role). Safe if either is already absent."""
    schema = guild_schema_name(guild_id)

    # DROP SCHEMA needs an exclusive lock on the schema's tables (and on
    # public.guilds to drop their FKs); concurrent app sessions can hold it. Fail
    # fast rather than hang — the caller treats a failure as "retry later", and
    # this drop is idempotent so a retry recovers cleanly.
    await conn.exec_driver_sql("SET lock_timeout = '10s'")
    await conn.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    for role in (guild_role_name(guild_id), guild_readonly_role_name(guild_id)):
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
