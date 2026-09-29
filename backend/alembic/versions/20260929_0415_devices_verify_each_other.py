"""devices verify each other

``dm_verification_messages``: the relay two devices of one account use to
exchange the messages of an emoji verification before they trust each other.
Each row is the client's own JSON — public keys, commitments and MACs — and
lives until its recipient collects it, or ten minutes.

The table is ``UNLOGGED``. What it holds is minutes old and only meaningful to
a verification in progress, so it writes no WAL, and Postgres empties it after a
crash, which cancels any verification that was under way.

Only the account's own platform-tier session reaches it: ``platform_base``
keeps ``SELECT``, ``INSERT`` and ``DELETE`` and its read floor ``SELECT``; the
guild floor is given nothing. The row policies are rendered from the shared
table registry (``app.db.public_rls``) at boot. There is nothing to carry in,
so the table is created and locked down in one go.

Revision ID: 20260929_0415
Revises: 20260928_0414
Create Date: 2026-09-29
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20260929_0415"
down_revision = "20260928_0414"
branch_labels = None
depends_on = None

TABLE = "public.dm_verification_messages"
SEQUENCE = "public.dm_verification_messages_id_seq"


def upgrade() -> None:
    base = f"{settings.PLATFORM_ROLE_PREFIX}platform_base"
    read_floor = f"{settings.PLATFORM_ROLE_PREFIX}platform_base_ro"

    op.create_table(
        "dm_verification_messages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("sender_device_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_device_id", sa.Uuid(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["sender_device_id"], ["dm_devices.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["recipient_device_id"], ["dm_devices.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        prefixes=["UNLOGGED"],
    )
    op.create_index(
        "ix_dm_verification_messages_device_id",
        "dm_verification_messages",
        ["recipient_device_id", "id"],
    )

    for statement in (
        f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY",
        # The schema's default privileges hand every new public table and
        # sequence to both floors, so they are wound back before anything is
        # given.
        f'REVOKE ALL ON TABLE {TABLE} FROM app_guild_base, "{base}"',
        f"REVOKE ALL ON SEQUENCE {SEQUENCE} FROM app_guild_base",
        f'GRANT SELECT, INSERT, DELETE ON TABLE {TABLE} TO "{base}"',
        f'GRANT USAGE, SELECT ON SEQUENCE {SEQUENCE} TO "{base}"',
        f'GRANT SELECT ON TABLE {TABLE} TO "{read_floor}"',
    ):
        op.execute(statement)


def downgrade() -> None:
    op.drop_index(
        "ix_dm_verification_messages_device_id",
        table_name="dm_verification_messages",
    )
    # Its policies, grants and sequence go with it.
    op.drop_table("dm_verification_messages")
