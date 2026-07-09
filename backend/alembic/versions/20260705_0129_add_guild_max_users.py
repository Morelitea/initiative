"""add guilds.max_users

Per-guild member cap for the platform admin dashboard. NULL = unlimited
(the default), mirroring the existing ``max_storage_bytes`` column on the same
shared ``public.guilds`` table.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260705_0129"
down_revision = "20260704_0128"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("guilds", sa.Column("max_users", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("guilds", "max_users")
