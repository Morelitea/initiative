"""Provision and tear down a per-guild PostgreSQL schema.

`provision_guild_schema` creates `guild_<id>` (tables via `apply_guild_schema`,
which RUNS structure DDL reflected LIVE from the guild_template schema),
per-guild Postgres roles, and the initiative-level RLS policies (via
`apply_guild_rls`, running RLS DDL rendered from the INITIATIVE_PATHS
registry); `drop_guild_schema`
removes the schema + roles. Idempotent — re-running back-fills any guild-scoped
table a later migration added and re-asserts the policies. The model is never
used to build the DB: Alembic is the single source, applied per schema.
Per-request routing (search_path + SET ROLE in `set_rls_context`) sends
guild-scoped queries into the schema, where the RLS policies (deferring to
`public.initiative_access`) enforce initiative membership for non-admin roles.

`backfill_guild_schemas` re-runs that idempotent provisioning for *every*
existing guild on every boot (`main.on_startup`). This closes two drift gaps: a
guild provisioned before guild_template gained a table/column/index never
receives it, and a crash mid-provision can leave a guild row whose schema
doesn't exist. Provisioning is ~0.2s/guild and idempotent, so a plain
sequential loop heals both with no extra bookkeeping.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field

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


def guild_support_role_name(guild_id: int) -> str:
    """Restricted read_write role for a guild, e.g. ``guild_42_support``.

    Assumed by a scoped read_write PAM grant (the ``support`` guild identity): it
    can SELECT everything and edit content, but the structural / permission tables
    in ``SUPPORT_WRITE_PROTECTED_TABLES`` are SELECT-only, so a support grantee
    cannot manage who is in the guild or who can see what. Break-glass (full
    admin) uses the full ``guild_<id>`` role instead; a read grant uses ``_ro``.
    """
    return f"{settings.GUILD_ROLE_PREFIX}guild_{int(guild_id)}_support"


# Structural / permission tables the restricted ``support`` role may READ but never
# WRITE — the DB-enforced "no member/permission management" line. Coarse by design
# (table/verb, not row-level): the finer "edit-existing vs authoring" nuance stays in
# the pam_write RLS leg. Kept in lockstep with the guild schema by
# ``support_role_test`` (a renamed/added structural table must be reconsidered here).
SUPPORT_WRITE_PROTECTED_TABLES: tuple[str, ...] = (
    "initiative_members",
    "initiative_roles",
    "initiative_role_permissions",
    "resource_grants",
)


# The platform privilege ladder, least -> most. Positional mapping from
# ``users.role`` (an enum with these exact values). The migration creates one
# ``platform_<tier>`` NOLOGIN role per entry plus a shared ``platform_base``
# floor; the public/platform request path assumes ``platform_<users.role>``.
PLATFORM_TIERS: tuple[str, ...] = (
    "member",
    "support",
    "moderator",
    "operator",
    "owner",
)


def platform_role_name(role: str) -> str:
    """Cluster-global Postgres role for a platform tier, e.g. ``platform_operator``.

    Carries ``settings.PLATFORM_ROLE_PREFIX`` (empty in prod/dev; ``test_`` under
    the suite) so these cluster-global roles don't collide with a co-located dev
    DB's. ``role`` is a ``users.role`` value and is validated by the caller against
    :data:`PLATFORM_TIERS` before reaching the privileged ``SET ROLE`` sink.
    """
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_{role}"


def billing_role_name() -> str:
    """Cluster-global Postgres role the billing-service endpoints assume
    (created by migration 0134). Shares ``settings.PLATFORM_ROLE_PREFIX``
    because it is cluster-global like the platform ladder."""
    return f"{settings.PLATFORM_ROLE_PREFIX}initiative_billing"


@dataclass(frozen=True)
class ProvisioningBundle:
    """The per-process render of everything provisioning applies.

    ``schema_ddl`` is reflected LIVE from the Alembic-maintained
    ``guild_template`` schema; ``rls_ddl`` is rendered from the
    ``INITIATIVE_PATHS`` registry (see ``app.db.guild_ddl``). There are no
    committed artifacts — new guilds match the template + registry by
    construction. ``stamp`` hashes both renders plus the rendered grant
    statements, so ANY provisioning-relevant change (a guild migration, a
    registry edit, a grants change) produces a new stamp and a one-time
    re-provisioning sweep on the next boot.
    """

    schema_ddl: str
    rls_ddl: str
    stamp: str


_bundle: ProvisioningBundle | None = None
_bundle_lock = asyncio.Lock()


async def get_provisioning_bundle() -> ProvisioningBundle:
    """Render (once per process, after migrations have run) and cache."""
    global _bundle
    if _bundle is not None:
        return _bundle
    async with _bundle_lock:
        if _bundle is not None:
            return _bundle
        from app.db.guild_ddl import render_guild_rls_ddl, render_guild_schema_ddl

        schema_ddl = await render_guild_schema_ddl(db_session.provisioning_engine)
        rls_ddl = render_guild_rls_ddl()
        digest = hashlib.sha256()
        digest.update(schema_ddl.encode())
        digest.update(rls_ddl.encode())
        digest.update(
            "\n".join(
                _grant_statements(
                    "__stamp__",
                    "__stamp_role__",
                    "__stamp_ro__",
                    "__stamp_support__",
                )
            ).encode()
        )
        _bundle = ProvisioningBundle(
            schema_ddl=schema_ddl,
            rls_ddl=rls_ddl,
            stamp=f"provisioned:{digest.hexdigest()[:16]}",
        )
        return _bundle


def reset_provisioning_bundle() -> None:
    """Drop the cached render (tests; or after in-process template changes)."""
    global _bundle
    _bundle = None


async def apply_guild_schema(conn: AsyncConnection, schema: str) -> None:
    """Build/refresh ``schema``'s guild-scoped tables by RUNNING the canonical,
    Alembic-owned DDL with the search_path pointed at it.

    The same DDL builds ``guild_template`` (a migration) and every ``guild_<id>``
    (provisioning) — one source of truth, applied per schema. It's schema-relative
    (unqualified names resolve in ``schema``; shared types/tables fall through to
    ``public``) and idempotent (``IF NOT EXISTS`` / guarded constraints), so a
    re-run back-fills anything a later migration added. No model, no clone.
    """
    ddl = (await get_provisioning_bundle()).schema_ddl
    raw = await conn.get_raw_connection()
    # search_path so unqualified CREATEs land in the schema and intra-schema FKs
    # resolve there; reset to public so it doesn't leak onto the pooled connection.
    await raw.driver_connection.execute(
        f'SET search_path TO "{schema}", public;\n{ddl}\nSET search_path TO public;'
    )


async def apply_guild_rls(conn: AsyncConnection, schema: str) -> None:
    """Apply the initiative-level RLS policies to ``schema``'s tables by RUNNING
    the registry-rendered RLS DDL with the search_path pointed at it.

    Schema-relative + idempotent (``ENABLE/FORCE`` + ``DROP POLICY IF EXISTS`` +
    ``CREATE POLICY``), so a re-run (provisioning, boot back-fill) re-asserts the
    policies harmlessly. Policies defer to ``public.initiative_access`` (qualified,
    so it resolves regardless of search_path); the per-table EXISTS joins resolve
    against the guild-local tables. Requires ``public.initiative_access`` to exist
    (created by migration 20260616_0110).
    """
    ddl = (await get_provisioning_bundle()).rls_ddl
    raw = await conn.get_raw_connection()
    await raw.driver_connection.execute(
        f'SET search_path TO "{schema}", public;\n{ddl}\nSET search_path TO public;'
    )


def _grant_statements(
    schema: str, role: str, ro_role: str, support_role: str
) -> list[str]:
    """Fail-closed grants tying a guild's ``role`` (read/write), ``ro_role``
    (read-only) and ``support_role`` (restricted read/write) to its ``schema``.

    NOTE: the provisioning-bundle stamp hashes this function's RENDERED
    output, so changing WHAT it grants invalidates every guild's stamp and
    schedules one full (idempotent) re-provisioning sweep on the next boot —
    cosmetic edits here don't.

    Each role inherits shared/public access from ``app_guild_base``. The login
    roles are granted membership in all three ``WITH INHERIT FALSE`` — they can
    ``SET ROLE`` into any but hold no standing access to the schema, so a
    guild's data is reachable only by assuming one of its roles. The read-only
    role (assumed by PAM read grants) gets SELECT only, so a write is denied.
    The support role (scoped read_write grants) gets DML on content but is
    revoked write on the structural/permission tables — the DB-enforced
    "no member/permission management" line.
    """
    stmts = [
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
        # Support role: read_write on content, but SELECT-only on the structural /
        # permission tables. Grant broadly (incl. default privileges for future
        # content tables) then REVOKE write on the protected set — coarse by design.
        f'GRANT USAGE ON SCHEMA "{schema}" TO "{support_role}"',
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" '
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{support_role}"',
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" '
        f'GRANT USAGE ON SEQUENCES TO "{support_role}"',
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "{schema}" '
        f'TO "{support_role}"',
        f'GRANT USAGE ON ALL SEQUENCES IN SCHEMA "{schema}" TO "{support_role}"',
        f'GRANT app_guild_base TO "{support_role}"',
        f'GRANT "{support_role}" TO "{APP_LOGIN_ROLE}", "{ADMIN_LOGIN_ROLE}" '
        f"WITH INHERIT FALSE",
    ]
    # Hard-cap the support role: SELECT stays, writes are revoked on the structural /
    # permission tables (these exist in every schema, so the REVOKE always applies).
    for table in SUPPORT_WRITE_PROTECTED_TABLES:
        stmts.append(
            f'REVOKE INSERT, UPDATE, DELETE ON "{schema}"."{table}" '
            f'FROM "{support_role}"'
        )
    return stmts


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
    support_role = guild_support_role_name(guild_id)
    await conn.exec_driver_sql(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    await _ensure_role(conn, role)
    await _ensure_role(conn, ro_role)
    await _ensure_role(conn, support_role)
    await apply_guild_schema(conn, schema)  # canonical Alembic-owned table DDL
    await _exec_batch(conn, _grant_statements(schema, role, ro_role, support_role))
    await apply_guild_rls(conn, schema)  # initiative-level RLS policies
    # Stamp the artifacts' version so the boot back-fill can skip this guild
    # until they change (constant hex literal, safe to inline).
    stamp = (await get_provisioning_bundle()).stamp
    await conn.exec_driver_sql(f"COMMENT ON SCHEMA \"{schema}\" IS '{stamp}'")
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
    for role in (
        guild_role_name(guild_id),
        guild_readonly_role_name(guild_id),
        guild_support_role_name(guild_id),
    ):
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
    guild whose stamp doesn't match the bundle stamp — i.e. its
    schema predates the current template structure / rendered RLS /
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
    stamp = (await get_provisioning_bundle()).stamp
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
    """Emit a deprecation banner when DATABASE_URL connects as a superuser
    (or BYPASSRLS) role.

    The app never needs a Postgres superuser: migrations + guild provisioning
    fit in the least-privilege ``app_provisioner`` role (NOSUPERUSER CREATEROLE
    + CREATE on the database + ownership of the app's objects). Role creation
    is an infrastructure concern, not app code: fresh docker-compose installs
    get the role from the Postgres image's ``docker-entrypoint-initdb.d``
    script; existing deployments run ``scripts/create-provisioner.sql`` once
    (see the deployment docs), then point DATABASE_URL at ``app_provisioner``.

    Superuser DATABASE_URL support is DEPRECATED and a future release will
    refuse to start with it, so the banner is deliberately loud — a framed
    multi-line block at WARNING every boot, not a one-liner that scrolls past —
    to move the remaining legacy deployments before the hard cutoff.
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
            "\n%s\n"
            "DEPRECATED: DATABASE_URL connects as %s role.\n"
            "The app never needs these privileges, and a FUTURE RELEASE WILL\n"
            "REFUSE TO START with them. Migrate once (about a minute):\n"
            "\n"
            "  1. Create the least-privilege provisioning role — connected as\n"
            "     the current DATABASE_URL role, run\n"
            "     backend/scripts/create-provisioner.sql, e.g.:\n"
            "       docker exec -i initiative-db \\\n"
            "         psql -v ON_ERROR_STOP=1 -U <user> -d <database> \\\n"
            "              -v provisioner_password='CHANGE-ME' \\\n"
            "              -f - < backend/scripts/create-provisioner.sql\n"
            "  2. Point DATABASE_URL at app_provisioner and restart.\n"
            "\n"
            "DATABASE_URL_APP / DATABASE_URL_ADMIN are unaffected. See the\n"
            "deployment docs for details.\n"
            "%s",
            "=" * 70,
            "a SUPERUSER" if rolsuper else "a BYPASSRLS",
            "=" * 70,
        )


