"""Add object-storage settings columns to app_settings.

Makes the S3 / blob-storage backend runtime-configurable from the Platform
settings "Storage" tab (previously env-only via STORAGE_BACKEND / S3_*). The
secret access key is stored encrypted, like the SMTP password and AI API key.
Server defaults mirror the env defaults so existing installs keep behaving as
"local" until an owner configures S3.

Revision ID: 20260625_0125
Revises: 20260624_0124
Create Date: 2026-06-25
"""

from alembic import op
import sqlalchemy as sa

revision = "20260625_0125"
down_revision = "20260624_0124"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column(
            "storage_backend",
            sa.String(length=20),
            nullable=False,
            server_default="local",
        ),
    )
    op.add_column(
        "app_settings",
        sa.Column("s3_bucket", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "app_settings",
        sa.Column(
            "s3_region",
            sa.String(length=64),
            nullable=False,
            server_default="us-east-1",
        ),
    )
    op.add_column(
        "app_settings",
        sa.Column("s3_endpoint_url", sa.String(length=1000), nullable=True),
    )
    op.add_column(
        "app_settings",
        sa.Column("s3_access_key_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "app_settings",
        sa.Column(
            "s3_secret_access_key_encrypted", sa.String(length=2000), nullable=True
        ),
    )
    op.add_column(
        "app_settings",
        sa.Column(
            "s3_use_path_style",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    op.add_column(
        "app_settings",
        sa.Column("s3_kms_key_id", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "app_settings",
        sa.Column(
            "s3_local_fallback",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "s3_local_fallback")
    op.drop_column("app_settings", "s3_kms_key_id")
    op.drop_column("app_settings", "s3_use_path_style")
    op.drop_column("app_settings", "s3_secret_access_key_encrypted")
    op.drop_column("app_settings", "s3_access_key_id")
    op.drop_column("app_settings", "s3_endpoint_url")
    op.drop_column("app_settings", "s3_region")
    op.drop_column("app_settings", "s3_bucket")
    op.drop_column("app_settings", "storage_backend")
