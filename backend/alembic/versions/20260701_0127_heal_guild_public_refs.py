"""Heal every guild schema of legacy references into ``public``; drop dead objects.

The fresh-install audit that accompanied the v0.53.5 squash found the legacy
``public`` schema carrying objects that fresh installs no longer create. One
local database proves nothing about the fleet: self-hosted deployments have
guild schemas provisioned at many different points in history, so this
migration re-runs the audit's *repairs* against **every** ``guild_<id>`` schema
(and ``guild_template``) wherever it runs. All checks are query-driven, so it
is a complete no-op on fresh installs and on healthy guilds.

Per guild schema:

1. **Sequence defaults** — any column default whose sequence lives OUTSIDE the
   schema (e.g. ``nextval('public.tasks_id_seq')``) is re-pointed to a
   schema-local sequence: created if missing, advanced to
   ``GREATEST(max(column), its current position)`` so ids can never collide,
   ownership fixed. The boot back-fill can't heal this (``CREATE TABLE IF NOT
   EXISTS`` never touches an existing table), and the future drop of the frozen
   public copies would break inserts for any guild left pointing at them.
2. **Cross-schema FKs** — an FK from a guild table to a frozen public copy is
   dropped (cross-schema refs are soft by design; the guild-local FK from
   ``guild_schema.sql`` still holds).

Once per database:

3. **Dead public objects** — the 4 enums and 2 trigger functions orphaned when
   the legacy per-resource permission tables were dropped (old migration 0116)
   are removed. The future drop of the frozen copies would NOT remove these
   (they are attached to nothing), so they are cleaned here. ``DROP …
   IF EXISTS`` without CASCADE: if anything unexpectedly references one, this
   fails loudly instead of silently severing it.

Revision ID: 20260701_0127
Revises: 20260701_0126
Create Date: 2026-07-01
"""

from alembic import op
from sqlalchemy import text

from app.db.guild_migrations import guild_schema_names

revision = "20260701_0127"
down_revision = "20260701_0126"
branch_labels = None
depends_on = None

# The guild-content tables frozen in ``public`` at squash time — same immutable
# record as in 20260701_0126 (migrations don't import each other).
_LEGACY_PUBLIC_GUILD_TABLES = (
    "calendar_event_attendees",
    "calendar_event_documents",
    "calendar_event_property_values",
    "calendar_event_tags",
    "calendar_events",
    "comments",
    "counter_groups",
    "counters",
    "document_file_versions",
    "document_links",
    "document_property_values",
    "document_tags",
    "documents",
    "event_reminder_dispatches",
    "guild_settings",
    "initiative_members",
    "initiative_role_permissions",
    "initiative_roles",
    "initiatives",
    "project_documents",
    "project_favorites",
    "project_orders",
    "project_tags",
    "projects",
    "property_definitions",
    "queue_item_documents",
    "queue_item_tags",
    "queue_item_tasks",
    "queue_items",
    "queues",
    "recent_views",
    "resource_grants",
    "subtasks",
    "tags",
    "task_assignees",
    "task_assignment_digest_items",
    "task_property_values",
    "task_statuses",
    "task_tags",
    "tasks",
    "uploads",
    "webhook_subscriptions",
)

# Orphans of the legacy per-resource permission tables (dropped by old 0116).
_DEAD_FUNCTIONS = (
    "fn_document_permissions_set_guild_id",
    "fn_project_permissions_set_guild_id",
)
_DEAD_ENUMS = (
    "counter_permission_level",
    "document_permission_level",
    "project_permission_level",
    "queue_permission_level",
)


