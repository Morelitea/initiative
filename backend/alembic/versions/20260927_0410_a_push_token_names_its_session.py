"""a push token names its session

The session that registered a device is recorded beside it, and delivery sends
to a device while that session's chain stands. A row that names neither a
live session nor a live device token is dropped at its next delivery; the app
registers again each time it starts.

A plain uuid rather than a foreign key, as ``auth_sessions.parent_id`` is:
session rows are purged on their own schedule. A refresh, a step-up and a
replacement move the row to the session that succeeds its own, so it is
indexed.

Revision ID: 20260927_0410
Revises: 20260927_0409
Create Date: 2026-09-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260927_0410"
down_revision = "20260927_0409"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("push_tokens", sa.Column("session_id", sa.Uuid(), nullable=True))
    op.create_index(
        "ix_push_tokens_session_id", "push_tokens", ["session_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_push_tokens_session_id", table_name="push_tokens")
    op.drop_column("push_tokens", "session_id")
