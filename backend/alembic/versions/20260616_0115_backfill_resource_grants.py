"""Backfill resource_grants from the per-resource *_permissions tables.

Copies every existing user/role grant for projects, documents, queues and counter
groups into the polymorphic resource_grants table, in each guild schema. Idempotent
(ON CONFLICT DO NOTHING) and additive — the old tables stay authoritative until the
engine switch + drop.

Calendar events had no per-event permission table before this PR — every initiative
member could see all events by virtue of membership. Now that events are DAC-gated
like the other tools, pre-existing events would become invisible to non-admins. So
we seed default grants for every existing event matching what ``create_calendar_event``
now writes for new events: the creator owns it, and each initiative role gets write
(managers) or read (everyone else) so events stay member-visible by default.

Revision ID: 20260616_0115
Revises: 20260616_0114
Create Date: 2026-06-16
"""

from alembic import op
from sqlalchemy import text

revision = "20260616_0115"
down_revision = "20260616_0114"
branch_labels = None
depends_on = None

# (resource_type, parent table, user-grant table, role-grant table, fk column)
_RESOURCES = [
    (
        "project",
        "projects",
        "project_permissions",
        "project_role_permissions",
        "project_id",
    ),
    (
        "document",
        "documents",
        "document_permissions",
        "document_role_permissions",
        "document_id",
    ),
    ("queue", "queues", "queue_permissions", "queue_role_permissions", "queue_id"),
    (
        "counter_group",
        "counter_groups",
        "counter_group_permissions",
        "counter_group_role_permissions",
        "counter_group_id",
    ),
]


def _guild_schemas(conn) -> list[str]:
    rows = conn.execute(
        text("SELECT nspname FROM pg_namespace WHERE nspname LIKE 'guild\\_%'")
    ).all()
    return [r[0] for r in rows]


def _backfill(conn) -> None:
    for rtype, parent, user_tbl, role_tbl, fk in _RESOURCES:
        conn.execute(
            text(
                f"""
                INSERT INTO resource_grants
                    (guild_id, initiative_id, resource_type, resource_id, user_id, level, created_at)
                SELECT up.guild_id, p.initiative_id, '{rtype}', up.{fk}, up.user_id,
                       up.level::text, up.created_at
                FROM {user_tbl} up JOIN {parent} p ON p.id = up.{fk}
                ON CONFLICT DO NOTHING
                """
            )
        )
        conn.execute(
            text(
                f"""
                INSERT INTO resource_grants
                    (guild_id, initiative_id, resource_type, resource_id, role_id, level, created_at)
                SELECT rp.guild_id, p.initiative_id, '{rtype}', rp.{fk}, rp.initiative_role_id,
                       rp.level::text, rp.created_at
                FROM {role_tbl} rp JOIN {parent} p ON p.id = rp.{fk}
                ON CONFLICT DO NOTHING
                """
            )
        )


def _backfill_calendar_events(conn) -> None:
    """Seed default grants for pre-existing calendar events (no legacy table to
    copy from). Mirrors ``create_calendar_event``: creator owns the event, every
    initiative role gets write (managers) or read (everyone else)."""
    # Creator → owner.
    conn.execute(
        text(
            """
            INSERT INTO resource_grants
                (guild_id, initiative_id, resource_type, resource_id, user_id, level, created_at)
            SELECT ce.guild_id, ce.initiative_id, 'calendar_event', ce.id,
                   ce.created_by_id, 'owner', ce.created_at
            FROM calendar_events ce
            ON CONFLICT DO NOTHING
            """
        )
    )
    # Each initiative role → write (managers) / read (others).
    conn.execute(
        text(
            """
            INSERT INTO resource_grants
                (guild_id, initiative_id, resource_type, resource_id, role_id, level, created_at)
            SELECT ce.guild_id, ce.initiative_id, 'calendar_event', ce.id, ir.id,
                   CASE WHEN ir.is_manager THEN 'write' ELSE 'read' END, ce.created_at
            FROM calendar_events ce
            JOIN initiative_roles ir ON ir.initiative_id = ce.initiative_id
            ON CONFLICT DO NOTHING
            """
        )
    )


def upgrade() -> None:
    conn = op.get_bind()
    for schema in _guild_schemas(conn):
        conn.execute(text(f'SET search_path TO "{schema}", public'))
        _backfill(conn)
        _backfill_calendar_events(conn)
    conn.execute(text("SET search_path TO public"))


def downgrade() -> None:
    # The grants also exist in the old tables; safe to clear the backfilled copies.
    conn = op.get_bind()
    for schema in _guild_schemas(conn):
        conn.execute(text(f'SET search_path TO "{schema}", public'))
        conn.execute(text("DELETE FROM resource_grants"))
    conn.execute(text("SET search_path TO public"))
