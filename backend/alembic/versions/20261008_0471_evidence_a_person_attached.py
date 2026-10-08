"""evidence a person attached

``evidence``, in every guild schema: one row per file a person attached to a
community report or an operations case. The object is stored encrypted under a
key of its own, which the row holds wrapped for its community
(``app.core.blob_crypto``). Its policies, the ``created_by`` trigger and the
filer role's reach are rendered by the provisioning run.

Revision ID: 20261008_0471
Revises: 20261008_0470
Create Date: 2026-10-08
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261008_0471"
down_revision = "20261008_0470"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    op.create_table(
        "evidence",
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=True),
        sa.Column("case_id", sa.Integer(), nullable=True),
        sa.Column("comment_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("origin_guild_id", sa.Integer(), nullable=False),
        sa.Column("origin_id", sa.Uuid(), nullable=False),
        sa.Column("storage_key", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("wrapped_dek", sa.LargeBinary(), nullable=False),
        sa.Column("kek_version", sa.SmallInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('attachment')", name="ck_evidence_kind"),
        sa.CheckConstraint(
            "num_nonnulls(report_id, case_id) = 1", name="ck_evidence_one_parent"
        ),
        sa.ForeignKeyConstraint(["case_id"], ["intake_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["comment_id"], ["comments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["report_id"], ["moderation_reports.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("evidence", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_evidence_case_id"), ["case_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_evidence_report_id"), ["report_id"], unique=False
        )


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    with op.batch_alter_table("evidence", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_evidence_report_id"))
        batch_op.drop_index(batch_op.f("ix_evidence_case_id"))

    op.drop_table("evidence")
