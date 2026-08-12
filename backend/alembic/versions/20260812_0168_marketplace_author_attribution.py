"""required author attribution on marketplace listings

Every listing states who wrote it. ``author_name`` is NOT NULL so the
requirement holds at the database as well as in the manifest validator;
``author_url`` and ``author_contact`` are the optional ways to reach them.

**Existing rows take the value as part of the ALTER, not as a later UPDATE.**
``marketplace_listings`` carries ``FORCE ROW LEVEL SECURITY`` and a read-only
policy, and a migration runs with no request context — so ordinary DML here
would match no rows and report success. Adding the column with a server default
fills every existing row as part of the DDL, which is not policy-bound, and the
NOT NULL constraint is then verified by Postgres across the whole table rather
than by a row count this connection cannot see. Every row that exists at this
point is a ``core.*`` listing shipped in this build, so ``Initiative`` is the
correct value for all of them.

The default is dropped immediately afterwards: it exists to fill history, and
leaving it in place would let a future insert quietly attribute a listing to
Initiative instead of failing.

Grants and policies are untouched — these are new columns on a table whose
SELECT policy is unconditional and whose writes already belong to the system
engine, so nothing about who may read or write it changes.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260812_0168"
down_revision = "20260812_0167"
branch_labels = None
depends_on = None

_TABLE = "marketplace_listings"

#: What the listings that exist at this revision are: shipped built-ins.
_BUILTIN_AUTHOR = "Initiative"


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column(
            "author_name",
            sa.Text(),
            nullable=False,
            server_default=_BUILTIN_AUTHOR,
        ),
    )
    op.alter_column(_TABLE, "author_name", server_default=None)
    op.add_column(_TABLE, sa.Column("author_url", sa.Text(), nullable=True))
    op.add_column(_TABLE, sa.Column("author_contact", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column(_TABLE, "author_contact")
    op.drop_column(_TABLE, "author_url")
    op.drop_column(_TABLE, "author_name")
