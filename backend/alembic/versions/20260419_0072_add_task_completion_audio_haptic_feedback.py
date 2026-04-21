"""Add task_completion_audio_feedback and task_completion_haptic_feedback columns to users.

Subtler siblings to the existing visual-feedback preference. Both default
to true so existing users get a small confirmation chime + vibration on
task completion without having to opt in. Stored as separate booleans
(rather than a single bitmask or shared enum) so each modality can evolve
independently.

Revision ID: 20260419_0072
Revises: 20260418_0071
Create Date: 2026-04-19
"""

from alembic import op
import sqlalchemy as sa

revision = "20260419_0072"
down_revision = "20260418_0071"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "task_completion_audio_feedback",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "task_completion_haptic_feedback",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "task_completion_haptic_feedback")
    op.drop_column("users", "task_completion_audio_feedback")
