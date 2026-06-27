"""Backfill a missing owner grant for every DAC resource that lacks one.

Every shareable resource (project, document, queue, counter_group, calendar_event)
takes its owner from a ``level='owner'`` row in ``resource_grants``. The original
consolidation backfill (20260616_0115) was meant to carry the legacy owners across,
but it read the source tables with no RLS context set. Those tables carry
``FORCE ROW LEVEL SECURITY``, so under any migration role that does NOT bypass RLS
(typical of managed Postgres — the admin role has CREATEROLE/CREATEDB but not
``rolsuper``/``rolbypassrls``) the policies evaluated false for every row and the
``SELECT`` returned nothing. 0115 had no row-count guard and used
``ON CONFLICT DO NOTHING``, so it silently copied zero rows — then 20260616_0116
dropped the legacy ``*_permissions`` tables. On those deployments the owner grants
(and every per-user/per-role sharing grant) were lost.

The sharing grants are unrecoverable (no surviving source), but ownership can be
rebuilt from each table's surviving owner column: ``projects.owner_id`` and
``created_by_id`` on the rest. (Tasks are intentionally excluded — they are not a
DAC resource; their access inherits from the parent project.)

Robustness against a repeat of 0115: this migration sets
``app.current_guild_role = 'admin'`` first. ``public.initiative_access`` short-circuits
true on that leg, so the PERMISSIVE policies on the content tables AND on
``resource_grants`` admit every row regardless of whether the migration role carries
BYPASSRLS — the reads and writes below cannot silently no-op.

Idempotent and additive: only resources with no owner grant are touched; resources
that already have an owner (any user) are left alone, and if the owner already holds
a non-owner grant it is promoted (the unique grantee key excludes ``level``).

Revision ID: 20260626_0125
Revises: 20260624_0124
Create Date: 2026-06-26
"""

from alembic import op
from sqlalchemy import text

revision = "20260626_0125"
down_revision = "20260624_0124"
branch_labels = None
depends_on = None

# (resource_type, table, owner column). Projects carry a dedicated owner_id; the
# rest derive ownership from their creator.
_RESOURCES = [
    ("project", "projects", "owner_id"),
    ("document", "documents", "created_by_id"),
    ("queue", "queues", "created_by_id"),
    ("counter_group", "counter_groups", "created_by_id"),
    ("calendar_event", "calendar_events", "created_by_id"),
]


def _guild_schemas(conn) -> list[str]:
    rows = conn.execute(
        text("SELECT nspname FROM pg_namespace WHERE nspname LIKE 'guild\\_%'")
    ).all()
    return [r[0] for r in rows]


def _backfill(conn) -> None:
    for rtype, table, owner_col in _RESOURCES:
        conn.execute(
            text(
                f"""
                INSERT INTO resource_grants
                    (guild_id, initiative_id, resource_type, resource_id, user_id, level, created_at)
                SELECT r.guild_id, r.initiative_id, '{rtype}', r.id, r.{owner_col},
                       'owner', r.created_at
                FROM {table} r
                WHERE NOT EXISTS (
                    SELECT 1 FROM resource_grants rg
                    WHERE rg.resource_type = '{rtype}'
                      AND rg.resource_id = r.id
                      AND rg.level = 'owner'
                )
                ON CONFLICT ON CONSTRAINT resource_grants_unique_grantee
                DO UPDATE SET level = 'owner'
                """
            )
        )


def upgrade() -> None:
    conn = op.get_bind()
    # Satisfy the FORCE-RLS initiative_member policies via the guild-admin leg so the
    # reads/writes below see every row even when the migration role lacks BYPASSRLS.
    conn.execute(text("SELECT set_config('app.current_guild_role', 'admin', false)"))
    try:
        for schema in _guild_schemas(conn):
            conn.execute(text(f'SET search_path TO "{schema}", public'))
            _backfill(conn)
    finally:
        conn.execute(text("SET search_path TO public"))
        conn.execute(text("SELECT set_config('app.current_guild_role', '', false)"))


def downgrade() -> None:
    # Not safely reversible: a backfilled owner grant is indistinguishable from one
    # created normally, so there is nothing specific to undo.
    pass
