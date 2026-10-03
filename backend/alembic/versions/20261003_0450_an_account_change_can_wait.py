"""an account change can wait

``account_change_holds`` records a change to how an account is signed into
that waits before it is made: making an address primary, removing an address,
turning two-factor authentication off, or removing the last passkey. One
pending hold per account, held by a partial unique index.

The table is new and empty, so row security is turned on at creation. It is
the system engine's alone: the schema default is taken back from both floors
and no policy is written (``FORCED_NO_POLICY`` in ``app.db.public_rls``).

Revision ID: 20261003_0450
Revises: 20261003_0449
Create Date: 2026-10-03
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20261003_0450"
down_revision = "20261003_0449"
branch_labels = None
depends_on = None


def upgrade() -> None:
    base = f"{settings.PLATFORM_ROLE_PREFIX}platform_base"
    op.create_table(
        "account_change_holds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column(
            "address_id",
            sa.Integer(),
            sa.ForeignKey("user_emails.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "passkey_id",
            sa.Uuid(),
            sa.ForeignKey("user_passkeys.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("auth_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applies_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_account_change_holds_pending",
        "account_change_holds",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("cancelled_at IS NULL AND applied_at IS NULL"),
    )
    for statement in (
        "ALTER TABLE public.account_change_holds ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE public.account_change_holds FORCE ROW LEVEL SECURITY",
        "REVOKE ALL ON TABLE public.account_change_holds "
        f'FROM app_user, app_guild_base, "{base}"',
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.account_change_holds "
        "TO app_admin",
        "GRANT USAGE, SELECT ON SEQUENCE public.account_change_holds_id_seq "
        "TO app_admin",
    ):
        op.execute(statement)


def downgrade() -> None:
    op.drop_index("uq_account_change_holds_pending", table_name="account_change_holds")
    op.drop_table("account_change_holds")
