"""The DM rule stays with its reader

The revisions that write the DM rule's functions give them to
``app_dm_reader``. The database bootstrap's ownership handover also claimed
them for ``app_provisioner`` on the next start. It now leaves what the app's
own roles own; this gives these back to the reader.

Revision ID: 20260929_0417
Revises: 20260929_0416
Create Date: 2026-09-29
"""

from alembic import op

revision = "20260929_0417"
down_revision = "20260929_0416"
branch_labels = None
depends_on = None

READER = "app_dm_reader"

#: (function, argument types) of every function the revisions give the reader.
FUNCTIONS: tuple[tuple[str, str], ...] = (
    ("dm_apparent_permission", "integer"),
    ("dm_can_ask", "integer, integer"),
    ("dm_claim_one_time_key", "uuid"),
    ("dm_connection_requester", "integer, integer"),
    ("dm_conversation_direct", "uuid"),
    ("dm_deliverable", "integer"),
    ("dm_device_in_conversation", "uuid, uuid"),
    ("dm_in_conversation", "uuid"),
    ("dm_listable_in_guild", "integer"),
    ("dm_may_connect", "integer"),
    ("dm_mutual_ask", "integer, integer"),
    ("dm_pair_connected", "integer, integer"),
    ("dm_queue_bytes", "integer"),
    ("dm_reachable", "integer"),
    ("dm_roster_answered", "uuid"),
    ("dm_roster_names", "uuid, integer[]"),
    ("dm_roster_unreachable_pair", "integer[]"),
)


def upgrade() -> None:
    # Ownership can only be handed to a role that may create in the schema.
    op.execute(f'GRANT CREATE ON SCHEMA public TO "{READER}"')
    for name, signature in FUNCTIONS:
        op.execute(f'ALTER FUNCTION public.{name}({signature}) OWNER TO "{READER}"')
    op.execute(f'REVOKE CREATE ON SCHEMA public FROM "{READER}"')


def downgrade() -> None:
    # The owner this restores is the one the earlier revisions set; there is
    # no other state to return to.
    pass
