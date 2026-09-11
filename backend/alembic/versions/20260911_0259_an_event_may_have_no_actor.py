"""an event may have no actor

``audit_events.actor_user_id`` means "who did it", and some things worth
recording are done by nobody signed in. A refused sign-in is the first: the
request that made it is unauthenticated, and the account the address resolves
to is what the attempt was *against* rather than who made it. The board reads
this column as the person, so the account belongs in ``target_user_id``.

The column therefore becomes nullable, and such an event records a target and
no actor. The reader already resolves an absent id to no party.

Revision ID: 20260911_0259
Revises: 20260911_0258
Create Date: 2026-09-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260911_0259"
down_revision = "20260911_0258"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "audit_events",
        "actor_user_id",
        existing_type=sa.Integer(),
        nullable=True,
    )


def downgrade() -> None:
    # Rows with no actor cannot be represented under NOT NULL, and inventing an
    # actor for them would be a false record. They are removed instead.
    op.execute("DELETE FROM public.audit_events WHERE actor_user_id IS NULL")
    op.alter_column(
        "audit_events",
        "actor_user_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
