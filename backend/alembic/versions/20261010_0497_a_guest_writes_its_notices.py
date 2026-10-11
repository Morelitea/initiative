"""a guest writes its notices

``guest_base`` appends to ``public.notice_outbox`` and is given the table's
sequence beside it, as the other floors that append there are.

Revision ID: 20261010_0497
Revises: 20261010_0496
Create Date: 2026-10-10
"""

from alembic import op

revision = "20261010_0497"
down_revision = "20261010_0496"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "GRANT USAGE, SELECT ON SEQUENCE public.notice_outbox_id_seq TO guest_base"
    )


def downgrade() -> None:
    op.execute(
        "REVOKE USAGE, SELECT ON SEQUENCE public.notice_outbox_id_seq FROM guest_base"
    )
