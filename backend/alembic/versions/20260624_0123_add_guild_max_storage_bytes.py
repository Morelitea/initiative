"""Add max_storage_bytes to the public guilds table (per-guild storage quota).

A nullable ``BIGINT`` on ``public.guilds``. ``NULL`` means "unlimited" (the
default); a non-null value is the maximum total stored blob bytes for the guild,
enforced at upload against ``SUM(uploads.size_bytes)``
(``app.services.attachments.enforce_storage_quota``). It lives on the shared
``guilds`` identity row (an operator/plan-level attribute), not in the per-guild
``guild_settings`` schema — so this is a plain public-table column add, with no
guild-schema fan-out or guild_schema.sql regeneration.

Revision ID: 20260624_0123
Revises: 20260624_0122
Create Date: 2026-06-24
"""

from alembic import op
import sqlalchemy as sa

revision = "20260624_0123"
down_revision = "20260624_0122"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "guilds",
        sa.Column("max_storage_bytes", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("guilds", "max_storage_bytes")
