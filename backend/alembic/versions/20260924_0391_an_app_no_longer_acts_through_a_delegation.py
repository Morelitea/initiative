"""an app no longer acts through a delegation

The app-signed delegation token is gone, and with it the two things only it
used in ``public``:

- ``app_service_registrations.grants``: the operator-conferred ``delegation``
  and ``app_directory`` powers. An app acts through its installation token, or
  a member token a member consented to, and neither reads a grant.
- ``auto_delegation_jti_blocklist``: the one-shot guard for delegation tokens.

The downgrade restores both as they stood: the column empty on every row, and
the table empty, with the system engine's and the bare login's verbs and
nothing for the two floors the schema default grants to.

Revision ID: 20260924_0391
Revises: 20260924_0390
Create Date: 2026-09-24
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.config import settings

revision = "20260924_0391"
down_revision = "20260924_0390"
branch_labels = None
depends_on = None

REGISTRATIONS = "app_service_registrations"
BLOCKLIST = "auto_delegation_jti_blocklist"


def upgrade() -> None:
    op.drop_column(REGISTRATIONS, "grants")
    # Its index and its grants go with it.
    op.drop_table(BLOCKLIST)


def downgrade() -> None:
    op.create_table(
        BLOCKLIST,
        sa.Column("jti", sa.String(length=64), nullable=False),
        sa.Column(
            "redeemed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("jti", name=f"{BLOCKLIST}_pkey"),
    )
    op.create_index(f"ix_{BLOCKLIST}_expires_at", BLOCKLIST, ["expires_at"])
    platform_base = f"{settings.PLATFORM_ROLE_PREFIX}platform_base"
    op.execute(
        f'REVOKE ALL ON TABLE public.{BLOCKLIST} FROM app_guild_base, "{platform_base}"'
    )
    op.execute(f"GRANT SELECT, INSERT ON TABLE public.{BLOCKLIST} TO app_user")
    op.execute(f"GRANT SELECT, INSERT, DELETE ON TABLE public.{BLOCKLIST} TO app_admin")

    op.add_column(
        REGISTRATIONS,
        sa.Column(
            "grants",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
    )