_EFFECTIVE_BYPASS_SQL = (
    "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user"
)


def _bypassrls_exit_message(admin_login: str, heal_attempted: bool) -> str:
    """The boot-stopping message for a policy-bound system engine.

    ``heal_attempted`` distinguishes "this process may not repair the role"
    from "an in-place repair ran without error yet the re-check still sees no
    bypass" — the operator must know a repair already happened, or the
    instruction to run the same ALTER reads as the whole fix when something
    deeper (e.g. a pooler authenticating the admin URL as a different role)
    is eating it.
    """
    if heal_attempted:
        attempted = (
            "An automatic repair (ALTER ROLE … WITH BYPASSRLS via DATABASE_URL)\n"
            "already ran without error, but a fresh DATABASE_URL_ADMIN\n"
            "connection still reports no bypass — the URL is likely reaching a\n"
            "different role than it names (e.g. through a connection pooler).\n"
            "Verify which role the connection really lands on:\n\n"
            "  SELECT current_user, rolbypassrls FROM pg_roles\n"
            "   WHERE rolname = current_user;\n\n"
            "and repair that role as a Postgres superuser:\n"
        )
    else:
        attempted = "Repair it as a Postgres superuser:\n"
    return (
        f"\n{'=' * 70}\n"
        f"DATABASE_URL_ADMIN connects as {admin_login!r}, which does not hold\n"
        "the BYPASSRLS attribute. This login is the app's system engine\n"
        "(startup seeding, background jobs); policy-bound, it reads every\n"
        "shared table as empty and boot fails with a row-level security\n"
        "error. Roles are cluster state — restoring a database from a dump\n"
        "does not restore them.\n\n"
        f"{attempted}\n"
        f'  ALTER ROLE "{admin_login}" WITH BYPASSRLS;\n\n'
        "then restart the app.\n"
        f"{'=' * 70}"
    )


