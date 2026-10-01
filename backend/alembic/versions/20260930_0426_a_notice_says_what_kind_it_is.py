"""a notice says what kind it is

``notice_outbox`` carries a reaction to roll into its recipient's bell line,
and a reaction taken back, as well as a notice of its own. ``kind`` says which;
every row written before is a notice.

Revision ID: 20260930_0426
Revises: 20260930_0425
Create Date: 2026-09-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260930_0426"
down_revision = "20260930_0425"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notice_outbox",
        sa.Column("kind", sa.String(16), nullable=False, server_default="notice"),
    )


def downgrade() -> None:
    op.drop_column("notice_outbox", "kind")
