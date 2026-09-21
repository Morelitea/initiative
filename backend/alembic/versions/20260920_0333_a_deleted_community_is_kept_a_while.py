"""a deleted community is kept a while

Widens ``ck_guilds_status`` to admit ``'deleted'``: the status a guild holds
between somebody deleting it and the retention window running out, after which
the purge worker does what the delete used to do immediately.

No new columns. ``status_changed_at`` already records when the status moved,
which for a deleted guild is when it was deleted — so the purge date is that
timestamp plus the retention window, and there is nothing else to keep.

Revision ID: 20260920_0333
Revises: 20260920_0332
Create Date: 2026-09-20
"""

from alembic import op

revision = "20260920_0333"
down_revision = "20260920_0332"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_guilds_status", "guilds", type_="check")
    op.create_check_constraint(
        "ck_guilds_status",
        "guilds",
        "status IN ('active', 'read_only', 'suspended', 'deleted')",
    )


def downgrade() -> None:
    # A guild the new status was the only thing standing between and a purge
    # goes back to the nearest state that still denies its members, rather
    # than to 'active' — downgrading must not republish a deleted community.
    op.execute("UPDATE guilds SET status = 'suspended' WHERE status = 'deleted'")
    op.drop_constraint("ck_guilds_status", "guilds", type_="check")
    op.create_check_constraint(
        "ck_guilds_status",
        "guilds",
        "status IN ('active', 'read_only', 'suspended')",
    )
