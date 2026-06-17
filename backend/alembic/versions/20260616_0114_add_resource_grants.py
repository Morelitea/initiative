"""Add polymorphic resource_grants table (DAC consolidation, stage 1).

Non-destructive: creates the table only (public = guild-schema template); backfill,
engine repoint and dropping the old *_permissions tables are later stages. Per-guild
RLS comes from the regenerated guild_rls.sql at provisioning.

Revision ID: 20260616_0114
Revises: 20260616_0113
Create Date: 2026-06-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "20260616_0114"
down_revision = "20260616_0113"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resource_grants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.Integer(), nullable=False),
        sa.Column("initiative_id", sa.Integer(), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("role_id", sa.Integer(), nullable=True),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"]),
        sa.ForeignKeyConstraint(
            ["initiative_id"], ["initiatives.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["role_id"], ["initiative_roles.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "(user_id IS NULL) <> (role_id IS NULL)",
            name="resource_grants_one_grantee",
        ),
        sa.UniqueConstraint(
            "resource_type",
            "resource_id",
            "user_id",
            "role_id",
            name="resource_grants_unique_grantee",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index("ix_resource_grants_guild_id", "resource_grants", ["guild_id"])
    op.create_index(
        "ix_resource_grants_initiative_id", "resource_grants", ["initiative_id"]
    )
    op.create_index(
        "ix_resource_grants_resource",
        "resource_grants",
        ["resource_type", "resource_id"],
    )
    op.create_index(
        "ix_resource_grants_user",
        "resource_grants",
        ["user_id", "resource_type"],
        postgresql_where=text("user_id IS NOT NULL"),
    )
    op.create_index(
        "ix_resource_grants_role",
        "resource_grants",
        ["role_id", "resource_type"],
        postgresql_where=text("role_id IS NOT NULL"),
    )

    # System engine (app_admin, BYPASSRLS) provisions + backfills guild schemas.
    op.get_bind().execute(
        text("GRANT ALL PRIVILEGES ON TABLE resource_grants TO app_admin")
    )


def downgrade() -> None:
    op.drop_index("ix_resource_grants_role", table_name="resource_grants")
    op.drop_index("ix_resource_grants_user", table_name="resource_grants")
    op.drop_index("ix_resource_grants_resource", table_name="resource_grants")
    op.drop_index("ix_resource_grants_initiative_id", table_name="resource_grants")
    op.drop_index("ix_resource_grants_guild_id", table_name="resource_grants")
    op.drop_table("resource_grants")