async def ensure_system_engine_bypassrls() -> None:
    """Verify the system engine (``DATABASE_URL_ADMIN``) actually bypasses RLS,
    re-asserting the attribute when the provisioning login lawfully can.

    Every seeding/background-job query assumes the system engine holds
    BYPASSRLS. A login that connects fine but is policy-bound (roles are
    cluster state — a ``pg_dump``-based restore recreates none of their
    attributes, and hand-created logins may omit the attribute) reads every
    shared table as empty, so the first boot after such a restore dies deep in
    startup seeding with an opaque "new row violates row-level security policy
    for table \"guilds\"" while trying to re-create the primary guild it cannot
    see (issue #835). The baseline migration verifies this contract, but only
    fresh databases run it — an already-stamped database is never re-checked.

    Runs right after migrations on every boot. When ``DATABASE_URL`` holds
    BYPASSRLS or superuser (Postgres reserves BYPASSRLS surgery for holders of
    it — true for legacy deployments that still migrate as the compose
    superuser), the attribute is repaired in place, preserving the baseline's
    self-healing behavior. Otherwise boot stops with the exact repair command
    instead of the downstream RLS error.
    """
    async with db_session.admin_engine.connect() as conn:
        admin_login, bypasses = (
            await conn.execute(
                text(
                    "SELECT current_user, "
                    "(SELECT rolsuper OR rolbypassrls FROM pg_roles "
                    " WHERE rolname = current_user)"
                )
            )
        ).one()
    if bypasses:
        return

    async with db_session.provisioning_engine.begin() as conn:
        can_heal = (await conn.execute(text(_EFFECTIVE_BYPASS_SQL))).scalar()
        if can_heal:
            # Role DDL takes no bind parameters; pin the identifier through a
            # transaction-local GUC and quote it server-side with format(%I),
            # mirroring the baseline migration's role DDL.
            await conn.execute(
                text("SELECT set_config('app._system_engine_login', :name, true)"),
                {"name": admin_login},
            )
            await conn.execute(
                text(
                    "DO $$ BEGIN "
                    "EXECUTE format('ALTER ROLE %I WITH BYPASSRLS', "
                    "current_setting('app._system_engine_login')); "
                    "END $$"
                )
            )

    if can_heal:
        async with db_session.admin_engine.connect() as conn:
            healed = (await conn.execute(text(_EFFECTIVE_BYPASS_SQL))).scalar()
        if healed:
            logger.warning(
                "System engine login %r was missing BYPASSRLS — re-asserted it "
                "via DATABASE_URL. Restored databases lose role attributes; "
                "no action needed.",
                admin_login,
            )
            return
        logger.error(
            "Re-asserted BYPASSRLS on %r via DATABASE_URL, but a fresh "
            "DATABASE_URL_ADMIN connection still reports no bypass.",
            admin_login,
        )

    raise SystemExit(
        _bypassrls_exit_message(admin_login, heal_attempted=bool(can_heal))
    )


