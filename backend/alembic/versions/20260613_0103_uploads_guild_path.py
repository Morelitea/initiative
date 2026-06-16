"""Rewrite stored /uploads URLs to include the guild id

Part of the path-based guild tenancy cutover (B3). Media is now served at
``/uploads/{guild_id}/{filename}`` so the URL self-describes its guild (works on
cross-guild surfaces like My Documents, where one page renders images from
several guilds). Backfill every guild schema's stored upload URLs — direct
columns and URLs embedded in rich-text/JSONB content — from the old
``/uploads/{filename}`` form to ``/uploads/{guild_id}/{filename}``.

Public tables are deliberately NOT touched: public content (e.g.
``guilds.description``) must never resolve through a guild path.

Idempotent: the rewrite matches only the OLD form — ``/uploads/`` immediately
followed by the 32-hex upload filename. The new form has ``{guild_id}/`` in
between, so re-running (or running against already-migrated rows) is a no-op.

Revision ID: 20260613_0103
Revises: 20260612_0102
Create Date: 2026-06-13
"""

import sqlalchemy as sa
from alembic import op

revision = "20260613_0103"
down_revision = "20260612_0102"
branch_labels = None
depends_on = None

# /uploads/ followed by the 32-hex upload filename (uuid4().hex). Capturing the
# hex lets us re-emit it after the injected {guild_id}/ segment. Kept as a plain
# (non-f) string so the ``{32}`` quantifier survives string interpolation.
_OLD = "/uploads/([0-9a-fA-F]{32})"
_DOWN = "/uploads/[0-9]+/([0-9a-fA-F]{32})"

# Per-guild-schema columns that may hold direct or embedded /uploads URLs.
_TEXT_COLS = {
    "documents": ["file_url", "featured_image_url"],
    "document_file_versions": ["file_url"],
    "comments": ["content"],
    "tasks": ["description"],
    "calendar_events": ["description"],
    "initiatives": ["description"],
    "projects": ["description"],
}
_JSONB_COLS = {
    "documents": ["content"],
}


def _guild_schemas(conn):
    return (
        conn.execute(
            sa.text("SELECT nspname FROM pg_namespace WHERE nspname ~ '^guild_[0-9]+$'")
        )
        .scalars()
        .all()
    )


def _table_exists(conn, schema, table):
    return (
        conn.execute(
            sa.text("SELECT to_regclass(:q)"), {"q": f'"{schema}".{table}'}
        ).scalar()
        is not None
    )


def _run(conn, *, pattern, repl_suffix):
    """Apply ``regexp_replace(col, pattern, '/uploads/{gid}/' || \\1, 'g')`` to
    every targeted column in every guild schema. ``repl_suffix`` is the part
    after ``/uploads/`` in the replacement (``{gid}/\\1`` upgrade, ``\\1`` down)."""
    for schema in _guild_schemas(conn):
        gid = int(schema.split("_", 1)[1])
        repl = "/uploads/" + repl_suffix.format(gid=gid)
        for table, cols in _TEXT_COLS.items():
            if not _table_exists(conn, schema, table):
                continue
            sets = ", ".join(
                f"{c} = regexp_replace({c}, '{pattern}', '{repl}', 'g')" for c in cols
            )
            where = " OR ".join(f"{c} ~ '{pattern}'" for c in cols)
            conn.execute(sa.text(f'UPDATE "{schema}".{table} SET {sets} WHERE {where}'))
        for table, cols in _JSONB_COLS.items():
            if not _table_exists(conn, schema, table):
                continue
            sets = ", ".join(
                f"{c} = regexp_replace({c}::text, '{pattern}', '{repl}', 'g')::jsonb"
                for c in cols
            )
            where = " OR ".join(f"{c}::text ~ '{pattern}'" for c in cols)
            conn.execute(sa.text(f'UPDATE "{schema}".{table} SET {sets} WHERE {where}'))


def upgrade() -> None:
    _run(op.get_bind(), pattern=_OLD, repl_suffix="{gid}/\\1")


def downgrade() -> None:
    # Strip the {guild_id}/ segment back out.
    _run(op.get_bind(), pattern=_DOWN, repl_suffix="\\1")
