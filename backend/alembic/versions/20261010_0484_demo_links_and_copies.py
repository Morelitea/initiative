"""an invite names a role, and demo copies

``guild_invites.role`` is what accepting the invite makes somebody in the
community; every invite until now made a member, which is its default.

The demo deployment's two tables: ``demo_sandboxes`` (communities built for
the pool, and the visitors' copies once claimed, each with the invite that
opened it) and ``demo_accounts`` (the account made for each visitor, tied to
its copy). Empty on every deployment not started with ``DEMO_MODE``.

Both are app_admin-only: RLS enabled and forced with no policies, and the
schema's default grants revoked from the two base roles. The tables are new
and empty, so nothing is backfilled.

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

_TABLES = ("demo_sandboxes", "demo_accounts")


def upgrade() -> None:
    op.add_column(
        "guild_invites",
        sa.Column("role", sa.String(), nullable=False, server_default="member"),
    )
    op.create_check_constraint(
        "ck_guild_invites_role",
        "guild_invites",
        "role IN ('member', 'admin', 'superadmin')",
    )

    op.create_table(
        "demo_sandboxes",
        sa.Column("guild_id", sa.Integer(), primary_key=True),
        sa.Column("state", sa.String(), nullable=False, server_default="pooled"),
        sa.Column("invite_id", sa.Integer(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("import_job_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["invite_id"], ["guild_invites.id"], ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            "state IN ('pooled', 'live')", name="ck_demo_sandboxes_state"
        ),
    )
    op.create_index("ix_demo_sandboxes_state", "demo_sandboxes", ["state"])
    op.create_index("ix_demo_sandboxes_invite_id", "demo_sandboxes", ["invite_id"])
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


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.drop_table(table)
    op.drop_constraint("ck_guild_invites_role", "guild_invites", type_="check")
    op.drop_column("guild_invites", "role")
