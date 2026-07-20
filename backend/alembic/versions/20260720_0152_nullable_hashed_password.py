"""Make ``users.hashed_password`` nullable — SSO-only accounts carry no hash.

Accounts provisioned through an identity provider never receive a usable
password; until now they were stored with a random throwaway hash purely to
satisfy the NOT NULL constraint. With the column nullable, new SSO-provisioned
accounts store NULL and every password verification treats a missing hash as
"no password set" (never a match). Existing rows keep whatever hash they have.

Downgrade fills NULLs with ``'!'`` — a marker that is not a valid hash in any
supported scheme, so it can never verify — then restores NOT NULL.

Revision ID: 20260720_0152
Revises: 20260720_0151
Create Date: 2026-07-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260720_0152"
down_revision = "20260720_0151"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "hashed_password",
        existing_type=sa.String(),
        nullable=True,
    )


def downgrade() -> None:
    # users is FORCE ROW LEVEL SECURITY — policy-bound even for the owner this
    # migration runs as, so the UPDATE would silently match zero rows and the
    # SET NOT NULL below would then fail on the remaining NULLs. Lift and
    # restore the flag around the fill, inside the same transaction.
    op.execute("ALTER TABLE public.users NO FORCE ROW LEVEL SECURITY")
    op.execute("UPDATE users SET hashed_password = '!' WHERE hashed_password IS NULL")
    op.execute("ALTER TABLE public.users FORCE ROW LEVEL SECURITY")
    op.alter_column(
        "users",
        "hashed_password",
        existing_type=sa.String(),
        nullable=False,
    )
