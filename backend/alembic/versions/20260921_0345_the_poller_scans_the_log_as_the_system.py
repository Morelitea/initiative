"""Let the webhook poller scan the change log as the system login.

The poller reads the outbox as each subscription's owner so that RLS, not the
poller, decides what that owner may see.  That is right for a batch and wrong
for the scan that finds the batches: under the owner's guild role every row of
the log goes through ``initiative_access()`` — a SQL function the planner cannot
inline, about a millisecond a call — before the cheap filters get a look, and
the scan covers the whole log every pass to find the handful still owed.  Ten
subscriptions over a few thousand rows is a poller that never finishes a pass
and a database pinned at its CPU limit.

Grant the system login the two log columns that scan reads and the four ledger
columns it checks against, so it keeps BYPASSRLS for that one query.  Which rows
of a transaction the owner may see is still read in the owner's context.
Provisioning contains the same matrix for guilds created after this migration;
this file backfills every existing guild schema and the template.

``USAGE`` on each schema was granted by 20260916_0278 and is not touched here in
either direction.
"""

from sqlalchemy import text
from alembic import op

from app.db.guild_migrations import guild_schema_names

revision = "20260921_0345"
down_revision = "20260921_0344"
branch_labels = None
depends_on = None


SYSTEM_OUTBOX_SCAN_GRANTS: dict[str, tuple[str, ...]] = {
    "event_outbox": ("SELECT (id, txn_id)",),
    "webhook_deliveries": (
        "SELECT (subscription_id, txn_id, delivered_at, next_attempt_at)",
    ),
}


def _grant_to_schema(connection, schema: str) -> None:
    for table, privileges in SYSTEM_OUTBOX_SCAN_GRANTS.items():
        connection.execute(
            text(
                f"GRANT {', '.join(privileges)} ON TABLE "
                f'"{schema}"."{table}" TO app_admin'
            )
        )


def _revoke_from_schema(connection, schema: str) -> None:
    for table, privileges in SYSTEM_OUTBOX_SCAN_GRANTS.items():
        connection.execute(
            text(
                f"REVOKE {', '.join(privileges)} ON TABLE "
                f'"{schema}"."{table}" FROM app_admin'
            )
        )


def upgrade() -> None:
    connection = op.get_bind()
    for schema in guild_schema_names(connection):
        _grant_to_schema(connection, schema)


def downgrade() -> None:
    connection = op.get_bind()
    for schema in guild_schema_names(connection):
        _revoke_from_schema(connection, schema)
