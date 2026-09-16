"""app_settings names the guild that receives operations work

One nullable pointer on the singleton. NULL on every existing and fresh
install, which is what "this deployment routes nothing anywhere" looks like:
the intake writer resolves no binding and every call it makes is a no-op.

``ON DELETE SET NULL`` so deleting the guild clears the pointer in the same
statement that removes it, alongside the memberships, invites and grants that
already cascade off ``public.guilds``. Nothing is left naming a guild that is
gone.

Revision ID: 20260915_0268
Revises: 20260913_0267
Create Date: 2026-09-15
"""

import sqlalchemy as sa
from alembic import op

revision = "20260915_0268"
down_revision = "20260913_0267"
branch_labels = None
depends_on = None

_FK = "fk_app_settings_operations_guild_id"


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column("operations_guild_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        _FK,
        "app_settings",
        "guilds",
        ["operations_guild_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(_FK, "app_settings", type_="foreignkey")
    op.drop_column("app_settings", "operations_guild_id")
