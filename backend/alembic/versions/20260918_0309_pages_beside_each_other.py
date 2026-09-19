"""a wiki's pages sit beside each other, and some are drafts

Sub-pages are gone. A wiki's structure is the pages in a list and the headings
inside each one, so the tree column goes and the count that described it goes
with it. In their place: a page can be a draft, which only the people who write
the wiki are shown, and a wiki can say when a page was last written to.

Revision ID: 20260918_0309
Revises: 20260918_0308
Create Date: 2026-09-18
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260918_0309"
down_revision = "20260918_0308"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    with op.batch_alter_table("wiki_pages", schema=None) as batch_op:
        # A page somebody is still writing. Editors see it; everybody else is
        # not told it exists.
        batch_op.add_column(
            sa.Column(
                "is_draft",
                sa.Boolean(),
                server_default=sa.text("false"),
                nullable=False,
            )
        )
        # The spine was a tree. Dropping the column takes its index and its
        # self-referencing key with it.
        batch_op.drop_column("parent_page_id")

    with op.batch_alter_table("wikis", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "show_updated_at",
                sa.Boolean(),
                server_default=sa.text("true"),
                nullable=False,
            )
        )
        # This counted the pages filed under a page. There are none.
        batch_op.drop_column("show_page_counts")


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)


def _apply_downgrade() -> None:
    with op.batch_alter_table("wikis", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "show_page_counts",
                sa.Boolean(),
                server_default=sa.text("false"),
                nullable=False,
            )
        )
        batch_op.drop_column("show_updated_at")

    with op.batch_alter_table("wiki_pages", schema=None) as batch_op:
        batch_op.add_column(sa.Column("parent_page_id", sa.Integer(), nullable=True))
        batch_op.drop_column("is_draft")

    # The key and the index the column carried before, restored with it.
    op.create_foreign_key(
        "wiki_pages_parent_page_id_fkey",
        "wiki_pages",
        "wiki_pages",
        ["parent_page_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_wiki_pages_parent_page_id", "wiki_pages", ["parent_page_id"], unique=False
    )
