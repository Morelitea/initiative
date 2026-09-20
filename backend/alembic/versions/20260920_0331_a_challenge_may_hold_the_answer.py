"""A challenge can carry the answer it is waiting for, and the address it went to.

Every challenge so far is answered with the value it was issued under: the
client was handed it, and presenting it back is the whole proof. A code sent
by mail is not like that. Two things are handed out — a handle, to the browser
that asked, and a code, to the mailbox — and the row has to recognise the pair.

The handle stays in ``challenge_hash``, so the lookup and the attempt count are
the one statement they already are, and ``answer_hash`` holds the code. ``NULL``
on every challenge whose value is its own answer.

``user_email_id`` says which of the account's addresses the code went to,
following ``user_tokens.user_email_id``, which carries the same fact for the
same reason: an account may hold more than one, and what arriving at a
particular address proves is about that address.

Revision ID: 20260920_0331
Revises: 20260920_0330
Create Date: 2026-09-20
"""

import sqlalchemy as sa
from alembic import op

revision = "20260920_0331"
down_revision = "20260920_0330"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "auth_challenges",
        sa.Column("answer_hash", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "auth_challenges",
        sa.Column(
            "user_email_id",
            sa.Integer(),
            sa.ForeignKey("user_emails.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("auth_challenges", "user_email_id")
    op.drop_column("auth_challenges", "answer_hash")
