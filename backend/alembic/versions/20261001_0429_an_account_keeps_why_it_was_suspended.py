"""an account keeps why it was suspended

- ``users.status_reason``: the reason a suspension gave, which the time-out
  screen shows. It was read off the suspension's bell line, so that line had
  to be written in the request; now it is a notice like any other. Written
  only by the system engine: no request floor holds UPDATE on the column.
- The platform floor and the bare login lose the ``notifications_id_seq``
  grant: neither has been able to insert a notification since 0357.

Revision ID: 20261001_0429
Revises: 20261001_0428
Create Date: 2026-10-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20261001_0429"
down_revision = "20261001_0428"
branch_labels = None
depends_on = None


def _platform_base() -> str:
    """Read at apply time, not at import: the platform prefix is a setting, and
    the migrations test swaps it around the chain it runs."""
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_base"


def upgrade() -> None:
    op.add_column("users", sa.Column("status_reason", sa.Text(), nullable=True))
    for role in (_platform_base(), "app_user"):
        op.execute(f'REVOKE ALL ON SEQUENCE public.notifications_id_seq FROM "{role}"')


def downgrade() -> None:
    for role in (_platform_base(), "app_user"):
        op.execute(
            f'GRANT USAGE, SELECT ON SEQUENCE public.notifications_id_seq TO "{role}"'
        )
    op.drop_column("users", "status_reason")