def _heal_sequence_defaults(conn, schema: str) -> None:
    """Re-point column defaults that use a sequence outside ``schema`` to a
    schema-local sequence, without ever rewinding a sequence."""
    # pg_depend ties a column default (pg_attrdef) to the sequence its nextval
    # references — authoritative, no expression parsing. Schema names come from
    # pg_namespace and identifiers from the catalogs, so they're safe to quote.
    rows = conn.execute(
        text(
            """
            SELECT c.relname AS tbl, a.attname AS col,
                   sn.nspname AS seq_schema, s.relname AS seq
            FROM pg_attrdef ad
            JOIN pg_class c ON c.oid = ad.adrelid
            JOIN pg_namespace cn ON cn.oid = c.relnamespace AND cn.nspname = :schema
            JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ad.adnum
            JOIN pg_depend d ON d.classid = 'pg_attrdef'::regclass
                            AND d.objid = ad.oid
                            AND d.refclassid = 'pg_class'::regclass
            JOIN pg_class s ON s.oid = d.refobjid AND s.relkind = 'S'
            JOIN pg_namespace sn ON sn.oid = s.relnamespace
            WHERE sn.nspname <> :schema
            """
        ),
        {"schema": schema},
    ).fetchall()

    for tbl, col, seq_schema, seq in rows:
        local_seq = f"{tbl}_{col}_seq"
        qseq = f'"{schema}"."{local_seq}"'
        conn.execute(text(f"CREATE SEQUENCE IF NOT EXISTS {qseq} AS integer"))
        # Never rewind: advance to the max of the column's ids and wherever the
        # local sequence already is (it may exist and be live).
        conn.execute(
            text(
                f"SELECT setval('{qseq}', GREATEST("
                f'(SELECT COALESCE(max("{col}"), 0) FROM "{schema}"."{tbl}"), '
                f"(SELECT last_value FROM {qseq}), 1))"
            )
        )
        conn.execute(
            text(
                f'ALTER TABLE "{schema}"."{tbl}" ALTER COLUMN "{col}" '
                f"SET DEFAULT nextval('{qseq}'::regclass)"
            )
        )
        conn.execute(text(f'ALTER SEQUENCE {qseq} OWNED BY "{schema}"."{tbl}"."{col}"'))
        print(
            f"  healed {schema}.{tbl}.{col}: default was {seq_schema}.{seq}, "
            f"now {schema}.{local_seq}"
        )


def _drop_cross_schema_fks(conn, schema: str) -> None:
    """Drop FKs from ``schema``'s tables to the frozen public guild copies."""
    rows = conn.execute(
        text(
            """
            SELECT con.conname, cl.relname AS tbl
            FROM pg_constraint con
            JOIN pg_class cl ON cl.oid = con.conrelid
            JOIN pg_namespace cn ON cn.oid = cl.relnamespace AND cn.nspname = :schema
            JOIN pg_class tgt ON tgt.oid = con.confrelid
            JOIN pg_namespace tn ON tn.oid = tgt.relnamespace AND tn.nspname = 'public'
            WHERE con.contype = 'f' AND tgt.relname = ANY(:legacy)
            """
        ),
        {"schema": schema, "legacy": list(_LEGACY_PUBLIC_GUILD_TABLES)},
    ).fetchall()
    for conname, tbl in rows:
        conn.execute(
            text(f'ALTER TABLE "{schema}"."{tbl}" DROP CONSTRAINT "{conname}"')
        )
        print(f"  dropped cross-schema FK {schema}.{tbl}.{conname} -> public")


def upgrade() -> None:
    conn = op.get_bind()
    for schema in guild_schema_names(conn):
        _heal_sequence_defaults(conn, schema)
        _drop_cross_schema_fks(conn, schema)

    for fn in _DEAD_FUNCTIONS:
        conn.execute(text(f"DROP FUNCTION IF EXISTS public.{fn}()"))
    for enum in _DEAD_ENUMS:
        conn.execute(text(f"DROP TYPE IF EXISTS public.{enum}"))


def downgrade() -> None:
    # Healing/cleanup only: re-breaking sequence defaults or resurrecting dead
    # enums has no value and no faithful inverse — roll forward only.
    raise NotImplementedError(
        "20260701_0127 heals legacy state; there is nothing to restore."
    )
