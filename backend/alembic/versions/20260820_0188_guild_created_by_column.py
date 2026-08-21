"""One name for a row's author across the guild schema

Guild-content migration.

Every guild-schema table that models something a person made now records its
author in one column, ``created_by``. It was spelled six different ways
(``author_id``, ``uploader_user_id``, ``uploaded_by_id``, ``installed_by_id``,
``created_by_user_id``, ``created_by_id``) and absent from most tables entirely,
so anything needing a row's author carried a per-table map of column names.
Every one of those columns is renamed, not recreated, so its data survives.

The ``_id`` suffix goes with them: ``created_by`` now matches ``deleted_by``,
which never had one.

``documents.updated_by_id`` is **dropped**. Who changed a row, and when, is
already captured per transaction by ``public.capture_change`` into
``event_outbox`` — with the transaction id and the names of the columns that
changed, which one mutable column could not hold. The column was written on six
paths and read on none: it was required by the read schema, so a client
assembling a document summary from another shape had to invent a value to
satisfy it. No table grows one.

A BEFORE INSERT trigger fills the column from ``app.current_user_id``, the GUC
the request already sets for RLS — the same shape as the ``fn_*_set_guild_id``
triggers beside it and the actor read in ``public.capture_change``. One shared
function serves every schema, because the column name is the same everywhere.

Junction rows, roster rows, per-user state and machinery ledgers are left alone;
``app.db.tenancy.CREATED_BY_EXEMPT_TABLES`` lists them with the reason.

The backfill fills ``created_by`` on child rows from the parent that holds one —
a subtask from its task, a property value from its entity. That is a reasonable
default, not a record: whoever made the parent is usually but not always whoever
made the child. Rows with no such parent stay NULL rather than being guessed at.

Revision ID: 20260820_0188
Revises: 20260815_0187
Create Date: 2026-08-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260820_0188"
down_revision = "20260815_0187"
branch_labels = None
depends_on = None


#: (table, old column) -> ``created_by``. Renamed in place; the values they hold
#: are the same fact under a different word.
_RENAMES: tuple[tuple[str, str], ...] = (
    ("calendar_events", "created_by_id"),
    ("calendars", "created_by_id"),
    ("comments", "author_id"),
    ("counter_groups", "created_by_id"),
    ("dashboards", "created_by_id"),
    ("document_file_versions", "uploaded_by_id"),
    ("documents", "created_by_id"),
    ("export_jobs", "created_by_id"),
    ("guild_ai_connections", "created_by_user_id"),
    ("guild_apps", "installed_by_id"),
    ("import_jobs", "created_by_id"),
    ("queues", "created_by_id"),
    ("tasks", "created_by_id"),
    ("uploads", "uploader_user_id"),
    ("webhook_subscriptions", "created_by_user_id"),
)

#: Written on six paths, read on none — and ``capture_change`` already records
#: who changed a document, with the transaction and the columns involved.
_DROPPED_UPDATED_BY = ("documents", "updated_by_id")

#: Constraints and indexes named after a renamed column. Postgres rewrites what
#: they reference on RENAME COLUMN but keeps their own name, so the name is
#: brought along by hand — as (forward, reverse) statement pairs.
_RENAMED_OBJECTS: tuple[tuple[str, str], ...] = (
    (
        "ALTER INDEX ix_comments_author_id RENAME TO ix_comments_created_by",
        "ALTER INDEX ix_comments_created_by RENAME TO ix_comments_author_id",
    ),
    *(
        (
            f"ALTER TABLE {table} RENAME CONSTRAINT "
            f"{table}_{old}_fkey TO {table}_created_by_fkey",
            f"ALTER TABLE {table} RENAME CONSTRAINT "
            f"{table}_created_by_fkey TO {table}_{old}_fkey",
        )
        for table, old in (
            ("calendars", "created_by_id"),
            ("dashboards", "created_by_id"),
            ("export_jobs", "created_by_id"),
            ("guild_ai_connections", "created_by_user_id"),
            ("guild_apps", "installed_by_id"),
            ("import_jobs", "created_by_id"),
        )
    ),
)

#: Tables gaining ``created_by`` (they recorded no author at all).
_NEW_CREATED_BY: tuple[str, ...] = (
    "calendar_event_property_values",
    "counters",
    "document_links",
    "document_property_values",
    "guild_settings",
    "initiative_roles",
    "initiatives",
    "projects",
    "property_definitions",
    "queue_items",
    "resource_grants",
    "subtasks",
    "tags",
    "task_property_values",
    "task_statuses",
)

#: Every table carrying ``created_by`` after this migration — the renames plus
#: the additions. Spelled out rather than imported: a revision has to keep doing
#: to a database exactly what it did when it was written.
_CREATED_BY_TABLES: tuple[str, ...] = tuple(
    sorted({table for table, _ in _RENAMES} | set(_NEW_CREATED_BY))
)

#: Fills ``created_by`` from the request GUC the RLS context already sets. One
#: shared function in ``public``, like ``capture_change``: the column is named
#: the same on every table, so there is nothing per-table to know.
#:
#: Only NULL is filled, so a caller that names an author explicitly — the backup
#: importer restoring original authorship — keeps it. A write with no user in
#: context (background jobs, seeding, migrations) leaves NULL, because there is
#: nobody to name. INSERT only: an author is a historical fact and is never
#: revised.
_STAMP_FUNCTION = """
CREATE OR REPLACE FUNCTION public.fn_set_created_by() RETURNS trigger
    LANGUAGE plpgsql AS $stamp$
