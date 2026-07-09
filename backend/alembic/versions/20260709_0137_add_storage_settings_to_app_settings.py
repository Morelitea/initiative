"""Add object-storage settings columns to app_settings.

Makes the S3 / blob-storage backend runtime-configurable from the Platform
settings "Storage" tab (previously env-only via STORAGE_BACKEND / S3_*). The
secret access key is stored encrypted, like the SMTP password and AI API key.
Server defaults mirror the env defaults so existing installs keep behaving as
"local" until an owner configures S3.

Revision ID: 20260709_0137
Revises: 20260709_0136
Create Date: 2026-07-09
"""

from alembic import op
import sqlalchemy as sa

revision = "20260709_0137"
down_revision = "20260709_0136"
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

    # One-time seed from env for an install that configured S3 via STORAGE_BACKEND /
    # S3_* before this tab existed: its app_settings singleton (id=1) already exists,
    # so the columns we just added landed at their defaults (storage_backend='local',
    # S3 fields NULL) and the backend selection would be lost on upgrade. Seed it once
    # here. After this the service treats the DB row as authoritative (it does not
    # re-seed storage from env), so an owner can later clear a field without it
    # reverting. A fresh DB has no row yet (it's created post-migrate, env-seeded by
    # _build_default_app_settings), so this updates 0 rows there.
    from app.core.config import settings as cfg
    from app.core.encryption import SALT_S3_SECRET_KEY, encrypt_field

    secret = (cfg.S3_SECRET_ACCESS_KEY or "").strip() or None
    op.get_bind().execute(
        sa.text(
            "UPDATE app_settings SET "
            "storage_backend = :backend, s3_bucket = :bucket, s3_region = :region, "
            "s3_endpoint_url = :endpoint, s3_access_key_id = :akid, "
            "s3_secret_access_key_encrypted = :secret, "
            "s3_use_path_style = :path_style, s3_kms_key_id = :kms, "
            "s3_local_fallback = :fallback WHERE id = 1"
        ),
        {
            "backend": (cfg.STORAGE_BACKEND or "local").lower(),
            "bucket": (cfg.S3_BUCKET or "").strip() or None,
            "region": cfg.S3_REGION or "us-east-1",
            "endpoint": (cfg.S3_ENDPOINT_URL or "").strip() or None,
            "akid": (cfg.S3_ACCESS_KEY_ID or "").strip() or None,
            "secret": encrypt_field(secret, SALT_S3_SECRET_KEY) if secret else None,
            "path_style": bool(cfg.S3_USE_PATH_STYLE),
            "kms": (cfg.S3_KMS_KEY_ID or "").strip() or None,
            "fallback": bool(cfg.S3_LOCAL_FALLBACK),
        },
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
