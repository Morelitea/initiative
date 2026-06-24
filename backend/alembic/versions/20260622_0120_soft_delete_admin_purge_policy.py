"""Admin-only hard-delete (purge) RESTRICTIVE policy on soft-delete tables.

Hard delete == purge, and only a guild admin may purge. The interactive purge
endpoint already 403s a non-admin, and the background auto-purge worker runs as
``app_admin`` (BYPASSRLS), so RLS does not touch it. This adds the missing
DB-layer backstop: a RESTRICTIVE FOR DELETE policy (``soft_delete_admin_purge``)
admitting only a routed guild admin (``app.current_guild_role = 'admin'``) on
every initiative-scoped soft-delete table.

It is RESTRICTIVE, so it AND-combines with the PERMISSIVE ``initiative_member_delete``
policy — a write-member clears the permissive leg but is still refused by this
one. (The original RESTRICTIVE delete guard from 20260426_0078 lived on the now-
inert ``public`` table copies and was never carried onto the per-guild schemas
during the schema-per-guild cutover; this restores that intent on the request
path, generated from a single source.)

The guard covers **every** soft-delete table. The initiative-scoped ones already
have RLS (for the membership gate), so the RESTRICTIVE policy is just appended.
The two guild-level soft-delete tables (``initiatives``, ``tags``) are RLS-free,
so they get RLS ENABLED solely to host the guard, with a permissive allow-all
(``guild_level_open``) — isolation stays the schema boundary and initiative
stays the gate; this is not a membership scope. (See
``history/soft-delete-purge-guard-design.md``.)

The policy set is generated into ``alembic/guild/guild_rls.sql`` by
``scripts/gen_guild_rls.py`` (from ``SOFT_DELETE_TABLES``). New guilds get it via
``provision_guild_schema`` (``apply_guild_rls``); ``backfill_guild_schemas``
re-asserts it on boot. This migration applies the regenerated file to
``guild_template`` (if present) and every existing ``guild_<id>`` so the guard
lands at deploy, not only on the next boot — mirroring 20260616_0110.

Revision ID: 20260622_0120
Revises: 20260622_0119
Create Date: 2026-06-22
"""

from pathlib import Path

from alembic import op
from sqlalchemy import text

revision = "20260622_0120"
down_revision = "20260622_0119"
branch_labels = None
depends_on = None

_GUILD_RLS_SQL_PATH = (
    Path(__file__).resolve().parents[2] / "alembic" / "guild" / "guild_rls.sql"
)

# Kept here only for the downgrade (the upgrade re-applies the whole regenerated
# file). Snapshot of SOFT_DELETE_TABLES at the time of writing.
#
# Initiative-scoped soft-delete tables: only the appended RESTRICTIVE guard is
# dropped; their initiative_member RLS predates this migration and stays.
_GUARD_TABLES = (
    "projects",
    "tasks",
    "documents",
    "comments",
    "queues",
    "queue_items",
    "calendar_events",
    "counters",
    "counter_groups",
)
# Guild-level soft-delete tables: this migration turned RLS ON to host the guard,
# so the downgrade fully reverts them (drop both policies + DISABLE RLS).
_GUILD_LEVEL_GUARD_TABLES = (
    "initiatives",
    "tags",
)


def _guild_schemas(conn) -> list[str]:
    """Every guild schema (guild_<id> and guild_template if present)."""
    return list(
        conn.execute(
            text("SELECT nspname FROM pg_namespace WHERE nspname LIKE 'guild\\_%'")
        ).scalars()
    )


def _statements(sql: str) -> list[str]:
    """Split a (dollar-quote-free) SQL file into individual statements. asyncpg's
    extended protocol rejects multi-statement strings, so each runs separately.
    Comment lines are stripped FIRST (a ``--`` comment may itself contain ';'),
    then split on ';' — guild_rls.sql has no ';' inside predicates."""
    no_comments = "\n".join(
        ln for ln in sql.splitlines() if not ln.strip().startswith("--")
    )
    return [s.strip() for s in no_comments.split(";") if s.strip()]


def upgrade() -> None:
    conn = op.get_bind()
    statements = _statements(_GUILD_RLS_SQL_PATH.read_text())
    for schema in _guild_schemas(conn):
        conn.execute(text(f'SET search_path TO "{schema}", public'))
        for stmt in statements:
            conn.execute(text(stmt))
    conn.execute(text("SET search_path TO public"))


def downgrade() -> None:
    conn = op.get_bind()
    for schema in _guild_schemas(conn):
        conn.execute(text(f'SET search_path TO "{schema}", public'))
        # Initiative-scoped tables: drop only the appended guard.
        for table in _GUARD_TABLES:
            conn.execute(
                text(f"DROP POLICY IF EXISTS soft_delete_admin_purge ON {table}")
            )
        # Guild-level tables: drop both policies and turn RLS back off (this
        # migration enabled it), restoring schema-boundary-only protection.
        for table in _GUILD_LEVEL_GUARD_TABLES:
            conn.execute(
                text(f"DROP POLICY IF EXISTS soft_delete_admin_purge ON {table}")
            )
            conn.execute(text(f"DROP POLICY IF EXISTS guild_level_open ON {table}"))
            conn.execute(text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))
    conn.execute(text("SET search_path TO public"))
