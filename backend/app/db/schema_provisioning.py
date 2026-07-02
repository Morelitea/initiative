"""Provision and tear down a per-guild PostgreSQL schema.

`provision_guild_schema` creates `guild_<id>` (tables via `apply_guild_schema`,
which RUNS the canonical Alembic-owned DDL in `alembic/guild/guild_schema.sql`),
per-guild Postgres roles, and the initiative-level RLS policies (via
`apply_guild_rls`, running `alembic/guild/guild_rls.sql`); `drop_guild_schema`
removes the schema + roles. Idempotent — re-running back-fills any guild-scoped
table a later migration added and re-asserts the policies. The model is never
used to build the DB: Alembic is the single source, applied per schema.
Per-request routing (search_path + SET ROLE in `set_rls_context`) sends
guild-scoped queries into the schema, where the RLS policies (deferring to
`public.initiative_access`) enforce initiative membership for non-admin roles.

`backfill_guild_schemas` re-runs that idempotent provisioning for *every*
existing guild on every boot (`main.on_startup`). This closes two drift gaps: a
guild provisioned before `guild_schema.sql` gained a table/column/index never
receives it, and a crash mid-provision can leave a guild row whose schema
doesn't exist. Provisioning is ~0.2s/guild and idempotent, so a plain
sequential loop heals both with no extra bookkeeping.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import settings
from app.db import session as db_session

logger = logging.getLogger(__name__)

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


# The platform privilege ladder, least -> most. Positional mapping from
# ``users.role`` (an enum with these exact values). The migration creates one
# ``platform_<tier>`` NOLOGIN role per entry plus a shared ``platform_base``
# floor; the public/platform request path assumes ``platform_<users.role>``.
PLATFORM_TIERS: tuple[str, ...] = ("member", "support", "moderator", "admin", "owner")


def platform_role_name(role: str) -> str:
    """Cluster-global Postgres role for a platform tier, e.g. ``platform_admin``.

    Carries ``settings.PLATFORM_ROLE_PREFIX`` (empty in prod/dev; ``test_`` under
    the suite) so these cluster-global roles don't collide with a co-located dev
    DB's. ``role`` is a ``users.role`` value and is validated by the caller against
    :data:`PLATFORM_TIERS` before reaching the privileged ``SET ROLE`` sink.
    """
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_{role}"


# The single source for a guild schema's structure: schema-relative DDL generated
# from the Alembic-maintained guild_template schema (regenerate with
# scripts/gen_guild_schema.py after any guild-scoped migration). The model is
# never used to build the DB.
GUILD_SCHEMA_SQL_PATH = (
    Path(__file__).resolve().parents[2] / "alembic" / "guild" / "guild_schema.sql"
)

# Companion to guild_schema.sql: initiative-level RLS for the schema's tables.
# The access RULE lives once in public.initiative_access (member OR guild-admin OR
# PAM); these policies just resolve each table's initiative id and defer to it.
GUILD_RLS_SQL_PATH = (
    Path(__file__).resolve().parents[2] / "alembic" / "guild" / "guild_rls.sql"
)


@lru_cache(maxsize=1)
def provisioning_stamp() -> str:
    """Schema-comment stamp identifying the provisioning artifacts' version.

    A guild schema whose comment carries the current stamp was provisioned by
    exactly these artifacts, so the boot back-fill can skip it — O(changed
    guilds) boots instead of O(all guilds). The stamp covers the two SQL
    artifacts AND the grant layer (the ``_grant_statements`` source plus the
    login-role names it targets), so any provisioning change — including a
    grants-only edit — produces a new stamp and a one-time full sweep. No
    manual version bump to forget.
    """
    digest = hashlib.sha256()
    digest.update(GUILD_SCHEMA_SQL_PATH.read_bytes())
    digest.update(GUILD_RLS_SQL_PATH.read_bytes())
    digest.update(inspect.getsource(_grant_statements).encode())
    digest.update(f"{APP_LOGIN_ROLE}|{ADMIN_LOGIN_ROLE}".encode())
    return f"provisioned:{digest.hexdigest()[:16]}"


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


async def apply_guild_rls(conn: AsyncConnection, schema: str) -> None:
    """Apply the initiative-level RLS policies to ``schema``'s tables by RUNNING
    the canonical ``guild_rls.sql`` with the search_path pointed at it.

    Schema-relative + idempotent (``ENABLE/FORCE`` + ``DROP POLICY IF EXISTS`` +
    ``CREATE POLICY``), so a re-run (provisioning, boot back-fill) re-asserts the
    policies harmlessly. Policies defer to ``public.initiative_access`` (qualified,
    so it resolves regardless of search_path); the per-table EXISTS joins resolve
    against the guild-local tables. Requires ``public.initiative_access`` to exist
    (created by migration 20260616_0110).
    """
    ddl = GUILD_RLS_SQL_PATH.read_text()
    raw = await conn.get_raw_connection()
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
    await apply_guild_rls(conn, schema)  # initiative-level RLS policies
    # Stamp the artifacts' version so the boot back-fill can skip this guild
    # until they change (constant hex literal, safe to inline).
    await conn.exec_driver_sql(
        f"COMMENT ON SCHEMA \"{schema}\" IS '{provisioning_stamp()}'"
    )
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
    provisioning_login = make_url(settings.DATABASE_URL).username
    for role in (guild_role_name(guild_id), guild_readonly_role_name(guild_id)):
        if await _role_exists(conn, role):
            # DROP OWNED requires the role's PRIVILEGES, not just ADMIN OPTION
            # on it (PG16+ separates the two). The provisioning login
            # administers every guild role, so grant itself membership first —
            # a no-op under a superuser DATABASE_URL.
            await conn.exec_driver_sql(f'GRANT "{role}" TO "{provisioning_login}"')
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
    """Drop a guild's schema + role on the superuser engine, and remove its blobs."""
    async with db_session.provisioning_engine.begin() as conn:
        await drop_guild_schema(conn, guild_id)
    # Remove the guild's stored blobs (the ``guild_<id>/`` storage namespace).
    # Best-effort and after the schema drop succeeds: a storage hiccup must not
    # strand a half-deleted guild, and delete_prefix needs no DB so order is moot.
    try:
        from app.services.storage import purge_guild_blobs

        # Offload to a thread: the S3 path makes paginated blocking calls, and this
        # runs on the event loop. A one-shot teardown shouldn't stall the loop.
        removed = await asyncio.to_thread(purge_guild_blobs, guild_id)
        logger.info(
            "deprovision guild %s: removed %d stored blob(s)", guild_id, removed
        )
    except Exception:  # noqa: BLE001 — blob cleanup must not block teardown
        logger.exception("failed to purge stored blobs for guild %s", guild_id)


