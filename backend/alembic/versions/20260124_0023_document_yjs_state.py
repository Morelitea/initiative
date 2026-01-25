"""Add Yjs state columns to documents for collaborative editing.

Revision ID: 20260124_0023
Revises: 20260121_0022
Create Date: 2026-01-24

Adds columns to store Yjs CRDT state for real-time collaboration:
- yjs_state: Binary blob containing the Y.Doc state
- yjs_updated_at: Timestamp of last Yjs sync

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260124_0023"
down_revision: Union[str, None] = "20260121_0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("yjs_state", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("yjs_updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("documents", "yjs_updated_at")
    op.drop_column("documents", "yjs_state")
