"""Normalize backfilled calendar-event grants to all-initiative-members Viewer.

Before per-event DAC, every initiative member could see all calendar events by
virtue of membership. The ``0115`` backfill stood that up as one grant *per
initiative role* (write for managers, read for the rest), because the
``all_initiative_members`` column didn't exist yet (it arrives in ``0117``).

Functionally those per-role grants keep the events visible, but in the unified
2-mode sharing model they render as "Restricted" with every role listed instead
of "All members" — which is not their original shape. This migration restores
that shape: for every pre-existing calendar event, drop the per-role backfill
grants and seed a single ``all_initiative_members`` / ``read`` grant, exactly
what ``create_calendar_event`` now writes for new events. The creator's owner
grant is left untouched.

Revision ID: 20260622_0118
Revises: 20260617_0117
Create Date: 2026-06-22
"""

from alembic import op
from sqlalchemy import text

revision = "20260622_0118"
down_revision = "20260617_0117"
branch_labels = None
depends_on = None


def _guild_schemas(conn) -> list[str]:
    rows = conn.execute(
        text("SELECT nspname FROM pg_namespace WHERE nspname LIKE 'guild\\_%'")
    ).all()
    return [r[0] for r in rows]


def _to_all_members(conn) -> None:
    # Drop the per-role backfill grants on calendar events (the stand-in for
    # "every member can see it"); we now express that directly.
    conn.execute(
        text(
            "DELETE FROM resource_grants "
            "WHERE resource_type = 'calendar_event' AND role_id IS NOT NULL"
        )
    )
    # Seed one all-initiative-members Viewer grant per event, mirroring the
    # create flow. Creator owner grants (user_id set) are left as-is.
    conn.execute(
        text(
            """
            INSERT INTO resource_grants
                (guild_id, initiative_id, resource_type, resource_id,
                 all_initiative_members, level, created_at)
            SELECT ce.guild_id, ce.initiative_id, 'calendar_event', ce.id,
                   true, 'read', ce.created_at
            FROM calendar_events ce
            ON CONFLICT DO NOTHING
            """
        )
    )


def _to_per_role(conn) -> None:
    # Reverse: remove the all-members grants and re-seed per-role grants exactly
    # the way the 0115 backfill did (write for managers, read for everyone else).
    conn.execute(
        text(
            "DELETE FROM resource_grants "
            "WHERE resource_type = 'calendar_event' AND all_initiative_members IS TRUE"
        )
    )
    conn.execute(
        text(
            """
            INSERT INTO resource_grants
                (guild_id, initiative_id, resource_type, resource_id,
                 role_id, level, created_at)
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
        _to_all_members(conn)
    conn.execute(text("SET search_path TO public"))


def downgrade() -> None:
    conn = op.get_bind()
    for schema in _guild_schemas(conn):
        conn.execute(text(f'SET search_path TO "{schema}", public'))
        _to_per_role(conn)
    conn.execute(text("SET search_path TO public"))
