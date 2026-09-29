"""read notifications expire

Read notifications are deleted thirty days after they were read, by a batched
sweep on the notification housekeeping job. The sweep asks for rows by
``read_at`` alone, which the existing ``(user_id, read_at)`` composite cannot
answer without scanning, so it gets a partial index of its own over the read
rows. Unread rows are never swept and stay out of it.

Revision ID: 20260925_0394
Revises: 20260925_0393
Create Date: 2026-09-25
"""

import sqlalchemy as sa
from alembic import op

revision = "20260925_0394"
down_revision = "20260925_0393"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_notifications_read_at",
        "notifications",
        ["read_at"],
        unique=False,
        schema="public",
        postgresql_where=sa.text("read_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_notifications_read_at", table_name="notifications", schema="public"
    )
