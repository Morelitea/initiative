"""One spelling for authorship across the guild schema

Guild-content migration.

Every guild-schema table that models something a person wrote now records who
wrote it and who last changed it under one pair of names — ``created_by_id``
and ``updated_by_id`` — supplied by ``AuthorshipMixin``. Six tables spelled the
first half differently (``author_id``, ``uploader_user_id``, ``uploaded_by_id``,
``installed_by_id``, ``created_by_user_id``); those columns are renamed, not
recreated, so the data they hold survives.

``updated_by_id`` is new everywhere except ``documents``, which already had it.
It starts NULL and is stamped from the next write onward.

Junction rows, roster rows, per-user state and machinery ledgers are left
alone; ``app.db.tenancy.AUTHORSHIP_EXEMPT_TABLES`` lists them with the reason.

The backfill fills ``created_by_id`` on child rows from the parent that holds
one — a subtask from its task, a property value from its entity. That is a
reasonable default, not a record: whoever wrote the parent is usually but not
always whoever wrote the child. Rows with no such parent stay NULL rather than
being guessed at.

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


#: table -> (old authorship column, new name). Renamed in place; the values
#: they hold are the same fact under a different word.
_RENAMES: tuple[tuple[str, str], ...] = (
    ("comments", "author_id"),
    ("document_file_versions", "uploaded_by_id"),
    ("guild_ai_connections", "created_by_user_id"),
    ("guild_apps", "installed_by_id"),
    ("uploads", "uploader_user_id"),
    ("webhook_subscriptions", "created_by_user_id"),
)

#: Constraints and indexes named after a renamed column. Postgres rewrites what
#: they reference on RENAME COLUMN but keeps their own name, so the name is
#: brought along by hand — as (forward, reverse) statement pairs.
_RENAMED_OBJECTS: tuple[tuple[str, str], ...] = (
    (
        "ALTER INDEX ix_comments_author_id RENAME TO ix_comments_created_by_id",
        "ALTER INDEX ix_comments_created_by_id RENAME TO ix_comments_author_id",
    ),
    (
        "ALTER TABLE guild_apps RENAME CONSTRAINT "
        "guild_apps_installed_by_id_fkey TO guild_apps_created_by_id_fkey",
        "ALTER TABLE guild_apps RENAME CONSTRAINT "
        "guild_apps_created_by_id_fkey TO guild_apps_installed_by_id_fkey",
    ),
    (
        "ALTER TABLE guild_ai_connections RENAME CONSTRAINT "
        "guild_ai_connections_created_by_user_id_fkey "
        "TO guild_ai_connections_created_by_id_fkey",
        "ALTER TABLE guild_ai_connections RENAME CONSTRAINT "
        "guild_ai_connections_created_by_id_fkey "
        "TO guild_ai_connections_created_by_user_id_fkey",
    ),
)

#: Tables gaining ``created_by_id`` (they had no authorship column at all).
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

#: Tables gaining ``updated_by_id``. Everything carrying the mixin except
#: ``documents``, which has had the column since it was created.
_NEW_UPDATED_BY: tuple[str, ...] = _NEW_CREATED_BY + (
    "calendar_events",
    "calendars",
    "comments",
    "counter_groups",
    "dashboards",
    "document_file_versions",
    "export_jobs",
    "guild_ai_connections",
    "guild_apps",
    "import_jobs",
    "queues",
    "tasks",
    "uploads",
    "webhook_subscriptions",
)

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
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    for table, old in _RENAMES:
        op.alter_column(table, old, new_column_name="created_by_id")
    for forward, _ in _RENAMED_OBJECTS:
        op.execute(forward)

    for table in _NEW_CREATED_BY:
        op.add_column(table, sa.Column("created_by_id", sa.Integer(), nullable=True))
    for table in _NEW_UPDATED_BY:
        op.add_column(table, sa.Column("updated_by_id", sa.Integer(), nullable=True))

    _backfill_children_from_parents()


def _backfill_children_from_parents() -> None:
    """Seed each child's ``created_by_id`` from the parent that has one.

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
                    f"UPDATE {child} SET created_by_id = p.created_by_id "  # noqa: S608
                    f"FROM {parent} p "
                    f"WHERE p.{parent_key} = {child}.{fk} "
                    f"AND p.created_by_id IS NOT NULL "
                    f"AND {child}.created_by_id IS NULL"
                )
            )
            remaining = bind.execute(
                sa.text(
                    f"SELECT count(*) FROM {child} "  # noqa: S608
                    f"JOIN {parent} p ON p.{parent_key} = {child}.{fk} "
                    f"WHERE p.created_by_id IS NOT NULL "
                    f"AND {child}.created_by_id IS NULL"
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


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    for table in _NEW_UPDATED_BY:
        op.drop_column(table, "updated_by_id")
    for table in _NEW_CREATED_BY:
        op.drop_column(table, "created_by_id")

    for _, reverse in _RENAMED_OBJECTS:
        op.execute(reverse)
    for table, old in _RENAMES:
        op.alter_column(table, "created_by_id", new_column_name=old)
