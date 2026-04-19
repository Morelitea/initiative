"""Add task_completion_visual_feedback column to users.

Stores the user's preference for the celebratory visual effect that fires
when they complete a task they're assigned to. Free-form short string;
the frontend validates against the known set
(none | confetti | heart | d20 | gold_coin | random) and falls back to
"none" if it doesn't recognise the value. Defaults to "none" so existing
users see no behavior change until they opt in.

Revision ID: 20260418_0071
Revises: 20260413_0070
Create Date: 2026-04-18
"""

from alembic import op
import sqlalchemy as sa

revision = "20260418_0071"
down_revision = "20260413_0070"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "task_completion_visual_feedback",
            sa.String(length=32),
            nullable=False,
            server_default="none",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "task_completion_visual_feedback")
