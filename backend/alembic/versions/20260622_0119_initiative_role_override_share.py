"""Add "Full access" (override_share_restrictions) to initiative_roles.

A single boolean on ``initiative_roles``. A role with it set lets its members
view/edit ALL content in the initiative regardless of how each item is shared,
and manage sharing — the gate-4 (DAC) override, scoped to one initiative (the
initiative-scoped sibling of the guild-admin override). Off by default; only a
guild admin may turn it on, and only on the built-in project_manager role.

``initiative_roles`` is a structural guild-scoped table, so the column is added
to ``public`` (the reflection source for guild_schema.sql) AND every existing
``guild_*`` schema — the generated guild_schema.sql only
``CREATE TABLE IF NOT EXISTS`` (a no-op on existing tables), so the new column
reaches existing guilds only via this explicit ALTER. New guilds pick it up from
the regenerated guild_schema.sql. No RLS change: structural initiative tables
carry no initiative-member policies, and the override is enforced in the DAC
engine (app layer), not RLS. See history/initiative-admin-override-design.md.

Revision ID: 20260622_0119
Revises: 20260622_0118
Create Date: 2026-06-22
"""

from alembic import op
from sqlalchemy import text

revision = "20260622_0119"
down_revision = "20260622_0118"
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
            "ALTER TABLE initiative_roles "
            "ADD COLUMN IF NOT EXISTS override_share_restrictions "
            "BOOLEAN NOT NULL DEFAULT FALSE"
        )
    )


def _revert(conn) -> None:
    conn.execute(
        text(
            "ALTER TABLE initiative_roles "
            "DROP COLUMN IF EXISTS override_share_restrictions"
        )
    )


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
