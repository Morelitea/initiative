"""a community can be on hold

Widens ``ck_guilds_status`` to admit ``'on_hold'``: the status the billing
service sets for a significantly late payment. Nobody in the guild reaches it
and it leaves every member's guild list, the same as a deleted one, without
the retention clock.

No new columns. ``status_changed_at`` already records when the hold began.

Revision ID: 20260923_0360
Revises: 20260923_0359
Create Date: 2026-09-23
"""

from alembic import op

revision = "20260923_0360"
down_revision = "20260923_0359"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_guilds_status", "guilds", type_="check")
    op.create_check_constraint(
        "ck_guilds_status",
        "guilds",
        "status IN ('active', 'read_only', 'suspended', 'on_hold', 'deleted')",
    )


def downgrade() -> None:
    # A held guild goes back to the nearest state that still refuses its
    # members, rather than to 'active'.
    op.execute("ALTER TABLE guilds NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute("UPDATE guilds SET status = 'suspended' WHERE status = 'on_hold'")
    finally:
        op.execute("ALTER TABLE guilds FORCE ROW LEVEL SECURITY")
    op.drop_constraint("ck_guilds_status", "guilds", type_="check")
    op.create_check_constraint(
        "ck_guilds_status",
        "guilds",
        "status IN ('active', 'read_only', 'suspended', 'deleted')",
    )
