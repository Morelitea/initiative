"""a notice waits for its worker

``notice_outbox`` is where a notice is written for each of its recipients
instead of being delivered inside the request that caused it. A worker writes
the bell line, queues the email and sends the push.

The request path appends and never reads, so INSERT is the whole of what the
request-path floors hold, and there is no row policy for it to narrow. The
system engine owns the rest.

Revision ID: 20260930_0425
Revises: 20260930_0424
Create Date: 2026-09-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.config import settings

revision = "20260930_0425"
down_revision = "20260930_0424"
branch_labels = None
depends_on = None


def _appenders() -> tuple[str, ...]:
    """The floors a request that causes a notice runs under.

    Read at apply time, not at import: the platform prefix is a setting, and
    the migrations test swaps it around the chain it runs.
    """
    return (
        "app_guild_base",
        f"{settings.PLATFORM_ROLE_PREFIX}platform_base",
        "app_install_base",
    )


def upgrade() -> None:
    op.create_table(
        "notice_outbox",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "guild_id",
            sa.Integer(),
            sa.ForeignKey("guilds.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("rollup_key", sa.Text(), nullable=True),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("actor_name", sa.Text(), nullable=True),
        sa.Column("push_title", sa.Text(), nullable=True),
        sa.Column("push_body", sa.Text(), nullable=True),
        sa.Column("push_data", postgresql.JSONB(), nullable=True),
        sa.Column("email_subject", sa.Text(), nullable=True),
        sa.Column("email_headline", sa.Text(), nullable=True),
        sa.Column("email_body", sa.Text(), nullable=True),
        sa.Column("email_link", sa.Text(), nullable=True),
        sa.Column("email_link_label", sa.Text(), nullable=True),
        sa.Column(
            "email_names_line",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deliver_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bell_written_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_notice_outbox_due", "notice_outbox", ["deliver_after", "user_id"]
    )

    # Schema defaults hand a new table full DML to the floors that have them,
    # so the narrowing is an explicit REVOKE before the one grant they keep.
    for role in _appenders():
        op.execute(f'REVOKE ALL ON TABLE public.notice_outbox FROM "{role}"')
        op.execute(f'GRANT INSERT ON TABLE public.notice_outbox TO "{role}"')
        op.execute(
            f'GRANT USAGE, SELECT ON SEQUENCE public.notice_outbox_id_seq TO "{role}"'
        )
    op.execute("REVOKE ALL ON TABLE public.notice_outbox FROM app_user")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.notice_outbox "
        "TO app_admin"
    )
    op.execute(
        "GRANT USAGE, SELECT ON SEQUENCE public.notice_outbox_id_seq TO app_admin"
    )


def downgrade() -> None:
    op.drop_index("ix_notice_outbox_due", table_name="notice_outbox")
    op.drop_table("notice_outbox")
