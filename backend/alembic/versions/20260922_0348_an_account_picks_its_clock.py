"""An account picks the clock it reads times on.

Every timestamp the app renders took its 12- or 24-hour shape from whatever
the reader's browser locale said, which an account has no way to disagree
with: somebody on ``en-US`` who thinks in 24-hour time had nowhere to say so.

``users.time_format`` is that answer, and it sits beside ``week_starts_on``
for the same reason — both are conventions about reading a date, not data
about one.

``system`` is the default and means "no answer": the browser's locale decides,
exactly as it did before this column existed. So every existing account keeps
the display it already had, and only the two explicit values change anything.

Revision ID: 20260922_0348
Revises: 20260921_0347
Create Date: 2026-09-22
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20260922_0348"
down_revision = "20260921_0347"
branch_labels = None
depends_on = None


def _write_roles() -> tuple[str, ...]:
    """The floors that write ``public.users`` — 0221 took the guild path off
    this table, and 0222 onwards is this pair."""
    return (
        f'"{settings.PLATFORM_ROLE_PREFIX}platform_base"',
        "app_user",
    )


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "time_format",
            sa.String(length=16),
            nullable=False,
            server_default="system",
        ),
    )
    # UPDATE on ``users`` is a column list computed at 0144, so a column added
    # afterwards is writable by nobody until it is named. This one is written
    # by its own holder through ``PATCH /users/me``, on the platform path; the
    # own-row policies from 0202 still decide whose row that reaches.
    for role in _write_roles():
        op.execute(f"GRANT UPDATE (time_format) ON TABLE public.users TO {role}")


def downgrade() -> None:
    # The grant goes with the column it names.
    op.drop_column("users", "time_format")
