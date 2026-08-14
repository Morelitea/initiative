"""guild app placement

Which initiatives an app's initiative-scoped surfaces appear in. ``{}`` — the
default, and what every existing install keeps — means every one of them.

One JSONB column rather than a mode plus a list, so "all" has exactly one
representation and cannot fall out of step with a stale set of ids.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260813_0175"
down_revision = "20260812_0174"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    op.add_column(
        "guild_apps",
        sa.Column(
            "placement",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
    )


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    op.drop_column("guild_apps", "placement")
