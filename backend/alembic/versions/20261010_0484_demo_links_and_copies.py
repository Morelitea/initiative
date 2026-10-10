"""demo links and copies

The demo deployment's three tables: ``demo_links`` (a link handing a pitch
out, kept by the SHA-256 of its token), ``demo_sandboxes`` (communities built
for the pool, and the visitors' copies once claimed) and ``demo_accounts``
(the account made for each visitor, tied to its copy). Empty on every
deployment not started with ``DEMO_MODE``.

All three are app_admin-only: RLS enabled and forced with no policies, and
the schema's default grants revoked from the two base roles. The tables are
new and empty, so nothing is backfilled.

Revision ID: 20261010_0484
Revises: 20261010_0483
Create Date: 2026-10-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20261010_0484"
down_revision = "20261010_0483"
branch_labels = None
depends_on = None

_TABLES = ("demo_links", "demo_sandboxes", "demo_accounts")


def upgrade() -> None:
    op.create_table(
        "demo_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("source_guild_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(), nullable=False, server_default="admin"),
        sa.Column("max_redemptions", sa.Integer(), nullable=True),
        sa.Column("max_live", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("redemption_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_redeemed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "role IN ('member', 'admin', 'superadmin')", name="ck_demo_links_role"
        ),
    )
    op.create_unique_constraint(
        "uq_demo_links_token_hash", "demo_links", ["token_hash"]
    )
    op.create_index("ix_demo_links_source_guild_id", "demo_links", ["source_guild_id"])

    op.create_table(
        "demo_sandboxes",
        sa.Column("guild_id", sa.Integer(), primary_key=True),
        sa.Column("state", sa.String(), nullable=False, server_default="pooled"),
        sa.Column("link_id", sa.Integer(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("import_job_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["link_id"], ["demo_links.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "state IN ('pooled', 'live')", name="ck_demo_sandboxes_state"
        ),
    )
    op.create_index("ix_demo_sandboxes_state", "demo_sandboxes", ["state"])
    op.create_index("ix_demo_sandboxes_link_id", "demo_sandboxes", ["link_id"])

    op.create_table(
        "demo_accounts",
        sa.Column("user_id", sa.Integer(), primary_key=True),
        sa.Column("sandbox_guild_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["sandbox_guild_id"], ["demo_sandboxes.guild_id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_demo_accounts_sandbox_guild_id", "demo_accounts", ["sandbox_guild_id"]
    )

    if op.get_bind().dialect.name != "postgresql":
        return

    base = f"{settings.PLATFORM_ROLE_PREFIX}platform_base"
    for table in _TABLES:
        for statement in (
            f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY",
            # The public schema default-grants platform_base + app_guild_base
            # full DML on every new table; both come straight back off.
            f'REVOKE ALL ON TABLE public.{table} FROM app_guild_base, "{base}"',
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.{table} TO app_admin",
        ):
            op.execute(statement)
    # The system engine draws the ids of the links it inserts.
    op.execute(
        "REVOKE ALL ON SEQUENCE public.demo_links_id_seq "
        f'FROM app_guild_base, "{base}", app_user'
    )
    op.execute("GRANT USAGE, SELECT ON SEQUENCE public.demo_links_id_seq TO app_admin")


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.drop_table(table)
