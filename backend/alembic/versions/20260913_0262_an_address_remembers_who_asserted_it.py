"""an address remembers who asserted it

An address arrives one of two ways: somebody typed it, or an identity provider
asserted it. The row did not say which, so an address a guild's own directory
supplied was indistinguishable from a personal one.

``provider_id`` records the provider that asserted it, and NULL means nobody
did. Which guild an address belongs to follows from there —
``auth_providers.guild_id`` already says which guild a provider serves — so the
guild is not stored a second time and the two cannot disagree.

ON DELETE SET NULL: removing a provider from the registry leaves the addresses
it asserted in place, unattributed. They are still the person's addresses.

Revision ID: 20260913_0262
Revises: 20260911_0261
Create Date: 2026-09-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260913_0262"
down_revision = "20260911_0261"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_emails", sa.Column("provider_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_user_emails_provider_id",
        "user_emails",
        "auth_providers",
        ["provider_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Supports the per-guild read: the addresses one guild's providers asserted.
    op.create_index("ix_user_emails_provider_id", "user_emails", ["provider_id"])


def downgrade() -> None:
    op.drop_index("ix_user_emails_provider_id", table_name="user_emails")
    op.drop_constraint("fk_user_emails_provider_id", "user_emails", type_="foreignkey")
    op.drop_column("user_emails", "provider_id")
