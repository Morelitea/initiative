"""Add is_archived to initiatives (hide from sidebar without deleting).

A single boolean on ``initiatives``. When set, the initiative stays fully
intact (it is NOT soft-deleted) but is hidden from the main sidebar for every
member; a guild admin manages it from the guild settings "Initiatives" tab. It
is a visibility flag, not an access boundary.

``initiatives`` is a structural guild-scoped table, so the column is added to
``public`` (the reflection source for guild_schema.sql) AND every existing
``guild_*`` schema — the generated guild_schema.sql only
``CREATE TABLE IF NOT EXISTS`` (a no-op on existing tables), so the new column
reaches existing guilds only via this explicit ALTER. New guilds pick it up from
the regenerated guild_schema.sql. No RLS change: structural initiative tables
carry no initiative-member policies, and visibility is filtered in the app
layer, not RLS. Mirrors 20260622_0119 (override_share_restrictions).

Revision ID: 20260624_0122
Revises: 20260623_0121
Create Date: 2026-06-24
"""

from alembic import op
from sqlalchemy import text

revision = "20260624_0122"
down_revision = "20260623_0121"
branch_labels = None
depends_on = None


def _guild_schemas(conn) -> list[str]:
    # Matches every guild_<id> AND guild_template.
    rows = conn.execute(
        text("SELECT nspname FROM pg_namespace WHERE nspname LIKE 'guild\\_%'")
    ).all()
    return [r[0] for r in rows]


def _apply(conn) -> None:
    conn.execute(
        text(
            "ALTER TABLE initiatives "
            "ADD COLUMN IF NOT EXISTS is_archived "
            "BOOLEAN NOT NULL DEFAULT FALSE"
        )
    )


def _revert(conn) -> None:
    conn.execute(text("ALTER TABLE initiatives DROP COLUMN IF EXISTS is_archived"))


def upgrade() -> None:
    conn = op.get_bind()
    for schema in _guild_schemas(conn):
        conn.execute(text(f'SET search_path TO "{schema}", public'))
        _apply(conn)
    conn.execute(text("SET search_path TO public"))
    _apply(conn)


def downgrade() -> None:
    conn = op.get_bind()
    for schema in _guild_schemas(conn):
        conn.execute(text(f'SET search_path TO "{schema}", public'))
        _revert(conn)
    conn.execute(text("SET search_path TO public"))
    _revert(conn)
