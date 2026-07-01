"""Baseline migration: v0.53.5 schema snapshot replacing 73 incremental migrations.

Revision ID: 20260626_0125
Revises: (none — this is the new root)
Create Date: 2026-06-26 (squashed 2026-07-01)

Second squash (the first was 20260216_0053, a v0.30.0 snapshot). For a database
already stamped '20260626_0125' (any v0.53.2+ deployment) upgrade() never runs —
the revision id deliberately equals the old head. For a fresh database it
creates the login/platform/guild-base roles and then builds the **shared public
schema only**, by running the frozen snapshot artifact
``alembic/baseline/public_schema_0125.sql`` (pg_dump of a chain-built v0.53.5
database, curated).

Deliberately ABSENT — the point of this squash:

* The legacy ``public.<guild-content>`` tables (tasks, projects, documents, …).
  Guild content lives only in per-guild ``guild_<id>`` schemas (and
  ``guild_template``, created by migration 20260701_0126) built from
  ``alembic/guild/guild_schema.sql``. Fresh installs never get public copies.
  Existing deployments keep their frozen copies untouched — nothing reads or
  writes them, and this squash does NOT drop them (data-integrity backstop).

**Upgrade floor: v0.53.2.** A deployment older than that must upgrade to a
v0.53.x release and boot it once (its startup runs the schema-per-guild data
conversion) before upgrading past this squash; older revision ids no longer
exist in this chain, so alembic fails loudly rather than corrupting anything.

Role names: ``app_user`` / ``app_admin`` / ``app_guild_base`` are fixed;
``platform_base`` / ``platform_<tier>`` carry ``settings.PLATFORM_ROLE_PREFIX``
read at APPLY time (the test suite migrates with a prefix), and the same prefix
is substituted into the snapshot's GRANT/POLICY statements.
"""

import os
import re
import string
from pathlib import Path
from urllib.parse import urlparse

from alembic import op
from sqlalchemy import text

from app.db.guild_migrations import split_sql_statements

revision = "20260626_0125"
down_revision = None
branch_labels = None
depends_on = None

_SNAPSHOT_SQL_PATH = (
    Path(__file__).resolve().parents[1] / "baseline" / "public_schema_0125.sql"
)

# The five platform tiers, least -> most privileged. A frozen copy of
# schema_provisioning.PLATFORM_TIERS: migrations are immutable records, so this
# baseline must not drift if the ladder ever changes (that would be a new
# migration's job).
_PLATFORM_TIERS = ("member", "support", "moderator", "admin", "owner")

# Prefix defense-in-depth (operator/test config, never user input): explicit
# allow-list of role-name characters so a stray quote can't break out of DDL.
_ALLOWED_PREFIX_CHARS = frozenset(string.ascii_letters + string.digits + "_")


def _platform_prefix() -> str:
    """The platform-role prefix, read from settings at APPLY time (the test
    suite sets it before running migrations; empty in prod/dev)."""
    from app.core.config import settings

    prefix = settings.PLATFORM_ROLE_PREFIX
    if not set(prefix) <= _ALLOWED_PREFIX_CHARS:
        raise ValueError(f"unsafe PLATFORM_ROLE_PREFIX for role DDL: {prefix!r}")
    return prefix


# ---------------------------------------------------------------------------
# Role helpers (carried over from the previous 20260216_0053 baseline)
# ---------------------------------------------------------------------------


def _role_exists(connection, rolname: str) -> bool:
    result = connection.execute(
        text("SELECT 1 FROM pg_roles WHERE rolname = :name"),
        {"name": rolname},
    )
    return result.fetchone() is not None


def _password_from_url(env_var: str) -> str | None:
    """Extract the password component from a DATABASE_URL env var.

    Checks os.environ first (Docker / exported vars), then falls back to the
    pydantic settings object which reads from .env files.
    """
    url = os.environ.get(env_var)
    if not url:
        try:
            from app.core.config import settings

            url = getattr(settings, env_var, None)
        except Exception:
            pass
    if not url:
        return None
    try:
        return urlparse(url).password
    except Exception:
        return None


def _exec_role_ddl(connection, ddl_template: str, password: str | None) -> None:
    """Execute a role DDL statement with an optional password.

    PostgreSQL DDL (CREATE/ALTER ROLE) doesn't support bind parameters, so the
    password travels through set_config() and format('%L') for safe literal
    quoting inside a DO block.
    """
    if password is not None:
        connection.execute(
            text("SELECT set_config('app._migration_pw', :pw, true)"),
            {"pw": password},
        )
        connection.execute(
            text(
                "DO $$ BEGIN "
                f"EXECUTE format('{ddl_template} PASSWORD %L', "
                "current_setting('app._migration_pw')); "
                "END $$"
            )
        )
        connection.execute(text("SELECT set_config('app._migration_pw', '', true)"))
    else:
        connection.execute(text(ddl_template))


