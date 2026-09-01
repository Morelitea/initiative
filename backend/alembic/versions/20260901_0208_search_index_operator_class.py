"""build the search index against the search operator class

The guild search index is matched with ``public.@@@``. That operator and its
GIN operator class are installed once, as a superuser, by
``scripts/create-search-operator.sql`` (or by the compose init script on a fresh
install).

Deployments that have not run it yet still upgrade cleanly: the index is built
on the stock operator class instead, search returns the same rows, and the boot
check says what to run. Installing the objects later moves the provisioning
stamp, and the next boot rebuilds the index on them.

Revision ID: 20260901_0208
Revises: 20260901_0207
Create Date: 2026-09-01
"""

from alembic import op
from sqlalchemy import text

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260901_0208"
down_revision = "20260901_0207"
branch_labels = None
depends_on = None

INDEX = "ix_search_entries_tsv"
OPCLASS = "tsvector_search_ops"


def _opclass_available() -> bool:
    return bool(
        op.get_bind()
        .execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM pg_opclass c "
                "JOIN pg_namespace n ON n.oid = c.opcnamespace "
                "WHERE n.nspname = 'public' AND c.opcname = :o)"
            ),
            {"o": OPCLASS},
        )
        .scalar()
    )


def upgrade() -> None:
    using = f"gin (tsv public.{OPCLASS})" if _opclass_available() else "gin (tsv)"
    run_for_each_guild_schema(op.get_bind(), lambda: _rebuild(using))


def _rebuild(using: str) -> None:
    op.execute(f"DROP INDEX IF EXISTS {INDEX}")
    op.execute(f"CREATE INDEX {INDEX} ON search_entries USING {using}")


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), lambda: _rebuild("gin (tsv)"))
