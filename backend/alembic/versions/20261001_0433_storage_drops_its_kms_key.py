"""Storage drops its KMS key setting

``app_settings.s3_kms_key_id`` asked the store for SSE-KMS on every write. Few
S3-compatible stores implement that header, and the ones that encrypt do it
with a default set on the bucket, so the setting goes. Objects already written
with a key read back the same way: a read names no key.

Revision ID: 20261001_0433
Revises: 20261001_0432
Create Date: 2026-10-01
"""

import sqlalchemy as sa
from alembic import op

revision = "20261001_0433"
down_revision = "20261001_0432"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("app_settings", "s3_kms_key_id")


def downgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column("s3_kms_key_id", sa.String(length=500), nullable=True),
    )
