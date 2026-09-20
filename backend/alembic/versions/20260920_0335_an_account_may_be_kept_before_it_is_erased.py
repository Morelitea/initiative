"""an account may be kept before it is erased

Three additive changes, all on shared ``public`` tables:

- ``user_status`` gains ``deleted`` — the state an account sits in between its
  holder asking for it to go and the erasure actually running.
- ``users.status_changed_at`` — when the status last moved, which for a deleted
  account is when the deletion was asked for and so what the erasure date is
  counted from. The same column, doing the same job, as
  ``guilds.status_changed_at``.
- ``app_settings.deleted_account_retention_days`` — how long that window is.
  Nullable, and NULL means never erase, for a deployment required to keep
  accounts rather than to remove them. 30 on a fresh install and on every
  upgrade.

``ALTER TYPE ... ADD VALUE`` is committed on its own before the columns,
because a value added to an enum cannot be used by later statements in the
same transaction. Nothing here uses it, but the separation keeps that true if
somebody adds a backfill.

Revision ID: 20260920_0335
Revises: 20260920_0334
Create Date: 2026-09-20
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20260920_0335"
down_revision = "20260920_0334"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("COMMIT")
    op.execute("ALTER TYPE user_status ADD VALUE IF NOT EXISTS 'deleted'")
    op.execute("BEGIN")

    op.add_column(
        "users",
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=True),
    )
    # UPDATE on ``users`` is granted column by column (0144), so a new column
    # is reachable by nobody until it is named. The platform path writes this
    # one wherever it writes ``status``.
    #
    # Not ``app_guild_base``: the guild path holds nothing at all on this table
    # and reads ``public.guild_member_profiles`` instead.
    base = f"{settings.PLATFORM_ROLE_PREFIX}platform_base"
    for role in (base, "app_user"):
        op.execute(
            f'GRANT UPDATE (status_changed_at) ON TABLE public.users TO "{role}"'
        )

    op.add_column(
        "app_settings",
        sa.Column(
            "deleted_account_retention_days",
            sa.Integer(),
            nullable=True,
            server_default="30",
        ),
    )


def downgrade() -> None:
    # Any account still waiting out its window goes back to ``deactivated``:
    # the value is about to stop existing, and the nearest state that keeps the
    # row and its data is the right place to leave somebody. Neither erasing
    # them nor putting them back in use is a downgrade's decision to make.
    op.execute("UPDATE users SET status = 'deactivated' WHERE status = 'deleted'")
    op.drop_column("app_settings", "deleted_account_retention_days")
    op.drop_column("users", "status_changed_at")
    # The enum value is left in place. Removing one means rebuilding the type
    # and every column that uses it, which is a great deal of risk for a value
    # nothing references any more.
