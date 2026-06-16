"""Re-apply the /uploads/{guild_id}/ rewrite that 20260613_0103 missed

20260613_0103 rewrote stored ``/uploads/{filename}`` URLs to
``/uploads/{guild_id}/{filename}`` but ONLY in ``guild_<id>`` schemas. On an
upgrade from a pre-schema-per-guild release those schemas do not yet exist when
migrations run — they are created later in ``main.on_startup`` by
``convert_public_to_guild_schemas`` / ``backfill_guild_schemas``, which run
AFTER ``alembic upgrade head``. So 0103 saw zero guild schemas and was a no-op,
and the conversion then copied the still-old-format URLs out of ``public`` into
the guild schemas. Result: every stored ``/uploads/`` URL (document
``file_url``, ``featured_image_url``, embedded rich-text/JSONB images, and
task/project/initiative/comment/calendar descriptions) kept the prefix-less form
and now 404s, because media is served at ``/uploads/{guild_id}/{filename}``.

This migration fixes both populations and is safe regardless of conversion state
(it also runs before conversion on every boot):

* ``public.*`` — rewrite per-row using each row's own ``guild_id`` column, so a
  guild NOT yet converted (e.g. a v0.50 -> this-version direct upgrade) is copied
  into its schema already in the new format.
* ``guild_<id>.*`` — rewrite in place using the gid parsed from the schema name,
  so a deployment already converted under v0.51.0 (old-format rows sitting in its
  guild schemas) is healed.

Idempotent: matches only the OLD form — ``/uploads/`` immediately followed by the
32-hex upload filename, with NO guild segment in between — so already-migrated
rows and re-runs are no-ops.

Revision ID: 20260615_0105
Revises: 20260613_0104
Create Date: 2026-06-15
"""

import sqlalchemy as sa
from alembic import op

revision = "20260615_0105"
down_revision = "20260613_0104"
branch_labels = None
depends_on = None

# /uploads/ followed by the 32-hex upload filename (uuid4().hex), with NO
# {guild_id}/ segment in front of it. Capturing the hex lets us re-emit it after
# the injected guild path. Plain (non-f) strings so the ``{32}`` quantifier
# survives string interpolation into the SQL.
_OLD = "/uploads/([0-9a-fA-F]{32})"
_DOWN = "/uploads/[0-9]+/([0-9a-fA-F]{32})"

# Per-guild-scoped columns that may hold direct or embedded /uploads URLs. Mirror
# of 20260613_0103's maps. Every one of these tables also carries a ``guild_id``
# column in ``public`` (the pre-cutover RLS model), which the public rewrite uses.
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
_ALL_TABLES = sorted(set(_TEXT_COLS) | set(_JSONB_COLS))


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


def _rewrite_table(conn, schema, table, *, pattern, repl_expr, extra_where=None):
    """``UPDATE schema.table`` applying ``regexp_replace(col, pattern, repl_expr,
    'g')`` to every targeted column. ``repl_expr`` is the SQL *replacement
    expression* (already quoted): a literal ``'/uploads/7/\\1'`` for a guild
    schema, or the per-row ``'/uploads/' || guild_id::text || '/\\1'`` for public.
    ``extra_where`` AND-guards the URL-match predicate (e.g. ``guild_id IS NOT
    NULL`` so a NULL guild_id can't ``||``-propagate the column to NULL)."""
    text_cols = _TEXT_COLS.get(table, [])
    jsonb_cols = _JSONB_COLS.get(table, [])
    sets = [
        f"{c} = regexp_replace({c}, '{pattern}', {repl_expr}, 'g')" for c in text_cols
    ]
    sets += [
        f"{c} = regexp_replace({c}::text, '{pattern}', {repl_expr}, 'g')::jsonb"
        for c in jsonb_cols
    ]
    wheres = [f"{c} ~ '{pattern}'" for c in text_cols]
    wheres += [f"{c}::text ~ '{pattern}'" for c in jsonb_cols]
    if not sets:
        return
    where = f"({' OR '.join(wheres)})"
    if extra_where:
        where += f" AND {extra_where}"
    conn.execute(
        sa.text(f'UPDATE "{schema}".{table} SET {", ".join(sets)} WHERE {where}')
    )


def _rewrite_public(conn, *, pattern, repl_expr, extra_where=None):
    # Public copies may already be gone in a later phase (see guild_conversion):
    # guard each table so a dropped backup is a skip, not an error.
    for table in _ALL_TABLES:
        if _table_exists(conn, "public", table):
            _rewrite_table(
                conn,
                "public",
                table,
                pattern=pattern,
                repl_expr=repl_expr,
                extra_where=extra_where,
            )


def _rewrite_guild_schemas(conn, *, pattern, repl_expr_for):
    for schema in _guild_schemas(conn):
        gid = int(schema.split("_", 1)[1])
        for table in _ALL_TABLES:
            if _table_exists(conn, schema, table):
                _rewrite_table(
                    conn, schema, table, pattern=pattern, repl_expr=repl_expr_for(gid)
                )


def upgrade() -> None:
    conn = op.get_bind()
    # public: per-row gid from the row's own guild_id column. ``::text`` makes the
    # concat explicit, and ``guild_id IS NOT NULL`` keeps a NULL gid (nullable on
    # comments/document_file_versions) from ``||``-nulling an otherwise-matching
    # URL — such a row is never copied into a guild schema anyway.
    _rewrite_public(
        conn,
        pattern=_OLD,
        repl_expr="'/uploads/' || guild_id::text || '/\\1'",
        extra_where="guild_id IS NOT NULL",
    )
    # guild schemas: gid is a constant parsed from the schema name.
    _rewrite_guild_schemas(
        conn, pattern=_OLD, repl_expr_for=lambda gid: f"'/uploads/{gid}/\\1'"
    )


def downgrade() -> None:
    conn = op.get_bind()
    # Strip the {guild_id}/ segment back out (constant replacement either way).
    _rewrite_public(conn, pattern=_DOWN, repl_expr="'/uploads/\\1'")
    _rewrite_guild_schemas(
        conn, pattern=_DOWN, repl_expr_for=lambda _gid: "'/uploads/\\1'"
    )