@dataclass
class BackfillSummary:
    """Outcome of a `backfill_guild_schemas` sweep, for a one-line boot log."""

    total: int
    provisioned: int
    failed: int
    skipped: int = 0  # stamp matched — provisioned by the current artifacts
    failed_guild_ids: list[int] = field(default_factory=list)


async def backfill_guild_schemas() -> BackfillSummary:
    """Re-provision every guild schema the current artifacts haven't built yet.

    Enumerates guild ids (and their schema-comment stamps) from the
    provisioning engine, then runs the idempotent ``provision_guild`` for each
    guild whose stamp doesn't match :func:`provisioning_stamp` — i.e. its
    schema predates the current ``guild_schema.sql`` / ``guild_rls.sql`` /
    grants version, is missing entirely, or was never stamped. Because
    provisioning re-runs the canonical DDL (``CREATE ... IF NOT EXISTS``) and
    re-applies grants, this back-fills any table/column/index/grant added
    since, then re-stamps. Already-stamped guilds are skipped, so a boot with
    unchanged artifacts is O(changed guilds), not O(all guilds) — set
    ``FORCE_GUILD_BACKFILL=true`` to sweep everything regardless.

    Per-guild failures are logged with the guild id and skipped so one broken
    guild can't take down boot for the rest; ``provision_guild`` runs each guild
    in its own transaction, so a failure rolls back only that guild. Returns a
    summary for the caller to log.
    """
    stamp = provisioning_stamp()
    # Enumerate on the SYSTEM engine, not the provisioning engine: guild ids
    # live in the RLS-forced public.guilds, and the provisioner is a pure DDL
    # actor — FORCE RLS filters its unrouted data reads to zero rows (by
    # design). Reading data is the system engine's job (BYPASSRLS).
    async with db_session.admin_engine.connect() as conn:
        # Pooled connection: shed any guild role a previous checkout assumed
        # (a leaked role would RLS-filter public.guilds to zero rows).
        await conn.execute(text("SELECT set_config('role', 'none', false)"))
        rows = (
            await conn.execute(
                text(
                    "SELECT g.id, obj_description(n.oid) "
                    "FROM public.guilds g "
                    "LEFT JOIN pg_namespace n ON n.nspname = 'guild_' || g.id "
                    "ORDER BY g.id"
                )
            )
        ).all()

    provisioned = 0
    skipped = 0
    failed_guild_ids: list[int] = []
    for gid, comment in rows:
        if comment == stamp and not settings.FORCE_GUILD_BACKFILL:
            skipped += 1
            continue
        try:
            await provision_guild(gid)
            provisioned += 1
        except Exception:  # noqa: BLE001 — one broken guild must not block boot
            failed_guild_ids.append(gid)
            logger.exception("guild schema back-fill failed for guild %s", gid)

    return BackfillSummary(
        total=len(rows),
        provisioned=provisioned,
        failed=len(failed_guild_ids),
        skipped=skipped,
        failed_guild_ids=failed_guild_ids,
    )


async def warn_if_privileged_database_url() -> None:
    """Warn when DATABASE_URL connects as a superuser (or BYPASSRLS) role.

    The app never needs a Postgres superuser: migrations + guild provisioning
    fit in the least-privilege ``app_provisioner`` role (NOSUPERUSER CREATEROLE
    + CREATE on the database + ownership of the app's objects). Role creation
    is an infrastructure concern, not app code: fresh docker-compose installs
    get the role from the Postgres image's ``docker-entrypoint-initdb.d``
    script; existing deployments run ``scripts/create-provisioner.sql`` once
    (see the deployment docs), then point DATABASE_URL at ``app_provisioner``.
    """
    async with db_session.provisioning_engine.connect() as conn:
        rolsuper, rolbypassrls = (
            await conn.execute(
                text(
                    "SELECT rolsuper, rolbypassrls FROM pg_roles "
                    "WHERE rolname = current_user"
                )
            )
        ).one()
    if rolsuper or rolbypassrls:
        logger.warning(
            "DATABASE_URL connects as %s role — the app does not need this. "
            "Run backend/scripts/create-provisioner.sql once (see the "
            "deployment docs) and point DATABASE_URL at app_provisioner.",
            "a SUPERUSER" if rolsuper else "a BYPASSRLS",
        )
