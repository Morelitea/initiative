"""intake cases carry a topic

``intake_cases.topic``, in every guild schema: what a case is about within its
stream, as its filer chose — a support topic, a security topic, a feedback
kind, an appeal. NULL where nobody chose one. The filer role's grant on it is
rendered by the provisioning run.

Revision ID: 20261010_0481
Revises: 20261009_0480
Create Date: 2026-10-10
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261010_0481"
down_revision = "20261009_0480"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    op.add_column(
        "intake_cases", sa.Column("topic", sa.String(length=32), nullable=True)
    )


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    op.drop_column("intake_cases", "topic")