# --- shared-table grant healing (issue #835, deeper than the BYPASSRLS heal) --
#
# BYPASSRLS (above) lets the system engine skip RLS *policies*; it does NOT skip
# table-level privilege checks. A restored/recreated cluster can bring app_admin
# back with LOGIN + BYPASSRLS but WITHOUT the per-table GRANTs the migrations
# applied — roles are cluster state, and an already-stamped database never
# re-runs the grant-issuing migrations. The system engine then fails one gate
# deeper than #835's first report: "permission denied for table guilds" while
# seeding the primary guild it can read (BYPASSRLS) but not INSERT (no grant).
# `backfill_guild_schemas` re-asserts GUILD-schema grants on every boot; nothing
# did the same for the shared `public` tables. This does, sourced from the
# audited `system_grants` registry (the single truth for those grants),
# additively and idempotently.
#
# The bare login role (`app_user`, the pre-routing surface) is healed the same
# way from its own registry — a restore loses its grants too.

# A directly-connecting role that may INSERT needs privilege on the row-id
# sequence as well; match what the baseline grants each role.
_SEQUENCE_GRANT_BY_ROLE: dict[str, str] = {
    "app_admin": "ALL",
    "app_user": "SELECT, USAGE",
}


def _expected_shared_table_grants() -> list[tuple[str, str, frozenset[str]]]:
    """`(role, table, verbs)` the two directly-connecting roles must hold on the
    shared `public` tables, from the audited registries. Tables mapped to
    ``None`` (no access) are omitted."""
    from app.db import system_grants

    expected: list[tuple[str, str, frozenset[str]]] = []
    for role, matrix in (
        ("app_admin", system_grants.SHARED_TABLE_SYSTEM_GRANTS),
        ("app_user", system_grants.SHARED_TABLE_APP_USER_GRANTS),
    ):
        for table, verbs in matrix.items():
            if verbs:
                expected.append((role, table, verbs))
    return expected


