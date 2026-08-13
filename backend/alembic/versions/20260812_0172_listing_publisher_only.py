"""one required name on a listing: publisher

``0168`` added ``author_name``/``author_url``/``author_contact`` beside the
existing ``publisher``, on the theory that who wrote a listing and who ships it
are different questions. In practice they are one question — whoever publishes
is who a reader is trusting, whether that is the person who wrote it or an
organisation shipping someone else's work — and splitting them produced a
required column nothing displayed and two optional ones nothing read.

So the three go away and ``publisher`` carries the requirement, which it is
already shaped for: ``NOT NULL`` since the catalog was introduced, and the
prefix a registry binds to the key that signed its index.

No data is lost that anything consumed: ``publisher`` was populated for every
row (it defaulted to the author's name), so dropping the author columns leaves
each listing with the name it was already displaying.

**The downgrade refills ``author_name`` from ``publisher``, and has to lift
``FORCE`` to do it.** ``marketplace_listings`` is ``FORCE ROW LEVEL SECURITY``
with a SELECT policy and no write policy, so the owner is policy-bound too and
a plain ``UPDATE`` here would match no rows while still reporting success. The
refill therefore runs with forcing lifted and the row count asserted, and
forcing is restored immediately. A server default cannot do this job instead:
Postgres will not accept one that reads another column.

Grants and policies are untouched — these are columns on a table whose SELECT
policy is unconditional and whose writes already belong to the system engine.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260812_0172"
down_revision = "20260812_0171"
branch_labels = None
depends_on = None

_TABLE = "marketplace_listings"


def upgrade() -> None:
    op.drop_column(_TABLE, "author_contact")
    op.drop_column(_TABLE, "author_url")
    op.drop_column(_TABLE, "author_name")


def downgrade() -> None:
    op.add_column(_TABLE, sa.Column("author_name", sa.Text(), nullable=True))
    op.add_column(_TABLE, sa.Column("author_url", sa.Text(), nullable=True))
    op.add_column(_TABLE, sa.Column("author_contact", sa.Text(), nullable=True))

    connection = op.get_bind()
    expected = connection.execute(
        sa.text(f"SELECT count(*) FROM public.{_TABLE}")
    ).scalar_one()
    # Forcing binds the owner as well, and this table has no write policy, so
    # the refill would otherwise match nothing and say it succeeded.
    op.execute(f"ALTER TABLE public.{_TABLE} NO FORCE ROW LEVEL SECURITY")
    try:
        filled = connection.execute(
            sa.text(f"UPDATE public.{_TABLE} SET author_name = publisher")
        ).rowcount
    finally:
        op.execute(f"ALTER TABLE public.{_TABLE} FORCE ROW LEVEL SECURITY")
    if filled != expected:
        raise RuntimeError(
            f"author_name refill touched {filled} of {expected} listings; "
            "refusing to set NOT NULL over rows it could not see"
        )

    op.alter_column(_TABLE, "author_name", nullable=False)
