"""Add OIDC claim-to-role mapping

Revision ID: 20260211_0048
Revises: 20260210_0047
Create Date: 2026-02-11

Adds oidc_role_claim_path column to app_settings,
creates oidc_claim_mappings table for mapping OIDC token claims
to guild/initiative memberships, and adds oidc_managed boolean
to guild_memberships and initiative_members.
"""

from alembic import op
import sqlalchemy as sa


revision = "20260211_0048"
down_revision = "20260210_0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add oidc_role_claim_path to app_settings
    op.add_column(
        "app_settings",
        sa.Column("oidc_role_claim_path", sa.String(500), nullable=True),
    )

    # 2. Create oidc_claim_mappings table
    op.create_table(
        "oidc_claim_mappings",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("claim_value", sa.String(500), nullable=False),
        sa.Column("target_type", sa.String(20), nullable=False),
        sa.Column(
            "guild_id",
            sa.Integer,
            sa.ForeignKey("guilds.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "guild_role",
            sa.String(20),
            nullable=False,
            server_default="member",
        ),
        sa.Column(
            "initiative_id",
            sa.Integer,
            sa.ForeignKey("initiatives.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "initiative_role_id",
            sa.Integer,
            sa.ForeignKey("initiative_roles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # 3. Add oidc_managed to guild_memberships
    op.add_column(
        "guild_memberships",
        sa.Column(
            "oidc_managed",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # 4. Add oidc_managed to initiative_members
    op.add_column(
        "initiative_members",
        sa.Column(
            "oidc_managed",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("initiative_members", "oidc_managed")
    op.drop_column("guild_memberships", "oidc_managed")
    op.drop_table("oidc_claim_mappings")
    op.drop_column("app_settings", "oidc_role_claim_path")