BEGIN
    IF NEW.created_by IS NULL THEN
        NEW.created_by := NULLIF(
            current_setting('app.current_user_id', true), ''
        )::integer;
    END IF;
    RETURN NEW;
END;
$stamp$;
"""


#: child table -> (parent table, join column on the child, parent key). The
#: child's author defaults to the parent's where one exists.
_BACKFILL: tuple[tuple[str, str, str, str], ...] = (
    ("subtasks", "tasks", "task_id", "id"),
    ("counters", "counter_groups", "counter_group_id", "id"),
    ("queue_items", "queues", "queue_id", "id"),
    ("document_links", "documents", "source_document_id", "id"),
    ("document_property_values", "documents", "document_id", "id"),
    ("task_property_values", "tasks", "task_id", "id"),
    ("calendar_event_property_values", "calendar_events", "event_id", "id"),
)


def upgrade() -> None:
    # Shared, in ``public``, created once — the per-schema loop only attaches
    # triggers to it (same split as ``public.capture_change``).
    op.execute(_STAMP_FUNCTION)
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    for table, old in _RENAMES:
        op.alter_column(table, old, new_column_name="created_by")
    table, column = _DROPPED_UPDATED_BY
    op.drop_column(table, column)
    for forward, _ in _RENAMED_OBJECTS:
        op.execute(forward)

    for table in _NEW_CREATED_BY:
        op.add_column(table, sa.Column("created_by", sa.Integer(), nullable=True))

    for table in _CREATED_BY_TABLES:
        op.execute(
            f"CREATE OR REPLACE TRIGGER tr_{table}_set_created_by "
            f"BEFORE INSERT ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION public.fn_set_created_by()"
        )

    _backfill_children_from_parents()


def _backfill_children_from_parents() -> None:
    """Seed each child's ``created_by`` from the parent that has one.

    Guild content is FORCE ROW LEVEL SECURITY, which binds the owning role too,
    so a naive UPDATE here would match nothing and report success. The policies
    come off for the statement and go straight back on, and the row count is
    asserted rather than assumed.
    """
    touched = {t for row in _BACKFILL for t in (row[0], row[1])}
    for table in sorted(touched):
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    try:
        bind = op.get_bind()
        for child, parent, fk, parent_key in _BACKFILL:
            bind.execute(
                sa.text(
                    f"UPDATE {child} SET created_by = p.created_by "  # noqa: S608
                    f"FROM {parent} p "
                    f"WHERE p.{parent_key} = {child}.{fk} "
                    f"AND p.created_by IS NOT NULL "
                    f"AND {child}.created_by IS NULL"
                )
            )
            remaining = bind.execute(
                sa.text(
                    f"SELECT count(*) FROM {child} "  # noqa: S608
                    f"JOIN {parent} p ON p.{parent_key} = {child}.{fk} "
                    f"WHERE p.created_by IS NOT NULL "
                    f"AND {child}.created_by IS NULL"
                )
            ).scalar()
            if remaining:
                raise RuntimeError(
                    f"{remaining} {child} rows kept no author after the backfill "
                    f"from {parent}"
                )
    finally:
        for table in sorted(touched, reverse=True):
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def _restore_updated_by() -> None:
    """Put ``documents.updated_by_id`` back, NOT NULL as it was.

    The values it held are gone, so every row gets its author — the only
    non-arbitrary stand-in available, and true for a document nobody has edited
    since. FORCE ROW LEVEL SECURITY binds the owning role, so the UPDATE runs
    with policies off and the remaining count is asserted rather than assumed.
    """
    table, column = _DROPPED_UPDATED_BY
    op.add_column(table, sa.Column(column, sa.Integer(), nullable=True))
    op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    try:
        bind = op.get_bind()
        bind.execute(sa.text(f"UPDATE {table} SET {column} = created_by"))  # noqa: S608
        remaining = bind.execute(
            sa.text(f"SELECT count(*) FROM {table} WHERE {column} IS NULL")  # noqa: S608
        ).scalar()
        if remaining:
            raise RuntimeError(
                f"{remaining} {table} rows have no author to restore {column} from"
            )
    finally:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.alter_column(table, column, nullable=False)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)
    # Reachable only from the triggers just dropped.
    op.execute("DROP FUNCTION IF EXISTS public.fn_set_created_by()")


def _apply_downgrade() -> None:
    for table in _CREATED_BY_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS tr_{table}_set_created_by ON {table}")

    for table in _NEW_CREATED_BY:
        op.drop_column(table, "created_by")

    for _, reverse in _RENAMED_OBJECTS:
        op.execute(reverse)
    _restore_updated_by()
    for table, old in _RENAMES:
        op.alter_column(table, "created_by", new_column_name=old)