async def _shared_grants_intact(
    conn: AsyncConnection, expected: list[tuple[str, str, frozenset[str]]]
) -> bool:
    """True when every expected `(role, table, verb)` privilege is already held.

    A single round-trip via ``has_table_privilege`` (authoritative — it respects
    role membership and the live ACL, and any login may query another role's
    privilege). Probes table grants only: a role recreation loses a role's table
    AND sequence grants together, so a missing table grant reliably signals the
    restore damage this heals; the heal then re-asserts both.
    """
    # Registry table names are trusted constants (not user input); inline them.
    values = ", ".join(
        f"('{role}', 'public.{table}', '{verb}')"
        for role, table, verbs in expected
        for verb in verbs
    )
    intact = (
        await conn.execute(
            text(
                "SELECT bool_and(has_table_privilege(role, tbl, priv)) "
                f"FROM (VALUES {values}) AS t(role, tbl, priv)"
            )
        )
    ).scalar()
    return bool(intact)


async def _reassert_shared_grants(
    conn: AsyncConnection, expected: list[tuple[str, str, frozenset[str]]]
) -> int:
    """Re-GRANT the audited table verbs (and, for insertable tables, the owned
    row-id sequence) to each role. Additive and idempotent — never REVOKEs, so
    it can only restore missing grants, never contradict a migration that
    intentionally reduced them. Returns the number of table grants asserted."""
    from app.db import system_grants

    for role, table, verbs in expected:
        verb_list = system_grants.grant_sql(verbs)
        if not verb_list:
            # Unreachable: _expected_shared_table_grants already drops None/empty
            # entries. The guard makes that invariant explicit and narrows
            # grant_sql's `str | None` to `str` (no `GRANT None …` can render).
            continue
        await conn.execute(
            text(f'GRANT {verb_list} ON TABLE public."{table}" TO "{role}"')
        )
        if "INSERT" not in verbs:
            continue
        # INSERT needs privilege on the row-id sequence too. Discover sequences
        # OWNED BY the table (robust to a serial column not named `id`) instead
        # of assuming a name.
        seqs = (
            await conn.execute(
                text(
                    "SELECT quote_ident(n.nspname) || '.' || quote_ident(s.relname) "
                    "FROM pg_class s "
                    "JOIN pg_depend d ON d.objid = s.oid "
                    "  AND d.classid = 'pg_class'::regclass "
                    "  AND d.refclassid = 'pg_class'::regclass AND d.deptype = 'a' "
                    "JOIN pg_class t ON t.oid = d.refobjid "
                    "JOIN pg_namespace n ON n.oid = s.relnamespace "
                    "WHERE s.relkind = 'S' AND n.nspname = 'public' "
                    "  AND t.relname = :table"
                ),
                {"table": table},
            )
        ).scalars()
        seq_grant = _SEQUENCE_GRANT_BY_ROLE[role]
        for seq in seqs:
            await conn.execute(text(f'GRANT {seq_grant} ON SEQUENCE {seq} TO "{role}"'))
    return len(expected)


