"""a wiki says where it put the documents it borrowed

A document in a wiki had no place in its list: it was drawn after every page
written there, sorted by name, because there was nowhere to record a place. A
document is not the wiki's to own — it belongs to whatever else it is in too —
so the wiki keeps the record instead: `{"<document id>": position}`, on the
same scale a page's `position` uses.

Revision ID: 20260918_0311
Revises: 20260918_0310
Create Date: 2026-09-18
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260918_0311"
down_revision = "20260918_0310"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    with op.batch_alter_table("wikis", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "document_positions",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'{}'::jsonb"),
                nullable=False,
            )
        )


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    with op.batch_alter_table("wikis", schema=None) as batch_op:
        batch_op.drop_column("document_positions")
