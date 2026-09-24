"""a session finds its children

``auth_sessions.parent_id`` gets an index. Both walks down a rotation chain go
from a row to its children: ``revoke_chain`` ending a sign-in, and the stream
re-check finding the live row a sign-in has reached since a connection was
opened on it. Without the index each step of either walk reads the table.

No rows move, and no grant or policy changes.

Revision ID: 20260923_0369
Revises: 20260923_0368
Create Date: 2026-09-23
"""

from alembic import op

revision = "20260923_0369"
down_revision = "20260923_0368"
branch_labels = None
depends_on = None

INDEX = "ix_auth_sessions_parent_id"


def upgrade() -> None:
    op.create_index(INDEX, "auth_sessions", ["parent_id"], if_not_exists=True)


def downgrade() -> None:
    op.drop_index(INDEX, table_name="auth_sessions", if_exists=True)
