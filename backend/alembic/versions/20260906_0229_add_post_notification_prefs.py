"""add post notification prefs

Two switches on ``users``: whether a notice going up on a board reaches the
account by email and by push. The in-app bell is not a preference — it is the
list of what happened, and this is one of the things that happened.

One pair for the board as a whole rather than one per initiative. A post is
already an occasional, deliberate thing, and a setting per board would be a
page of switches nobody visits.

Revision ID: 20260906_0229
Revises: 20260905_0229
Create Date: 2026-09-06
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20260906_0229"
down_revision = "20260905_0229"
branch_labels = None
depends_on = None

_USER_PREFS = ("email_posts", "push_posts")


def _write_roles() -> tuple[str, ...]:
    """The floors that still write ``public.users`` — the same pair 0227 named."""
    return (
        f'"{settings.PLATFORM_ROLE_PREFIX}platform_base"',
        "app_user",
    )


def upgrade() -> None:
    for column in _USER_PREFS:
        op.add_column(
            "users",
            sa.Column(
                column,
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
        )
    # The request path's UPDATE on ``public.users`` is a column list computed at
    # 0144, so a column added later is not in it. Name the new ones explicitly;
    # the own-row policies from 0202 still decide whose row they reach.
    for role in _write_roles():
        op.execute(
            f"GRANT UPDATE ({', '.join(_USER_PREFS)}) ON TABLE public.users TO {role}"
        )


def downgrade() -> None:
    for column in reversed(_USER_PREFS):
        op.drop_column("users", column)
