"""Push goes through the relay

A server sends iPhone pushes, and Android ones when it has no Firebase service
account of its own, through Morelitea's push relay. It registers with the relay
the first time it needs to and keeps what it is issued here, beside the service
account: ``push_relay_server_id`` (not a secret) and
``push_relay_key_encrypted`` (Fernet, like the credentials beside it). Nothing
is written: the first push through the relay fills them.

Revision ID: 20261004_0455
Revises: 20261004_0454
Create Date: 2026-10-04
"""

import sqlalchemy as sa
from alembic import op

revision = "20261004_0455"
down_revision = "20261004_0454"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_setting_secrets",
        sa.Column("push_relay_server_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "app_setting_secrets",
        sa.Column("push_relay_key_encrypted", sa.String(length=2000), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("app_setting_secrets", "push_relay_key_encrypted")
    op.drop_column("app_setting_secrets", "push_relay_server_id")
