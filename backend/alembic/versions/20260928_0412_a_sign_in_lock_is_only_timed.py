"""a sign-in lock is only timed

Every lock ends at ``locked_until`` and every lock is emailed, so
``sign_in_locks`` no longer records a standing hold or when its holder was last
told about one.

Revision ID: 20260928_0412
Revises: 20260928_0411
Create Date: 2026-09-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260928_0412"
down_revision = "20260928_0411"
branch_labels = None
depends_on = None

_COLUMNS = ("held_at", "notified_at")


def upgrade() -> None:
    for column in _COLUMNS:
        op.drop_column("sign_in_locks", column)


def downgrade() -> None:
    for column in _COLUMNS:
        op.add_column(
            "sign_in_locks",
            sa.Column(column, sa.DateTime(timezone=True), nullable=True),
        )
