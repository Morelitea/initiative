"""content holds

Every holdable table gains ``held_at`` and ``hold_id`` (``HoldMixin``), and
each guild schema gains ``content_holds``, the platform's record of what it
holds there. A community report can be settled as ``held``. The row policy that hides held rows, its write guard and
``content_holds``' own policies are rendered by the provisioning run from
``app.db.holds``.

The downgrade drops the columns with whatever was rendered on them.

Revision ID: 20261009_0473
Revises: 20261009_0472
Create Date: 2026-10-09
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261009_0473"
down_revision = "20261009_0472"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


#: ``moderation_reports.outcome``, before and after ``held``.
_OUTCOME_CK = "ck_moderation_reports_outcome"
_OUTCOMES = "'dismissed', 'content_removed', 'member_warned', 'escalated'"
_OUTCOMES_HELD = f"{_OUTCOMES}, 'held'"


def _outcomes(values: str) -> None:
    op.drop_constraint(_OUTCOME_CK, "moderation_reports", type_="check")
    op.create_check_constraint(
        _OUTCOME_CK, "moderation_reports", f"outcome IS NULL OR outcome IN ({values})"
    )


def _apply_upgrade() -> None:
    # A report can be settled as held: handed to the platform, its target held.
    _outcomes(_OUTCOMES_HELD)
    op.create_table(
        "content_holds",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("case_task_id", sa.Integer(), nullable=True),
        sa.Column("placed_by", sa.Integer(), nullable=True),
        sa.Column("placed_via", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("legal_basis", sa.String(length=32), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("placed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reminded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_by", sa.Integer(), nullable=True),
        sa.Column("release_outcome", sa.String(length=16), nullable=True),
        sa.CheckConstraint(
            "legal_basis IS NULL OR legal_basis IN ('child_safety', 'terrorism', 'intellectual_property', 'fraud', 'privacy', 'other')",
            name="ck_content_holds_legal_basis",
        ),
        sa.CheckConstraint(
            "placed_via IN ('community', 'platform')", name="ck_content_holds_via"
        ),
        sa.CheckConstraint(
            "reason <> 'illegal_content' OR legal_basis IS NOT NULL",
            name="ck_content_holds_basis_named",
        ),
        sa.CheckConstraint(
            "reason IN ('legal_request', 'illegal_content')",
            name="ck_content_holds_reason",
        ),
        sa.CheckConstraint(
            "release_outcome IS NULL OR release_outcome IN ('restore', 'remove', 'purge')",
            name="ck_content_holds_outcome",
        ),
        sa.CheckConstraint(
            "(released_at IS NULL) = (release_outcome IS NULL)",
            name="ck_content_holds_released",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("content_holds", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_content_holds_target_id"), ["target_id"], unique=False
        )

    with op.batch_alter_table("calendar_events", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("held_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("hold_id", sa.Integer(), nullable=True))

    with op.batch_alter_table("calendars", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("held_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("hold_id", sa.Integer(), nullable=True))

    with op.batch_alter_table("comments", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("held_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("hold_id", sa.Integer(), nullable=True))

    with op.batch_alter_table("counter_groups", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("held_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("hold_id", sa.Integer(), nullable=True))

    with op.batch_alter_table("counters", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("held_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("hold_id", sa.Integer(), nullable=True))

    with op.batch_alter_table("dashboards", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("held_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("hold_id", sa.Integer(), nullable=True))

    with op.batch_alter_table("files", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("held_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("hold_id", sa.Integer(), nullable=True))

    with op.batch_alter_table("galleries", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("held_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("hold_id", sa.Integer(), nullable=True))

    with op.batch_alter_table("gallery_images", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("held_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("hold_id", sa.Integer(), nullable=True))

    with op.batch_alter_table("posts", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("held_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("hold_id", sa.Integer(), nullable=True))

    with op.batch_alter_table("projects", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("held_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("hold_id", sa.Integer(), nullable=True))

    with op.batch_alter_table("queue_items", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("held_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("hold_id", sa.Integer(), nullable=True))

    with op.batch_alter_table("queues", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("held_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("hold_id", sa.Integer(), nullable=True))

    with op.batch_alter_table("tags", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("held_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("hold_id", sa.Integer(), nullable=True))

    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("held_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("hold_id", sa.Integer(), nullable=True))

    with op.batch_alter_table("uploads", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("held_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("hold_id", sa.Integer(), nullable=True))

    with op.batch_alter_table("wiki_pages", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("held_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("hold_id", sa.Integer(), nullable=True))

    with op.batch_alter_table("wikis", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("held_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("hold_id", sa.Integer(), nullable=True))

    # ### end Alembic commands ###


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


#: The tables that carry the hold columns, as of this revision.
_HOLDABLE = (
    "calendar_events",
    "calendars",
    "comments",
    "counter_groups",
    "counters",
    "dashboards",
    "files",
    "galleries",
    "gallery_images",
    "posts",
    "projects",
    "queue_items",
    "queues",
    "tags",
    "tasks",
    "uploads",
    "wiki_pages",
    "wikis",
)


def _apply_downgrade() -> None:
    # A report settled as held reads as escalated, which it also was.
    op.execute("ALTER TABLE moderation_reports NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "UPDATE moderation_reports SET outcome = 'escalated' WHERE outcome = 'held'"
    )
    op.execute("ALTER TABLE moderation_reports FORCE ROW LEVEL SECURITY")
    _outcomes(_OUTCOMES)
    # The policies, guards and search triggers rendered on the columns go
    # with them; the next boot renders what the older revision expects.
    for table in _HOLDABLE:
        op.execute(
            f"ALTER TABLE {table} DROP COLUMN IF EXISTS hold_id, "
            "DROP COLUMN IF EXISTS held_at CASCADE"
        )
    op.drop_index("ix_content_holds_target_id", table_name="content_holds")
    op.drop_table("content_holds")
