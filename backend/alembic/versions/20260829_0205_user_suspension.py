"""A platform moderator can freeze an account without taking anything away.

``suspended`` is deliberately not ``deactivated``: that one drops every guild
and initiative membership, which is the opposite of frozen. Suspension writes
one column, so lifting it restores the account whole — the memberships, the
grants, the assignments and the content are all still there.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260829_0205"
down_revision = "20260829_0204"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Adding a label is allowed inside the migration's transaction; using it in
    # the same one is not, and nothing here does.
    op.execute("ALTER TYPE user_status ADD VALUE IF NOT EXISTS 'suspended'")


def downgrade() -> None:
    # Postgres cannot drop a label from an enum. Leaving it in place is inert:
    # the upgrade is idempotent, and no row can hold it once the code that
    # writes it is gone. Rows that do are moved back to ``active`` first, since
    # a frozen account with no way to unfreeze it is worse than a live one.
    #
    # The write is set up the way every other ``public.users`` backfill in
    # this directory is (see 0201, 0203).
    conn = op.get_bind()
    op.execute("ALTER TABLE public.users NO FORCE ROW LEVEL SECURITY")
    try:
        conn.execute(
            sa.text(
                "UPDATE public.users SET status = 'active' WHERE status = 'suspended'"
            )
        )
    finally:
        op.execute("ALTER TABLE public.users FORCE ROW LEVEL SECURITY")
