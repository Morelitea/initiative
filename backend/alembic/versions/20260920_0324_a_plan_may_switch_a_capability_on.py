"""a plan may switch a capability on

The billing service already writes a guild's caps and its plan label. It now
also writes the **package of capabilities** that plan grants, which on this
side means three columns it did not hold before:

``banner_image_enabled`` — may upload banner artwork.
``support_enabled`` — may send a help request to whoever runs this deployment.
``auth_options`` — may decide its own sign-in, and its own security standards.

These are the same operator entitlements they have always been, enforced by the
same gates. What changes is who answers for them on a deployment that *has* a
billing service: the plan does, because that is where the question "is this
included" is actually decided, and answering it in two places is how a paying
community ends up without what it paid for.

Nothing here is a statement about price. The role may write which capabilities
a guild holds; it learns nothing about tiers, and a deployment running no
billing service is sent no package and keeps setting all three by hand.

An operator keeps their own write on the system engine, and it still takes
effect immediately. It lasts until the next time billing recomputes the guild's
plan, which re-asserts the package — so a change meant to stick belongs in
billing's support console, next to the plan it belongs to.

Revision ID: 20260920_0324
Revises: 20260920_0323
Create Date: 2026-09-20
"""

from __future__ import annotations

from alembic import op

from app.core.config import settings

revision = "20260920_0324"
down_revision = "20260920_0323"
branch_labels = None
depends_on = None

#: The columns the package resolves to — see ``app.core.billing_capabilities``.
_COLUMNS = "banner_image_enabled, support_enabled, auth_options"


def _billing_role() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}initiative_billing"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    role = _billing_role()
    # SELECT as well as UPDATE: the write's response reads the switches back,
    # which is what lets billing reconcile a package against what it became.
    op.execute(f'GRANT SELECT ({_COLUMNS}) ON public.guild_administration TO "{role}"')
    op.execute(f'GRANT UPDATE ({_COLUMNS}) ON public.guild_administration TO "{role}"')


def downgrade() -> None:
    if not _is_postgres():
        return
    role = _billing_role()
    op.execute(
        f'REVOKE UPDATE ({_COLUMNS}) ON public.guild_administration FROM "{role}"'
    )
    op.execute(
        f'REVOKE SELECT ({_COLUMNS}) ON public.guild_administration FROM "{role}"'
    )
