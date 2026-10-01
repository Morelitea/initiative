"""an account keeps why it was suspended

- ``users.status_reason``: the reason a suspension gave, which the time-out
  screen shows. It was read off the suspension's bell line, so that line had
  to be written in the request; now it is a notice like any other. Written
  only by the system engine: no request floor holds UPDATE on the column. An
  account suspended already keeps the reason it was shown, copied from its
  newest suspension line, which is where the screen read it until now.
- The platform floor and the bare login lose the ``notifications_id_seq``
  grant: neither has been able to insert a notification since 0357.

Revision ID: 20261001_0429
Revises: 20261001_0428
Create Date: 2026-10-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

from app.core.config import settings

revision = "20261001_0429"
down_revision = "20261001_0428"
branch_labels = None
depends_on = None


def _platform_base() -> str:
    """Read at apply time, not at import: the platform prefix is a setting, and
    the migrations test swaps it around the chain it runs."""
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_base"


#: Each suspended account's reason, as its newest suspension line gave it.
_REASONS = """
    SELECT DISTINCT ON (n.user_id)
        n.user_id, NULLIF(btrim(n.data ->> 'reason'), '') AS reason
    FROM public.notifications n
    JOIN public.users u ON u.id = n.user_id AND u.status = 'suspended'
    WHERE n.type = 'account_suspended'
    ORDER BY n.user_id, n.created_at DESC, n.id DESC
"""


def upgrade() -> None:
    op.add_column("users", sa.Column("status_reason", sa.Text(), nullable=True))

    # Both tables hold their owner to their policies, which a migration has no
    # request context to satisfy; lifted for the copy and restored after it.
    bind = op.get_bind()
    for table in ("public.users", "public.notifications"):
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    try:
        expected = bind.execute(
            text(f"SELECT count(*) FROM ({_REASONS}) r WHERE r.reason IS NOT NULL")
        ).scalar_one()
        copied = bind.execute(
            text(
                "UPDATE public.users u SET status_reason = r.reason "
                f"FROM ({_REASONS}) r "
                "WHERE r.user_id = u.id AND r.reason IS NOT NULL"
            )
        ).rowcount
        if copied != expected:
            raise RuntimeError(
                f"copied {copied} suspension reasons, expected {expected}"
            )
    finally:
        for table in ("public.users", "public.notifications"):
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    for role in (_platform_base(), "app_user"):
        op.execute(f'REVOKE ALL ON SEQUENCE public.notifications_id_seq FROM "{role}"')


def downgrade() -> None:
    for role in (_platform_base(), "app_user"):
        op.execute(
            f'GRANT USAGE, SELECT ON SEQUENCE public.notifications_id_seq TO "{role}"'
        )
    op.drop_column("users", "status_reason")