async def ensure_shared_table_grants() -> None:
    """Heal missing table/sequence GRANTs on the shared ``public`` tables for the
    app's directly-connecting roles (``app_admin`` system engine, ``app_user``
    bare login).

    Companion to :func:`ensure_system_engine_bypassrls`: that repairs the RLS
    *attribute*, this repairs the table *grants* one gate deeper. Both close the
    same class of drift — a ``pg_dump``-based restore or a hand-recreated role
    loses cluster state that an already-stamped database never re-applies
    (issue #835). Runs right after the BYPASSRLS check on every boot; a healthy
    posture is a single-SELECT no-op.
    """
    expected = _expected_shared_table_grants()
    if not expected:
        return
    async with db_session.provisioning_engine.connect() as conn:
        if await _shared_grants_intact(conn, expected):
            return
    # Something is missing — re-assert the full audited set via the object owner
    # (the provisioning engine, which the grant-issuing migrations also use).
    async with db_session.provisioning_engine.begin() as conn:
        asserted = await _reassert_shared_grants(conn, expected)
    logger.warning(
        "Shared-table grants were incomplete for the app's directly-connecting "
        "roles (app_admin/app_user) — re-asserted %d audited table grant(s) "
        "(plus the row-id sequences of insertable tables) from the system_grants "
        "registry. Restored databases lose role grants (issue #835); no action "
        "needed.",
        asserted,
    )
