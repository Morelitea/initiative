"""billing reads a guild's name

The billing service keys on a reference, which is unreadable on purpose — so a
page about somebody's own community has nothing to title itself with. This
widens the column-scoped grant by exactly one column so that page can show the
name the community chose.

One column, named, on a role whose access to this table is otherwise five
columns: it sees ``id`` and ``status`` here, and three caps on
``guild_administration``. Nothing else about a guild becomes readable.

Revision ID: 20260911_0257
Revises: 20260911_0256
Create Date: 2026-09-11
"""

from __future__ import annotations

from alembic import op

from app.core.config import settings

revision = "20260911_0257"
down_revision = "20260911_0256"
branch_labels = None
depends_on = None


def _billing_role() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}initiative_billing"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.execute(f'GRANT SELECT (name) ON public.guilds TO "{_billing_role()}"')


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute(f'REVOKE SELECT (name) ON public.guilds FROM "{_billing_role()}"')
