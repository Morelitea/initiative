"""a wiki's pages file under each other again

`parent_page_id` came off in 0309, when a wiki was a flat list. It goes back
on: a page is filed under a page, siblings hold an order, and the headings
inside a page stay what they were — content, in the body, not filing.

Documents borrowed into a wiki keep no parent. Where one is filed would be a
fact about a document that belongs to other places too.

Revision ID: 20260918_0312
Revises: 20260918_0311
Create Date: 2026-09-18
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260918_0312"
down_revision = "20260918_0311"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    with op.batch_alter_table("wiki_pages", schema=None) as batch_op:
        batch_op.add_column(sa.Column("parent_page_id", sa.Integer(), nullable=True))
        batch_op.create_index(
            "ix_wiki_pages_parent_page_id", ["parent_page_id"], unique=False
        )
        batch_op.create_foreign_key(
            "wiki_pages_parent_page_id_fkey",
            "wiki_pages",
            ["parent_page_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    with op.batch_alter_table("wiki_pages", schema=None) as batch_op:
        batch_op.drop_constraint("wiki_pages_parent_page_id_fkey", type_="foreignkey")
        batch_op.drop_index("ix_wiki_pages_parent_page_id")
        batch_op.drop_column("parent_page_id")
