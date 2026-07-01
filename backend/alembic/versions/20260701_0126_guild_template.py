"""Create the ``guild_template`` schema; guard the legacy data conversion.

Every code path since the schema-per-guild cutover was written for a
"``guild_template`` if present" — this migration finally creates it, on both
fresh databases (right after the squashed baseline) and existing deployments
(their first post-squash migration). The template is built by RUNNING the
canonical artifacts (``alembic/guild/guild_schema.sql`` + ``guild_rls.sql``),
exactly like a real guild schema, and from here on:

* guild-scoped migrations apply their DDL to ``guild_template`` + every
  ``guild_<id>`` (``guild_schema_names`` now matches the template) — and NOT to
  the frozen legacy ``public`` copies;
* ``scripts/gen_guild_schema.py`` reflects the template (not ``public``) when
  regenerating ``guild_schema.sql``;
* the drift guard diffs a freshly provisioned schema against the template.

**Conversion guard.** On a legacy deployment (the frozen public copies exist),
any guild that still has rows in those copies must already carry the
``schema-per-guild-converted`` marker on its ``guild_<id>`` schema — i.e. the
one-time startup conversion (removed along with this squash) must have run.
Otherwise this migration aborts with instructions to boot a v0.53.x release
once. This closes the only data-loss window: a deployment jumping many versions
without ever booting a release that performed the conversion.

Revision ID: 20260701_0126
Revises: 20260626_0125
Create Date: 2026-07-01
"""

from pathlib import Path

from alembic import op
from sqlalchemy import text

from app.db.guild_migrations import split_sql_statements

revision = "20260701_0126"
down_revision = "20260626_0125"
branch_labels = None
depends_on = None

_GUILD_DIR = Path(__file__).resolve().parents[1] / "guild"

# Marker comment the (now removed) startup conversion stamped on a guild schema
# once its public rows were fully copied in — see the deleted
# app/db/guild_conversion.py; frozen here as part of the migration record.
_CONVERSION_MARKER = "schema-per-guild-converted"

# The guild-content tables that existed in ``public`` at squash time (v0.53.5).
# Frozen: this guard reasons about the LEGACY snapshot, not about tables added
# later (which never get public copies).
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


def _assert_legacy_guilds_converted(conn) -> None:
    """Fail loudly if any guild still has unconverted rows in the frozen public
    copies. Fresh databases (no public copies) skip the whole check."""
    legacy_tables = [
        r[0]
        for r in conn.execute(
            text(
                "SELECT c.table_name FROM information_schema.columns c "
                "WHERE c.table_schema = 'public' AND c.column_name = 'guild_id' "
                "AND c.table_name = ANY(:t)"
            ),
            {"t": list(_LEGACY_PUBLIC_GUILD_TABLES)},
        )
    ]
    if not legacy_tables:
        return  # fresh install — the public copies never existed

    guild_ids: set[int] = set()
    for table in legacy_tables:
        rows = conn.execute(
            text(
                f'SELECT DISTINCT p.guild_id FROM public."{table}" p '
                "JOIN public.guilds g ON g.id = p.guild_id"
            )
        )
        guild_ids.update(r[0] for r in rows)

    unconverted = [
        gid
        for gid in sorted(guild_ids)
        if conn.execute(
            text(
                "SELECT obj_description(n.oid) FROM pg_namespace n WHERE n.nspname = :s"
            ),
            {"s": f"guild_{gid}"},
        ).scalar()
        != _CONVERSION_MARKER
    ]
    if unconverted:
        raise RuntimeError(
            "Cannot upgrade past the v0.53.5 squash: guild(s) "
            f"{unconverted} still have data in the legacy public tables but no "
            "completed schema-per-guild conversion. Deploy and boot a v0.53.x "
            "release once (its startup performs the conversion), then upgrade "
            "to this version."
        )


def _apply_artifact(conn, filename: str) -> None:
    statements = split_sql_statements((_GUILD_DIR / filename).read_text())
    for statement in statements:
        conn.execute(text(statement))


def upgrade() -> None:
    conn = op.get_bind()
    _assert_legacy_guilds_converted(conn)

    conn.execute(text('CREATE SCHEMA IF NOT EXISTS "guild_template"'))
    # Schema-relative artifacts: unqualified names resolve in the template,
    # shared types/functions fall through to public (same as provisioning).
    conn.execute(text('SET search_path TO "guild_template", public'))
    _apply_artifact(conn, "guild_schema.sql")
    _apply_artifact(conn, "guild_rls.sql")
    conn.execute(text("SET search_path TO public"))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(text('DROP SCHEMA IF EXISTS "guild_template" CASCADE'))
