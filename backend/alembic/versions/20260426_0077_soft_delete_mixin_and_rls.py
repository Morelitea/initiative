"""Add soft-delete columns + RLS DELETE deny across user-facing entities.

Adds the trash-can lifecycle columns (``deleted_at`` / ``deleted_by`` / ``purge_at``)
to nine guild-scoped entity tables, plus partial indexes for the active-row hot
path and the auto-purge job. Adds a RESTRICTIVE FOR DELETE policy on each table
that admits only sessions whose ``app.current_guild_role`` is ``admin`` (or
superadmin). The ``app_admin`` role bypasses RLS entirely so the auto-purge
worker is unaffected.

Also adds ``retention_days`` to ``guild_settings`` (default 90, NULL means
"never auto-purge").

Revision ID: 20260426_0077
Revises: 20260424_0076
Create Date: 2026-04-26
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text


revision = "20260426_0077"
down_revision = "20260424_0076"
branch_labels = None
depends_on = None


# Tables that get the soft-delete mixin columns and the RESTRICTIVE DELETE
# policy. Order matters only for index naming consistency.
SOFT_DELETE_TABLES: list[str] = [
    "projects",
    "tasks",
    "documents",
    "comments",
    "initiatives",
    "tags",
    "queues",
    "queue_items",
    "calendar_events",
]


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Mixin columns on each entity table.
    for tname in SOFT_DELETE_TABLES:
        op.add_column(
            tname,
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.add_column(
            tname,
            sa.Column("deleted_by", sa.Integer, nullable=True),
        )
        op.add_column(
            tname,
            sa.Column("purge_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_foreign_key(
            f"fk_{tname}_deleted_by_user",
            tname,
            "users",
            ["deleted_by"],
            ["id"],
            ondelete="SET NULL",
        )

        # Active-row partial index — speeds up the default "WHERE deleted_at
        # IS NULL" filter that with_loader_criteria injects on every query.
        conn.execute(text(
            f"CREATE INDEX ix_{tname}_active "
            f"ON {tname} (deleted_at) WHERE deleted_at IS NULL"
        ))

        # Purge-job partial index — only stamped rows are interesting here.
        conn.execute(text(
            f"CREATE INDEX ix_{tname}_purge "
            f"ON {tname} (purge_at) WHERE purge_at IS NOT NULL"
        ))

        # RESTRICTIVE DELETE policy. Pattern matches users_no_delete from
        # 20260424_0076: an in-app session running as app_user must have
        # app.current_guild_role='admin' (or app.is_superadmin='true') to
        # issue a DELETE. The auto-purge worker uses app_admin (BYPASSRLS),
        # so it is unaffected.
        conn.execute(text(
            f"CREATE POLICY {tname}_delete_admin_only ON {tname} "
            f"AS RESTRICTIVE FOR DELETE "
            f"USING ("
            f"    current_setting('app.current_guild_role', true) = 'admin' "
            f"    OR current_setting('app.is_superadmin', true) = 'true'"
            f")"
        ))

    # 2. Per-guild retention_days on guild_settings. NULL = never auto-purge.
    op.add_column(
        "guild_settings",
        sa.Column(
            "retention_days",
            sa.Integer,
            nullable=True,
            server_default="90",
        ),
    )


def downgrade() -> None:
    conn = op.get_bind()

    op.drop_column("guild_settings", "retention_days")

    for tname in SOFT_DELETE_TABLES:
        conn.execute(text(f"DROP POLICY IF EXISTS {tname}_delete_admin_only ON {tname}"))
        conn.execute(text(f"DROP INDEX IF EXISTS ix_{tname}_purge"))
        conn.execute(text(f"DROP INDEX IF EXISTS ix_{tname}_active"))
        op.drop_constraint(f"fk_{tname}_deleted_by_user", tname, type_="foreignkey")
        op.drop_column(tname, "purge_at")
        op.drop_column(tname, "deleted_by")
        op.drop_column(tname, "deleted_at")
