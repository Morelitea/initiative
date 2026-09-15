"""who has asserted an address

An address arrives one of two ways: somebody typed it, or an identity provider
asserted it. The row did not say which — and "which" is not one answer. A
contractor at two organisations signs into both with one address, and each
organisation's directory asserts it independently, so the providers behind an
address are a set rather than a field.

``user_email_assertions`` holds that set. An address with no rows here is one
nobody asserted. Which guild an address belongs to follows from there —
``auth_providers.guild_id`` already says which guild a provider serves — so no
guild is stored twice and the two cannot disagree.

CASCADE on both sides: the row *is* the assertion, so it goes when either the
address or the provider does. The address itself outlives its provider.

app_admin-only, like ``user_emails``: an address resolves before anybody is
authenticated.

Revision ID: 20260913_0262
Revises: 20260911_0261
Create Date: 2026-09-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20260913_0262"
down_revision = "20260911_0261"
branch_labels = None
depends_on = None


def _platform(role: str) -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_{role}"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.create_table(
        "user_email_assertions",
        sa.Column("user_email_id", sa.Integer(), primary_key=True),
        sa.Column("provider_id", sa.Integer(), primary_key=True),
        sa.Column("first_asserted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_asserted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_email_id"], ["user_emails.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["auth_providers.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_user_email_assertions_provider_id",
        "user_email_assertions",
        ["provider_id"],
    )

    if not _is_postgres():
        return

    base = _platform("base")
    for statement in (
        "ALTER TABLE public.user_email_assertions ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE public.user_email_assertions FORCE ROW LEVEL SECURITY",
        # The public schema default-grants platform_base + app_guild_base full
        # DML on every new table; both come straight back off.
        "REVOKE ALL ON TABLE public.user_email_assertions "
        f'FROM app_guild_base, "{base}"',
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "
        "public.user_email_assertions TO app_admin",
    ):
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.user_email_assertions CASCADE")
