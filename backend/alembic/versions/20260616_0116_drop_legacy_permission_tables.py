"""Drop the 8 legacy per-resource permission tables (DAC consolidation, final).

All access now resolves through resource_grants (backfilled in 0115); these tables
receive no reads or writes. Drop them in public AND in every guild schema. The
``*_permission_level`` Postgres enum types are left in place (harmless once
orphaned, and the Python level enums are unaffected).

Not reversibly recreated here — the data lives in resource_grants; restoring the
old shape would require re-deriving it. Downgrade recreates nothing.

Revision ID: 20260616_0116
Revises: 20260616_0115
Create Date: 2026-06-16
"""

from alembic import op
from sqlalchemy import text

revision = "20260616_0116"
down_revision = "20260616_0115"
branch_labels = None
depends_on = None

_TABLES = [
    "project_permissions",
    "project_role_permissions",
    "document_permissions",
    "document_role_permissions",
    "queue_permissions",
    "queue_role_permissions",
    "counter_group_permissions",
    "counter_group_role_permissions",
]


def _guild_schemas(conn) -> list[str]:
    rows = conn.execute(
        text("SELECT nspname FROM pg_namespace WHERE nspname LIKE 'guild\\_%'")
    ).all()
    return [r[0] for r in rows]


def upgrade() -> None:
    conn = op.get_bind()
    for schema in _guild_schemas(conn):
        conn.execute(text(f'SET search_path TO "{schema}", public'))
        for table in _TABLES:
            conn.execute(text(f'DROP TABLE IF EXISTS "{table}" CASCADE'))
    conn.execute(text("SET search_path TO public"))
    for table in _TABLES:
        conn.execute(text(f'DROP TABLE IF EXISTS public."{table}" CASCADE'))


def downgrade() -> None:
    raise NotImplementedError(
        "Irreversible: the legacy permission tables were consolidated into "
        "resource_grants. Restore from a backup if needed."
    )
