"""An installed app is a sector like any other

``identity_refs`` already holds a pairwise pseudonymous identifier per sector
(OpenID Connect Core §8.1). ``guild_app_subjects`` held the same thing for one
more sector — an installed app — with its own table, its own service and its own
vocabulary. This folds it in and removes it.

An install is identified by ``(sector_guild_id, sector_id)`` rather than an id
alone, because install ids are per-guild-schema and so are not unique on their
own. Neither column is a foreign key: ``guild_apps`` lives in a guild schema and
this table does not, so an install's references are removed by
``services.marketplace.app_refs.drop_install_refs`` and a guild's by the guild
deletion path.

No data is carried. A reference is what one app calls one member, so a value
that moved would leave the app looking at a stranger either way; the migration
counts what it removes and says so.

See ``history/opaque-identity-design.md`` §10.

Revision ID: 20260910_0250
Revises: 20260910_0249
Create Date: 2026-09-10
"""

import logging

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import apply_to_all_guild_schemas, guild_schema_names

revision = "20260910_0250"
down_revision = "20260910_0249"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

#: The live-reference index, before and after. NULLS NOT DISTINCT so the sector
#: columns compare equal when unset — a platform-wide sector leaves both NULL,
#: and the default would read two such rows as different. Same reasoning as
#: ``resource_grants_unique_grantee`` in 20260909_0246.
_LIVE_BEFORE = "(entity_type, entity_id, purpose)"
_LIVE_AFTER = "(entity_type, entity_id, purpose, sector_guild_id, sector_id)"


def _live_index(columns: str, nulls_not_distinct: bool) -> str:
    clause = " NULLS NOT DISTINCT" if nulls_not_distinct else ""
    return (
        f"CREATE UNIQUE INDEX ix_identity_refs_live ON public.identity_refs "
        f"{columns}{clause} WHERE retired_at IS NULL"
    )


def _report_discarded(connection) -> None:
    """Say how many subjects are being removed, per guild that has any."""
    total = 0
    for schema in guild_schema_names(connection):
        if schema == "guild_template":
            continue
        count = connection.execute(
            sa.text(f'SELECT count(*) FROM "{schema}".guild_app_subjects')
        ).scalar_one()
        if count:
            total += count
            logger.warning("%s: removing %s app subject(s)", schema, count)
    if total:
        logger.warning(
            "removed %s app subject(s); each install mints a fresh reference for "
            "a member on its next handoff",
            total,
        )


def upgrade() -> None:
    connection = op.get_bind()
    _report_discarded(connection)

    op.add_column(
        "identity_refs", sa.Column("sector_guild_id", sa.Integer(), nullable=True)
    )
    op.add_column("identity_refs", sa.Column("sector_id", sa.Integer(), nullable=True))

    op.execute("DROP INDEX IF EXISTS public.ix_identity_refs_live")
    op.execute(_live_index(_LIVE_AFTER, nulls_not_distinct=True))
    op.create_index(
        "ix_identity_refs_sector",
        "identity_refs",
        ["sector_guild_id", "sector_id"],
    )

    apply_to_all_guild_schemas(connection, "DROP TABLE IF EXISTS guild_app_subjects")


def downgrade() -> None:
    connection = op.get_bind()
    apply_to_all_guild_schemas(
        connection,
        """
        CREATE TABLE IF NOT EXISTS guild_app_subjects (
            id serial PRIMARY KEY,
            guild_id integer NOT NULL REFERENCES public.guilds(id) ON DELETE CASCADE,
            app_id integer NOT NULL REFERENCES guild_apps(id) ON DELETE CASCADE,
            user_id integer NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
            subject varchar(32) NOT NULL,
            created_at timestamptz NOT NULL,
            CONSTRAINT guild_app_subjects_unique_member UNIQUE (app_id, user_id),
            CONSTRAINT guild_app_subjects_unique_subject UNIQUE (subject)
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_guild_app_subjects_guild_id "
        "ON guild_app_subjects (guild_id)",
        "CREATE INDEX IF NOT EXISTS ix_guild_app_subjects_app_id "
        "ON guild_app_subjects (app_id)",
        "CREATE INDEX IF NOT EXISTS ix_guild_app_subjects_user_id "
        "ON guild_app_subjects (user_id)",
    )

    # The rows themselves are not restored — see the module docstring.
    op.drop_index("ix_identity_refs_sector", table_name="identity_refs")
    op.execute("DROP INDEX IF EXISTS public.ix_identity_refs_live")
    op.execute("DELETE FROM public.identity_refs WHERE purpose = 'app'")
    op.execute(_live_index(_LIVE_BEFORE, nulls_not_distinct=False))
    op.drop_column("identity_refs", "sector_id")
    op.drop_column("identity_refs", "sector_guild_id")
