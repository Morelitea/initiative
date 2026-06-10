"""Apply a guild-scoped schema change to every guild schema, from a migration.

Under schema-per-guild a guild-scoped table (tasks, projects, documents, …)
exists once per guild schema — ``guild_1.tasks``, ``guild_2.tasks``, … — plus the
legacy ``public.tasks`` (until the data conversion drops it). A normal Alembic
migration runs once against ``public``, so it would only change one of them.

The forward pattern has two halves, kept in sync:

1. **Existing guilds** — a guild-scoped migration calls
   :func:`apply_to_all_guild_schemas` in its ``upgrade()`` (and the reverse in
   ``downgrade()``). The migration owns the DDL (so the migration stays a
   self-contained, immutable record of *what* changed); this helper only owns the
   stable mechanism of *where* it runs.

2. **New guilds** — provisioning builds a fresh guild schema by running
   ``alembic/guild/guild_schema.sql`` (see ``app.db.schema_provisioning``). After
   landing a guild-scoped migration, regenerate that artifact
   (``python scripts/gen_guild_schema.py`` → commit) so guilds created later
   include the change.

The **drift-guard test** (``schema_provisioning_test.test_guild_schema_matches_alembic_public``)
provisions a fresh schema and diffs it against ``public``: if you applied a delta
to existing schemas but forgot to regenerate the artifact (or vice-versa), a new
guild won't match and CI fails. The two halves can't silently diverge.

Example migration::

    from alembic import op
    from app.db.guild_migrations import apply_to_all_guild_schemas

    def upgrade() -> None:
        apply_to_all_guild_schemas(
            op.get_bind(),
            "ALTER TABLE tasks ADD COLUMN archived boolean NOT NULL DEFAULT false",
        )

    def downgrade() -> None:
        apply_to_all_guild_schemas(op.get_bind(), "ALTER TABLE tasks DROP COLUMN archived")
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

# Guild schemas are named ``guild_<id>`` (see schema_provisioning.guild_schema_name).
_GUILD_SCHEMA_REGEX = "^guild_[0-9]+$"


def guild_schema_names(connection: Connection) -> list[str]:
    """Every provisioned guild schema, sorted. For guild-scoped migrations."""
    rows = connection.execute(
        text("SELECT nspname FROM pg_namespace WHERE nspname ~ :pat ORDER BY nspname"),
        {"pat": _GUILD_SCHEMA_REGEX},
    )
    return [row[0] for row in rows]


def apply_to_all_guild_schemas(
    connection: Connection,
    *statements: str,
    include_public: bool = True,
) -> None:
    """Run schema-relative DDL in every guild schema (and ``public`` by default).

    Each statement must be written WITHOUT a schema qualifier — e.g.
    ``ALTER TABLE tasks ADD COLUMN …`` — because it is run once per target schema
    with ``search_path`` pointed there (unqualified table/enum names resolve in
    that schema, falling through to ``public`` for shared types). Pass several
    statements to apply them as an ordered group per schema.

    ``include_public`` keeps the legacy ``public`` copy in step until the data
    conversion drops it; pass ``False`` once those copies are gone (and a
    ``guild_template`` exists, add it to the targets).

    Reminder: after using this in a migration, regenerate
    ``alembic/guild/guild_schema.sql`` so newly provisioned guilds get the change.
    """
    targets = (["public"] if include_public else []) + guild_schema_names(connection)
    try:
        for schema in targets:
            # set_config (not SET) so it lands on this exact connection, matching
            # how set_rls_context routes; schema name comes from pg_namespace so
            # it's already a safe identifier.
            connection.execute(
                text("SELECT set_config('search_path', :sp, false)"),
                {"sp": f"{schema}, public"},
            )
            for statement in statements:
                connection.execute(text(statement))
    finally:
        connection.execute(text("SELECT set_config('search_path', 'public', false)"))
