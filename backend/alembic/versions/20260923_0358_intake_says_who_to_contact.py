"""intake says who to contact

Two columns on the ``app_settings`` singleton, set from the owner's intake
settings page:

* ``intake_general_contact`` — the deployment's catch-all contact address.
* ``intake_contacts`` — one optional address per intake stream, keyed by the
  stream's value.

Nothing is backfilled: every install starts with no address, which is what a
notice that says "contact whoever runs this server" already assumes.

Revision ID: 20260923_0358
Revises: 20260923_0357
Create Date: 2026-09-23
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260923_0358"
down_revision = "20260923_0357"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column("intake_general_contact", sa.String(length=320), nullable=True),
    )
    op.add_column(
        "app_settings",
        sa.Column(
            "intake_contacts",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "intake_contacts")
    op.drop_column("app_settings", "intake_general_contact")
