"""one free community each

``guild_administration.plan_is_free`` is billing's answer to the only question
this app needs to ask about money: *is this community on a plan that charges
nobody?* Not which plan, not what it costs — those stay on the other side of
the boundary, where the price book is.

**A deployment with no billing service is unaffected.** Nothing writes this
column there, the gate that reads it is skipped when the billing endpoints are
not configured, and a self-hosted install goes on making as many communities as
it likes.

Revision ID: 20260920_0325
Revises: 20260920_0324
Create Date: 2026-09-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20260920_0325"
down_revision = "20260920_0324"
branch_labels = None
depends_on = None


def _billing_role() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}initiative_billing"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.add_column(
        "guild_administration",
        sa.Column("plan_is_free", sa.Boolean(), nullable=True),
    )
    if not _is_postgres():
        return
    role = _billing_role()
    op.execute(
        f'GRANT SELECT (plan_is_free) ON public.guild_administration TO "{role}"'
    )
    op.execute(
        f'GRANT UPDATE (plan_is_free) ON public.guild_administration TO "{role}"'
    )


def downgrade() -> None:
    if _is_postgres():
        role = _billing_role()
        op.execute(
            f'REVOKE UPDATE (plan_is_free) ON public.guild_administration FROM "{role}"'
        )
        op.execute(
            f'REVOKE SELECT (plan_is_free) ON public.guild_administration FROM "{role}"'
        )
    op.drop_column("guild_administration", "plan_is_free")