def _create_login_roles(connection) -> None:
    """app_user (RLS-enforced request path) and app_admin (BYPASSRLS system
    engine), passwords synced from DATABASE_URL_APP / DATABASE_URL_ADMIN."""
    app_user_pw = _password_from_url("DATABASE_URL_APP")
    if not _role_exists(connection, "app_user"):
        if app_user_pw:
            _exec_role_ddl(
                connection, "CREATE ROLE app_user WITH LOGIN NOINHERIT", app_user_pw
            )
        else:
            print(
                "NOTE: app_user role does not exist and DATABASE_URL_APP is not set.\n"
                "RLS enforcement requires this role. Create it with:\n"
                "  CREATE ROLE app_user WITH LOGIN NOINHERIT PASSWORD 'your_password';\n"
                "The baseline migration handles this when DATABASE_URL_APP is set."
            )
    else:
        _exec_role_ddl(
            connection, "ALTER ROLE app_user WITH LOGIN NOINHERIT", app_user_pw
        )

    app_admin_pw = _password_from_url("DATABASE_URL_ADMIN")
    if not _role_exists(connection, "app_admin"):
        if app_admin_pw:
            _exec_role_ddl(
                connection, "CREATE ROLE app_admin WITH LOGIN BYPASSRLS", app_admin_pw
            )
        else:
            print(
                "NOTE: app_admin role does not exist and DATABASE_URL_ADMIN is not set.\n"
                "The system engine requires this role. Create it with:\n"
                "  CREATE ROLE app_admin WITH LOGIN BYPASSRLS PASSWORD 'your_password';\n"
                "The baseline migration handles this when DATABASE_URL_ADMIN is set."
            )
    else:
        _exec_role_ddl(
            connection, "ALTER ROLE app_admin WITH LOGIN BYPASSRLS", app_admin_pw
        )


def _create_nologin_role(connection, role: str) -> None:
    connection.execute(
        text(
            f"""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                    CREATE ROLE "{role}" NOLOGIN;
                END IF;
            END $$;
            """
        )
    )


def _create_support_roles(connection) -> None:
    """app_guild_base (shared/public floor every guild role inherits) and the
    platform ladder (platform_base floor + five NOLOGIN platform_<tier> roles).

    Only role CREATion and memberships happen here — every schema/table grant
    and default privilege comes from the snapshot artifact, so per-table ACLs
    land exactly as the old chain left them (e.g. app_settings writes are
    owner-only). None of these roles carries BYPASSRLS.
    """
    prefix = _platform_prefix()
    base = f"{prefix}platform_base"
    tiers = [f"{prefix}platform_{tier}" for tier in _PLATFORM_TIERS]

    _create_nologin_role(connection, "app_guild_base")
    for role in (base, *tiers):
        _create_nologin_role(connection, role)

    # Each tier inherits the base floor; the login roles may only SET ROLE into
    # a tier (WITH INHERIT FALSE — no standing privileges), fail-closed like the
    # per-guild roles.
    for role in tiers:
        connection.execute(text(f'GRANT "{base}" TO "{role}"'))
    tier_list = ", ".join(f'"{r}"' for r in tiers)
    for login_role in ("app_user", "app_admin"):
        connection.execute(
            text(
                f"""
                DO $$ BEGIN
                    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{login_role}') THEN
                        GRANT {tier_list} TO "{login_role}" WITH INHERIT FALSE;
                    END IF;
                END $$;
                """
            )
        )


# ---------------------------------------------------------------------------
# Shared public schema (frozen snapshot artifact)
# ---------------------------------------------------------------------------


def _apply_public_snapshot(connection) -> None:
    """Run the curated pg_dump snapshot: enums, the 13 shared tables with their
    indexes/constraints/sequences, shared functions (initiative_access, the
    guild_id trigger functions, reorder_guild_memberships), RLS policies,
    grants and default privileges. Platform role names in the snapshot are
    written unprefixed; substitute the active prefix before executing."""
    sql = _SNAPSHOT_SQL_PATH.read_text()
    prefix = _platform_prefix()
    if prefix:
        sql = re.sub(
            r"\bplatform_(base|member|support|moderator|admin|owner)\b",
            lambda m: prefix + m.group(0),
            sql,
        )
    # initiative_access is a LANGUAGE sql function that reads initiative_members
    # UNQUALIFIED — it resolves in the caller's routed guild schema at call
    # time, so its body cannot validate at creation time (no such table exists
    # outside guild schemas). Transaction-local, matching pg_dump's own header.
    connection.execute(text("SET LOCAL check_function_bodies = false"))
    for statement in split_sql_statements(sql):
        connection.execute(text(statement))


def upgrade() -> None:
    connection = op.get_bind()
    _create_login_roles(connection)
    _create_support_roles(connection)
    _apply_public_snapshot(connection)


def downgrade() -> None:
    raise NotImplementedError(
        "Cannot downgrade past the v0.53.5 baseline — earlier revisions were "
        "squashed away. Restore from a backup instead."
    )
