"""add guilds.status + guilds.status_changed_at

Operator-set guild lifecycle status on the shared ``public.guilds`` table:
``active`` (default) / ``read_only`` (content writes denied at the Postgres
role level) / ``suspended`` (soft delete — members lose content access).
Stored as a CHECK-constrained string, mirroring the ``access_grants`` pattern.
Enforcement happens in the guild-access resolver (which Postgres role a
request assumes), so no RLS policy changes here; PAM/break-glass grants are
deliberately unaffected by the status.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260705_0130"
down_revision = "20260705_0129"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "guilds",
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="active",
        ),
    )
    op.add_column(
        "guilds",
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_guilds_status",
        "guilds",
        "status IN ('active', 'read_only', 'suspended')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_guilds_status", "guilds", type_="check")
    op.drop_column("guilds", "status_changed_at")
    op.drop_column("guilds", "status")
