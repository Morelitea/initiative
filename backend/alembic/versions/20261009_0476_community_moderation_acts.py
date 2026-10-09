"""community moderation acts

Each guild schema gains ``moderation_actions``, the community's moderation
log. A comment can become a tombstone (``removed_at``, ``removed_reason``,
``removal_id``), and a reply no longer goes with the comment it answers: its
pointer to it lets go on delete rather than cascading, so trashing a comment
leaves its replies. Everything a thread hangs off can be locked
(``comments_locked_at``). A community report records the law an ``illegal``
report named, the platform case it was also sent to, and what settling it did.

The log's policies and its guards, and the tombstone guard on ``comments``,
are rendered by the provisioning run (``app.db.moderation_log``). The
downgrade drops the columns with whatever was rendered on them.

Revision ID: 20261009_0476
Revises: 20261009_0475
Create Date: 2026-10-09
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261009_0476"
down_revision = "20261009_0475"
branch_labels = None
depends_on = None

#: Every table a thread hangs off.
_LOCKABLE = (
    "calendars",
    "counter_groups",
    "dashboards",
    "files",
    "galleries",
    "posts",
    "projects",
    "queues",
    "tasks",
    "wiki_pages",
    "wikis",
)

_REPLY_FK = "comments_parent_comment_id_fkey"


def _reply_pointer(ondelete: str) -> None:
    op.drop_constraint(_REPLY_FK, "comments", type_="foreignkey")
    op.create_foreign_key(
        _REPLY_FK,
        "comments",
        "comments",
        ["parent_comment_id"],
        ["id"],
        ondelete=ondelete,
    )


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    op.create_table(
        "moderation_actions",
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("initiative_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("subject_user_id", sa.Integer(), nullable=True),
        sa.Column("reason", sa.String(length=32), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("snapshot", sa.Text(), nullable=True),
        sa.Column("report_id", sa.Integer(), nullable=True),
        sa.Column("hold_id", sa.Integer(), nullable=True),
        sa.Column("via_grant_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action IN ('remove', 'restore', 'lock_comments', 'unlock_comments', 'clear_reactions', 'warn')",
            name="ck_moderation_actions_action",
        ),
        sa.ForeignKeyConstraint(
            ["initiative_id"], ["initiatives.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["report_id"], ["moderation_reports.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("moderation_actions", schema=None) as batch_op:
        batch_op.create_index(
            "ix_moderation_actions_log", ["initiative_id", "created_at"], unique=False
        )
        batch_op.create_index(
            "ix_moderation_actions_target", ["target_type", "target_id"], unique=False
        )

    with op.batch_alter_table("comments", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("removed_reason", sa.String(length=32), nullable=True)
        )
        batch_op.add_column(sa.Column("removal_id", sa.Integer(), nullable=True))

    with op.batch_alter_table("moderation_reports", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("legal_basis", sa.String(length=32), nullable=True)
        )
        batch_op.add_column(sa.Column("platform_case_id", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("platform_notified_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("action_id", sa.Integer(), nullable=True))

    for table in _LOCKABLE:
        op.add_column(
            table,
            sa.Column("comments_locked_at", sa.DateTime(timezone=True), nullable=True),
        )

    _reply_pointer("SET NULL")


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    _reply_pointer("CASCADE")
    # CASCADE: the tombstone guard and the search triggers rendered on these
    # columns go with them.
    for table in _LOCKABLE:
        op.execute(f"ALTER TABLE {table} DROP COLUMN comments_locked_at CASCADE")
    for column in ("removal_id", "removed_reason", "removed_at"):
        op.execute(f"ALTER TABLE comments DROP COLUMN {column} CASCADE")

    with op.batch_alter_table("moderation_reports", schema=None) as batch_op:
        batch_op.drop_column("action_id")
        batch_op.drop_column("platform_notified_at")
        batch_op.drop_column("platform_case_id")
        batch_op.drop_column("legal_basis")

    op.drop_table("moderation_actions")
