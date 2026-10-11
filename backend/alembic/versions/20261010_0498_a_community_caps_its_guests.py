"""a community caps its guests

- ``guild_administration.max_guests``: how many guests a community may have
  at once. NULL is no cap and 0 takes no new guests; never negative, as for
  ``max_users``.
- The billing role reads and writes it beside the other caps.

Revision ID: 20261010_0498
Revises: 20261010_0497
Create Date: 2026-10-10
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20261010_0498"
down_revision = "20261010_0497"
branch_labels = None
depends_on = None

_CHECK = "ck_guild_administration_max_guests_nonnegative"


def _billing_role() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}initiative_billing"


def upgrade() -> None:
    op.add_column(
        "guild_administration", sa.Column("max_guests", sa.Integer(), nullable=True)
    )
    op.create_check_constraint(
        _CHECK, "guild_administration", "max_guests IS NULL OR max_guests >= 0"
    )
    op.execute(
        f"GRANT SELECT (max_guests), UPDATE (max_guests) "
        f'ON public.guild_administration TO "{_billing_role()}"'
    )


def downgrade() -> None:
    op.execute(
        f"REVOKE SELECT (max_guests), UPDATE (max_guests) "
        f'ON public.guild_administration FROM "{_billing_role()}"'
    )
    op.drop_constraint(_CHECK, "guild_administration")
    op.drop_column("guild_administration", "max_guests")
