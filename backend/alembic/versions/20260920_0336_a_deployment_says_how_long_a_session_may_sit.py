"""A deployment says how long a session may sit untouched.

``session_max_hours`` is the absolute limit — the longest anybody may stay
signed in however much they use the app. This is the other half: the longest a
session may be *left alone*, which until now only ``AUTH_REFRESH_TTL_DAYS``
answered, and only at deploy time.

``NULL`` keeps that env value, so an upgrade changes nothing. A figure here
narrows it, and a community held to the compliance standard narrows it further
— whichever is strictest binds.

Revision ID: 20260920_0336
Revises: 20260920_0335
Create Date: 2026-09-20
"""

import sqlalchemy as sa
from alembic import op

revision = "20260920_0336"
down_revision = "20260920_0335"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column("session_idle_minutes", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "session_idle_minutes")
