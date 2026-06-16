"""Re-introduce initiative-level RLS inside guild schemas via one access function.

The schema-per-guild cutover dropped the in-schema initiative-membership RLS,
leaving scoping enforced only in app code. This restores a fail-closed DB
backstop **and** unifies the rule into a single source of truth:

* ``public.initiative_access(initiative_id, user_id, need_write)`` — the one
  predicate (initiative member OR guild admin OR PAM grant). It is deliberately
  NOT ``SECURITY DEFINER`` and pins NO ``search_path``, so the unqualified
  ``initiative_members`` resolves in the CALLER's search_path (= the routed
  ``guild_<id>, public``) — i.e. the guild-local table, not the frozen public
  copy. It reads the request GUCs set by ``set_rls_context``.
* Per-guild policies (``alembic/guild/guild_rls.sql``) on the 31 initiative-scoped
  tables, each a thin wrapper that resolves the table's initiative id and defers
  to the function. The app-layer clause builders (``membership.py``) call the same
  function, so there is one rule, not RLS + a separate Python copy.

This migration creates the function and applies the policies to ``guild_template``
(if present) and every existing ``guild_<id>`` schema. New guilds get them via
``provision_guild_schema`` (``apply_guild_rls``); ``backfill_guild_schemas`` on
boot re-asserts them idempotently.

Revision ID: 20260616_0110
Revises: 20260616_0109
Create Date: 2026-06-16
"""

import re
from pathlib import Path

from alembic import op
from sqlalchemy import text

revision = "20260616_0110"
down_revision = "20260616_0109"
branch_labels = None
depends_on = None

_GUILD_RLS_SQL = (
    Path(__file__).resolve().parents[2] / "alembic" / "guild" / "guild_rls.sql"
).read_text()

# The single source of truth for initiative access. Plain (NOT SECURITY DEFINER —
# no RLS bypass) and with NO `SET search_path`, so the unqualified initiative_members
# resolves in the CALLER's routed guild schema. STABLE; reads the request GUCs.
# NOTE: initiative_members itself must NOT carry an initiative_access policy, or
# this function's read of it would re-trigger that policy → infinite recursion.
_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION public.initiative_access(
    p_initiative_id integer,
    p_user_id integer,
    p_need_write boolean DEFAULT false
) RETURNS boolean
LANGUAGE sql STABLE
AS $func$
    SELECT
        current_setting('app.current_guild_role'::text, true) = 'admin'::text
        OR (CASE
              WHEN p_need_write
                THEN current_setting('app.pam_write'::text, true) = 'true'::text
              ELSE current_setting('app.pam_read'::text, true) = 'true'::text
                   OR current_setting('app.pam_write'::text, true) = 'true'::text
            END)
        OR EXISTS (
            SELECT 1 FROM initiative_members im
            WHERE im.initiative_id = p_initiative_id
              AND im.user_id = p_user_id
        )
$func$;
"""

# Tables the policies cover, parsed from the canonical SQL so the two never drift.
_TABLES = re.findall(r"ALTER TABLE (\w+) ENABLE ROW LEVEL SECURITY", _GUILD_RLS_SQL)
_POLICIES = (
    "initiative_member_select",
    "initiative_member_insert",
    "initiative_member_update",
    "initiative_member_delete",
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
    then split on ';' — guild_rls.sql has no ';' inside predicates, so this is
    safe."""
    no_comments = "\n".join(
        ln for ln in sql.splitlines() if not ln.strip().startswith("--")
    )
    return [s.strip() for s in no_comments.split(";") if s.strip()]


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(text(_FUNCTION_SQL))
    statements = _statements(_GUILD_RLS_SQL)
    for schema in _guild_schemas(conn):
        conn.execute(text(f'SET search_path TO "{schema}", public'))
        for stmt in statements:
            conn.execute(text(stmt))
    conn.execute(text("SET search_path TO public"))


def downgrade() -> None:
    conn = op.get_bind()
    for schema in _guild_schemas(conn):
        conn.execute(text(f'SET search_path TO "{schema}", public'))
        for table in _TABLES:
            for policy in _POLICIES:
                conn.execute(text(f"DROP POLICY IF EXISTS {policy} ON {table}"))
            conn.execute(text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY"))
            conn.execute(text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))
    conn.execute(text("SET search_path TO public"))
    conn.execute(
        text(
            "DROP FUNCTION IF EXISTS public.initiative_access(integer, integer, boolean)"
        )
    )
