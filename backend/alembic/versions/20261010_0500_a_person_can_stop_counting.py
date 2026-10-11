"""a person can stop counting toward search ranking

Adds ``users.count_toward_engagement_ranking``: whether what this person opens
and changes counts toward the engagement levels search orders by. On for every
account, and theirs to turn off.

The request path writes ``public.users`` through a column-scoped UPDATE (0144),
so the column is named in that grant, as one a person sets for themselves.

Revision ID: 20261010_0500
Revises: 20261010_0499
Create Date: 2026-10-10
"""

from alembic import op

from app.core.config import settings

revision = "20261010_0500"
down_revision = "20261010_0499"
branch_labels = None
depends_on = None

COLUMN = "count_toward_engagement_ranking"


def _write_roles() -> tuple[str, ...]:
    """The request-path roles that hold their UPDATE on ``users`` per column.
    The guild path holds nothing on ``users`` (0221): a person sets this from
    their own account, on the platform path."""
    return (
        f'"{settings.PLATFORM_ROLE_PREFIX}platform_base"',
        "app_user",
    )


def upgrade() -> None:
    op.execute(
        f"ALTER TABLE public.users ADD COLUMN {COLUMN} boolean NOT NULL DEFAULT true"
    )
    for role in _write_roles():
        op.execute(f"GRANT UPDATE ({COLUMN}) ON TABLE public.users TO {role}")


def downgrade() -> None:
    # The grant goes with the column it names.
    op.execute(f"ALTER TABLE public.users DROP COLUMN IF EXISTS {COLUMN}")
