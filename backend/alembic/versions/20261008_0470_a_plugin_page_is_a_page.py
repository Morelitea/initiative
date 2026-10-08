"""A plug-in page is a page: rename what the contract called an embed.

The plug-in contract (SDK 5.0) calls the screens a plug-in has framed in
Initiative ``pages``, leaving "embed" to the editor. This revision moves the
stored names to match, with nothing kept under the old ones:

* ``plugin_service_registrations.embed_origin`` is ``page_origin``.
* A stored definition's ``embeds`` key is ``pages``, and its ``features`` say
  ``pages`` for ``embeds``, sorted as the normalizer stores them. That is every
  published listing version and every community's pinned install.

The rewrite runs with user triggers off: nothing about the rows changed but
their spelling, so nothing is captured or delivered for it.

Revision ID: 20261008_0470
Revises: 20261007_0469
Create Date: 2026-10-08
"""

from collections.abc import Callable

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import guild_schema_names

revision = "20261008_0470"
down_revision = "20261007_0469"
branch_labels = None
depends_on = None


def _with_rows_writable(bind, table: str, fn: Callable[[], None]) -> None:
    """Run ``fn`` with the table's RLS unforced and its user triggers off."""
    forced = bool(
        bind.execute(
            sa.text(
                "SELECT relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:t)"
            ),
            {"t": table},
        ).scalar()
    )
    if forced:
        bind.execute(sa.text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY"))
    bind.execute(sa.text(f"ALTER TABLE {table} DISABLE TRIGGER USER"))
    try:
        fn()
    finally:
        bind.execute(sa.text(f"ALTER TABLE {table} ENABLE TRIGGER USER"))
        if forced:
            bind.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))


def _respell(bind, table: str, old: str, new: str) -> None:
    """Move ``definition -> old`` to ``new``, and the feature of that name."""

    def run() -> None:
        bind.execute(
            sa.text(
                f"UPDATE {table} SET definition = "
                "(definition - CAST(:old AS text)) "
                "|| jsonb_build_object(CAST(:new AS text), definition -> CAST(:old AS text)) "
                "WHERE definition ? CAST(:old AS text)"
            ),
            {"old": old, "new": new},
        )
        bind.execute(
            sa.text(
                f"UPDATE {table} SET definition = jsonb_set(definition, '{{features}}', "
                "(SELECT jsonb_agg(f ORDER BY f #>> '{}' COLLATE \"C\") FROM ("
                "SELECT CASE WHEN x = to_jsonb(CAST(:old AS text)) "
                "THEN to_jsonb(CAST(:new AS text)) ELSE x END AS f "
                "FROM jsonb_array_elements(definition -> 'features') AS x) AS s)) "
                "WHERE jsonb_typeof(definition -> 'features') = 'array' "
                "AND definition -> 'features' ? CAST(:old AS text)"
            ),
            {"old": old, "new": new},
        )

    _with_rows_writable(bind, table, run)


def _definitions(bind, old: str, new: str) -> None:
    _respell(bind, "public.marketplace_listing_versions", old, new)
    for schema in guild_schema_names(bind):
        _respell(bind, f'"{schema}".guild_plugins', old, new)


def upgrade() -> None:
    op.alter_column(
        "plugin_service_registrations",
        "embed_origin",
        new_column_name="page_origin",
        schema="public",
    )
    _definitions(op.get_bind(), "embeds", "pages")


def downgrade() -> None:
    _definitions(op.get_bind(), "pages", "embeds")
    op.alter_column(
        "plugin_service_registrations",
        "page_origin",
        new_column_name="embed_origin",
        schema="public",
    )
