"""A challenge can name an address no account holds yet.

``user_email_id`` names one of an account's addresses. A code sent to an
address nobody holds has no such row to point at, and the address still has to
survive the round trip: the code proves it, and the account made afterwards is
made with it.

Kept the way ``user_emails`` keeps one — Fernet ciphertext under the same
``SALT_EMAIL`` — so an address waiting on a sign-up is stored no differently
from one already held. ``NULL`` on every other challenge.

Revision ID: 20260920_0332
Revises: 20260920_0331
Create Date: 2026-09-20
"""

import sqlalchemy as sa
from alembic import op

revision = "20260920_0332"
down_revision = "20260920_0331"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "auth_challenges",
        sa.Column("email_encrypted", sa.String(length=2000), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("auth_challenges", "email_encrypted")
