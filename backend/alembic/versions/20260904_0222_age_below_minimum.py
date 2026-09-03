"""The other answer to the age question.

``users.age_below_minimum_at`` records that an account answered as being under
the minimum age. The date it gave is not kept here either — this is a
timestamp, like its opposite number, and for the same reason: what a deployment
needs is that the question was answered, not what the answer's arithmetic was.

Holding it is what lets the question be asked once. Without a record of the
answer the only options are to accept a fresh attempt every time or to keep the
date, and keeping the date is the thing the surface promises not to do.

``ck_users_age_answer`` holds the pair honest: an account has confirmed, or has
answered under, or has answered neither — never both.

``public.users`` grants its request-path UPDATE per column (0144), so a new
column is unwritable until it is named. It is named for the two floors that
still reach the table: ``platform_base`` and ``app_user``.

**Not ``app_guild_base``.** That role held every column here until 0221 took
the guild path off ``public.users`` altogether — it reads
``public.guild_member_profiles`` now. Granting a new column to all three
floors was right before 0221 and would quietly undo it after, which is what
``security_invariants_test`` is there to catch.

Revision ID: 20260904_0222
Revises: 20260904_0221
Create Date: 2026-09-04
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20260904_0222"
down_revision = "20260904_0221"
branch_labels = None
depends_on = None


def _write_roles() -> tuple[str, ...]:
    """The floors that still write ``public.users`` — see the note above."""
    return (
        f'"{settings.PLATFORM_ROLE_PREFIX}platform_base"',
        "app_user",
    )


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("age_below_minimum_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_users_age_answer",
        "users",
        "age_confirmed_at IS NULL OR age_below_minimum_at IS NULL",
    )
    for role in _write_roles():
        op.execute(
            f"GRANT UPDATE (age_below_minimum_at) ON TABLE public.users TO {role}"
        )


def downgrade() -> None:
    op.drop_constraint("ck_users_age_answer", "users", type_="check")
    # The grant goes with the column it names.
    op.drop_column("users", "age_below_minimum_at")
