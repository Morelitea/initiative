"""Grant app_admin privileges on queue tables and set default privileges.

The baseline migration granted app_admin ALL PRIVILEGES on existing tables
but only set ALTER DEFAULT PRIVILEGES for app_user. Tables created by
post-baseline migrations (like the queue tables) were missing app_admin
grants. This migration fixes the immediate issue and adds default
privileges so future migrations inherit app_admin grants automatically.

Revision ID: 20260228_0064
Revises: 20260227_0063
Create Date: 2026-02-28
"""

from alembic import op
from sqlalchemy import text

revision = "20260228_0064"
down_revision = "20260227_0063"
branch_labels = None
depends_on = None

QUEUE_TABLES = [
    "queues",
    "queue_items",
    "queue_permissions",
    "queue_role_permissions",
    "queue_item_tags",
    "queue_item_documents",
    "queue_item_tasks",
]


def upgrade() -> None:
    conn = op.get_bind()

    # Grant app_admin on all queue tables
    for table in QUEUE_TABLES:
        conn.execute(text(f"GRANT ALL PRIVILEGES ON TABLE {table} TO app_admin"))

    # Grant app_admin on queue sequences (queues_id_seq, queue_items_id_seq)
    conn.execute(text(
        "GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO app_admin"
    ))

    # Set default privileges so future tables/sequences created by the
    # migration role (initiative) automatically grant app_admin access.
    conn.execute(text(
        "ALTER DEFAULT PRIVILEGES FOR ROLE initiative IN SCHEMA public "
        "GRANT ALL PRIVILEGES ON TABLES TO app_admin"
    ))
    conn.execute(text(
        "ALTER DEFAULT PRIVILEGES FOR ROLE initiative IN SCHEMA public "
        "GRANT ALL PRIVILEGES ON SEQUENCES TO app_admin"
    ))


def downgrade() -> None:
    conn = op.get_bind()

    # Remove default privileges for app_admin
    conn.execute(text(
        "ALTER DEFAULT PRIVILEGES FOR ROLE initiative IN SCHEMA public "
        "REVOKE ALL PRIVILEGES ON TABLES FROM app_admin"
    ))
    conn.execute(text(
        "ALTER DEFAULT PRIVILEGES FOR ROLE initiative IN SCHEMA public "
        "REVOKE ALL PRIVILEGES ON SEQUENCES FROM app_admin"
    ))

    # Revoke app_admin from queue tables
    for table in QUEUE_TABLES:
        conn.execute(text(f"REVOKE ALL PRIVILEGES ON TABLE {table} FROM app_admin"))
