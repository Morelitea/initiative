"""a wiki keeps its home page

``wikis.home_page_id`` names the page a wiki opens on, and the model has always
declared it a key to ``wiki_pages`` that lets go (``ON DELETE SET NULL``). The
revision that made the table declared it ``use_alter``, which ``create_table``
leaves out, so no schema has it: a purged home page left the wiki naming a page
that no longer exists.

In every guild schema that lacks it, this clears any home page that no longer
exists and adds the key. The table's row security and request triggers (the
freeze, change capture, search) are held while those rows change, so archived
and trashed wikis are put right too.

The downgrade drops the key, which is the shape every schema had before.

Revision ID: 20261010_0495
Revises: 20261010_0494
Create Date: 2026-10-10
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20261010_0495"
down_revision = "20261010_0494"
branch_labels = None
depends_on = None

KEY = "wikis_home_page_id_fkey"


def _has_key() -> bool:
    return bool(
        op.get_bind().scalar(
            sa.text(
                """
                SELECT EXISTS (
                    SELECT 1 FROM pg_constraint c
                    JOIN pg_attribute a
                      ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
                    WHERE c.conrelid = 'wikis'::regclass
                      AND c.contype = 'f'
                      AND a.attname = 'home_page_id'
                )
                """
            )
        )
    )


def _add() -> None:
    if _has_key():
        return
    op.execute("ALTER TABLE wikis NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE wikis DISABLE TRIGGER USER")
    op.execute(
        """
        UPDATE wikis w SET home_page_id = NULL
        WHERE w.home_page_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM wiki_pages p WHERE p.id = w.home_page_id)
        """
    )
    op.execute("ALTER TABLE wikis ENABLE TRIGGER USER")
    op.execute("ALTER TABLE wikis FORCE ROW LEVEL SECURITY")
    op.create_foreign_key(
        KEY, "wikis", "wiki_pages", ["home_page_id"], ["id"], ondelete="SET NULL"
    )


def _drop() -> None:
    op.execute(f"ALTER TABLE wikis DROP CONSTRAINT IF EXISTS {KEY}")


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _add)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _drop)
