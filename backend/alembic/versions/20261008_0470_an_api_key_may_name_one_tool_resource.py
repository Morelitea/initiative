"""An API key may name one tool resource

``user_api_keys.resource_type``/``resource_id`` name the one tool resource a
key reads, the way ``resource_grants`` names one: the subscription link to a
calendar. Such a key is limited to its community and reads only, and a person
holds one per resource.

``user_api_keys`` is read on the system engine alone, so nothing is granted.

Revision ID: 20261008_0470
Revises: 20261007_0469
Create Date: 2026-10-08
"""

import sqlalchemy as sa
from alembic import op

revision = "20261008_0470"
down_revision = "20261007_0469"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_api_keys",
        sa.Column("resource_type", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "user_api_keys",
        sa.Column("resource_id", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "user_api_keys_resource_scope",
        "user_api_keys",
        "(resource_type IS NULL AND resource_id IS NULL) OR "
        "(resource_type IS NOT NULL AND resource_id IS NOT NULL "
        "AND guild_id IS NOT NULL AND read_only)",
    )
    op.create_index(
        "ix_user_api_keys_one_per_resource",
        "user_api_keys",
        ["user_id", "guild_id", "resource_type", "resource_id"],
        unique=True,
        postgresql_where=sa.text("resource_type IS NOT NULL"),
    )


def downgrade() -> None:
    # Keys limited to one resource go with the columns that limit them. The
    # table forces row security and has no policy, so the migration lifts it
    # for the delete.
    op.execute("ALTER TABLE public.user_api_keys NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute("DELETE FROM public.user_api_keys WHERE resource_type IS NOT NULL")
    finally:
        op.execute("ALTER TABLE public.user_api_keys FORCE ROW LEVEL SECURITY")
    op.drop_index("ix_user_api_keys_one_per_resource", table_name="user_api_keys")
    op.drop_constraint("user_api_keys_resource_scope", "user_api_keys", type_="check")
    op.drop_column("user_api_keys", "resource_id")
    op.drop_column("user_api_keys", "resource_type")
