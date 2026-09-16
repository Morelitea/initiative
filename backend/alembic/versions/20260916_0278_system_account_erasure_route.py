"""Give account erasure a narrow direct guild route.

The system login can already assume every guild role, but doing so drops its
BYPASSRLS attribute.  Account erasure must remove embedded names regardless of
tenant policy, and the RLS-expanded comments UPDATE becomes pathologically
expensive after a full test run has churned the PostgreSQL catalogs.

Grant only the scrubbed tables and the closure their frozen, capture, and search
triggers need.  Provisioning contains the same matrix for guilds created after
this migration; this file backfills every existing guild schema and the template.
"""

from sqlalchemy import text
from alembic import op

from app.db.guild_migrations import guild_schema_names

revision = "20260916_0278"
down_revision = "20260915_0277"
branch_labels = None
depends_on = None


SYSTEM_GUILD_MAINTENANCE_GRANTS: dict[str, tuple[str, ...]] = {
    "comments": ("SELECT", "UPDATE"),
    "documents": ("SELECT", "UPDATE"),
    "posts": ("SELECT", "UPDATE"),
    "task_assignment_digest_items": ("SELECT", "UPDATE"),
    "tasks": ("SELECT",),
    "projects": ("SELECT",),
    "queues": ("SELECT",),
    "counter_groups": ("SELECT",),
    "calendars": ("SELECT",),
    "dashboards": ("SELECT",),
    "galleries": ("SELECT",),
    "initiatives": ("SELECT",),
    "event_outbox": (
        "INSERT (txn_id, occurred_at, actor_user_id, initiative_id, "
        "resource_type, resource_id, action, changed, parents)",
    ),
    "search_entries": (
        "SELECT (entity_type, entity_id)",
        "INSERT (entity_type, entity_id, chunk_ix, initiative_id, dac_tool, "
        "dac_id, title, body, archived, template, updated_at, tsv)",
        "DELETE",
    ),
}

SYSTEM_GUILD_MAINTENANCE_SEQUENCE_GRANTS: dict[str, tuple[str, ...]] = {
    "event_outbox_id_seq": ("USAGE",),
}


def _grant_to_schema(connection, schema: str) -> None:
    connection.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO app_admin'))
    for table, privileges in SYSTEM_GUILD_MAINTENANCE_GRANTS.items():
        connection.execute(
            text(
                f"GRANT {', '.join(privileges)} ON TABLE "
                f'"{schema}"."{table}" TO app_admin'
            )
        )
    for sequence, privileges in SYSTEM_GUILD_MAINTENANCE_SEQUENCE_GRANTS.items():
        connection.execute(
            text(
                f"GRANT {', '.join(privileges)} ON SEQUENCE "
                f'"{schema}"."{sequence}" TO app_admin'
            )
        )


def _revoke_from_schema(connection, schema: str) -> None:
    for table, privileges in SYSTEM_GUILD_MAINTENANCE_GRANTS.items():
        connection.execute(
            text(
                f"REVOKE {', '.join(privileges)} ON TABLE "
                f'"{schema}"."{table}" FROM app_admin'
            )
        )
    for sequence, privileges in SYSTEM_GUILD_MAINTENANCE_SEQUENCE_GRANTS.items():
        connection.execute(
            text(
                f"REVOKE {', '.join(privileges)} ON SEQUENCE "
                f'"{schema}"."{sequence}" FROM app_admin'
            )
        )
    connection.execute(text(f'REVOKE USAGE ON SCHEMA "{schema}" FROM app_admin'))


def upgrade() -> None:
    connection = op.get_bind()
    for schema in guild_schema_names(connection):
        _grant_to_schema(connection, schema)


def downgrade() -> None:
    connection = op.get_bind()
    for schema in guild_schema_names(connection):
        _revoke_from_schema(connection, schema)
