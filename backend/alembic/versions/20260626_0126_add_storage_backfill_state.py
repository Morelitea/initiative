"""Add storage_backfill_state singleton for cluster-wide backfill status.

The local->S3 backfill status must be shared across workers (the previous
in-memory per-process status reported running/failed/idle inconsistently on a
multi-worker deployment). One singleton row, written only by the app_admin
(BYPASSRLS) engine via the owner-gated backfill endpoints.

RLS is enabled + forced with no policies, so only the BYPASSRLS app_admin engine
can read/write it; no scoped request role (app_user / platform_*) can reach it.

Revision ID: 20260626_0126
Revises: 20260625_0125
Create Date: 2026-06-26
"""

from alembic import op
import sqlalchemy as sa

revision = "20260626_0126"
down_revision = "20260625_0125"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "storage_backfill_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="idle"
        ),
        sa.Column("copied", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("hash_mismatches", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_keys", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("error", sa.String(length=2000), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat", sa.DateTime(timezone=True), nullable=True),
    )
    # Admin-only: with RLS enabled+forced and no policies, only the BYPASSRLS
    # app_admin engine (which the backfill endpoints use) can access the row.
    op.execute("ALTER TABLE storage_backfill_state ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE storage_backfill_state FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE storage_backfill_state DISABLE ROW LEVEL SECURITY")
    op.drop_table("storage_backfill_state")
