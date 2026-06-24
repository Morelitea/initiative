"""Add content_type and content_hash to uploads.

Records the MIME type and a SHA-256 of the stored bytes at upload time, so
serving can set ``Content-Type`` without sniffing (and a future object-store
backend can set it on the object), and blobs can be integrity-checked during the
eventual migration / deduped later.

``uploads`` is a guild-scoped table, so the columns are added to ``public`` (the
reflection source for guild_schema.sql) AND every existing ``guild_*`` schema —
the generated guild_schema.sql only ``CREATE TABLE IF NOT EXISTS`` (a no-op on
existing tables), so existing guilds get the columns only via this explicit
ALTER. New guilds pick them up from the regenerated guild_schema.sql. Both
columns are nullable: existing rows stay NULL and are backfilled lazily / during
the object-store migration. Mirrors 20260624_0122.

Revision ID: 20260624_0124
Revises: 20260624_0123
Create Date: 2026-06-24
"""

from alembic import op
from sqlalchemy import text

revision = "20260624_0124"
down_revision = "20260624_0123"
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
        text("ALTER TABLE uploads ADD COLUMN IF NOT EXISTS content_type VARCHAR(255)")
    )
    conn.execute(
        text("ALTER TABLE uploads ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)")
    )


def _revert(conn) -> None:
    conn.execute(text("ALTER TABLE uploads DROP COLUMN IF EXISTS content_hash"))
    conn.execute(text("ALTER TABLE uploads DROP COLUMN IF EXISTS content_type"))


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
