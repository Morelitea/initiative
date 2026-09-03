"""Whether a direct message reaches you by email and by push.

The conventional pair, the same shape every other notification category on
``public.users`` already has. There is no third switch for hiding the sender's
name: a per-field toggle would be the only one of its kind in the product, and
who a message is from is already in the conversation roster. What no channel
carries is what the message says.

Revision ID: 20260905_0227
Revises: 20260905_0226
Create Date: 2026-09-05
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20260905_0227"
down_revision = "20260905_0226"
branch_labels = None
depends_on = None

_USER_PREFS = ("email_direct_messages", "push_direct_messages")


def _write_roles() -> tuple[str, ...]:
    """The floors that still write ``public.users`` — 0221 took the guild path
    off this table, and 0222 is the current list."""
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

    # The rolled-up direct-message line is written on the system engine, which
    # already creates and reaps notifications but could not rewrite one. A
    # rollup rewrites a row it wrote itself.
    op.execute("GRANT UPDATE ON TABLE public.notifications TO app_admin")


def downgrade() -> None:
    op.execute("REVOKE UPDATE ON TABLE public.notifications FROM app_admin")
    for column in reversed(_USER_PREFS):
        op.drop_column("users", column)
