"""Add queue tables for turn/priority tracking.

Creates queues, queue_items, queue_permissions, queue_role_permissions,
queue_item_tags, queue_item_documents, queue_item_tasks tables with
guild isolation and initiative-scoped RESTRICTIVE RLS policies.
Also backfills initiative role permissions for queues_enabled and create_queues.

Revision ID: 20260226_0062
Revises: 20260226_0061
Create Date: 2026-02-26
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "20260226_0062"
down_revision = "20260226_0061"
branch_labels = None
depends_on = None

# ---------------------------------------------------------------------------
# RLS session-variable helpers
# ---------------------------------------------------------------------------
GUILD_ID = "current_setting('app.current_guild_id'::text, true)::int"
USER_ID = "NULLIF(current_setting('app.current_user_id'::text, true), ''::text)::integer"
GUILD_ROLE = "current_setting('app.current_guild_role'::text, true)"
IS_SUPER = "current_setting('app.is_superadmin'::text, true) = 'true'::text"
IS_ADMIN = f"{GUILD_ROLE} = 'admin'::text"
BYPASS = f"OR ({IS_ADMIN}) OR ({IS_SUPER})"

# Guild isolation expression
GUILD_CHECK = f"guild_id = {GUILD_ID} OR {IS_SUPER}"

# Tables and their initiative membership check expressions
TABLES_DIRECT_INITIATIVE = ["queues"]  # has initiative_id directly
TABLES_VIA_QUEUE = [  # reach initiative through queue_id -> queues
    "queue_items",
    "queue_permissions",
    "queue_role_permissions",
]
TABLES_VIA_QUEUE_ITEM = [  # reach initiative through queue_item_id -> queue_items -> queues
    "queue_item_tags",
    "queue_item_documents",
    "queue_item_tasks",
]


def _init_member_direct(table: str) -> str:
    """Check initiative membership for tables with initiative_id."""
    return (
        f"EXISTS ("
        f"SELECT 1 FROM initiatives "
        f"WHERE initiatives.id = {table}.initiative_id "
        f"AND is_initiative_member(initiatives.id, ({USER_ID}))"
        f")"
    )


def _init_member_via_queue(table: str) -> str:
    """Check initiative membership through queue_id -> queues."""
    return (
        f"EXISTS ("
        f"SELECT 1 FROM queues "
        f"WHERE queues.id = {table}.queue_id "
        f"AND is_initiative_member(queues.initiative_id, ({USER_ID}))"
        f")"
    )


def _init_member_via_queue_item(table: str) -> str:
    """Check initiative membership through queue_item_id -> queue_items -> queues."""
    return (
        f"EXISTS ("
        f"SELECT 1 FROM queue_items "
        f"JOIN queues ON queues.id = queue_items.queue_id "
        f"WHERE queue_items.id = {table}.queue_item_id "
        f"AND is_initiative_member(queues.initiative_id, ({USER_ID}))"
        f")"
    )


def _add_rls_policies(conn, table: str, membership_expr: str) -> None:
    """Enable RLS and add guild isolation + initiative membership policies."""
    conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
    conn.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))

    # PERMISSIVE guild isolation
    conn.execute(text(
        f"CREATE POLICY guild_isolation ON {table} "
        f"AS PERMISSIVE FOR ALL "
        f"USING ({GUILD_CHECK}) "
        f"WITH CHECK ({GUILD_CHECK})"
    ))

    # RESTRICTIVE initiative membership (per-command)
    bypass_expr = f"({membership_expr} {BYPASS})"
    for cmd, policy_name in [
        ("SELECT", "initiative_member_select"),
        ("INSERT", "initiative_member_insert"),
        ("UPDATE", "initiative_member_update"),
        ("DELETE", "initiative_member_delete"),
    ]:
        if cmd == "SELECT":
            conn.execute(text(
                f"CREATE POLICY {policy_name} ON {table} "
                f"AS RESTRICTIVE FOR SELECT USING ({bypass_expr})"
            ))
        elif cmd == "INSERT":
            conn.execute(text(
                f"CREATE POLICY {policy_name} ON {table} "
                f"AS RESTRICTIVE FOR INSERT WITH CHECK ({bypass_expr})"
            ))
        elif cmd == "UPDATE":
            conn.execute(text(
                f"CREATE POLICY {policy_name} ON {table} "
                f"AS RESTRICTIVE FOR UPDATE USING ({bypass_expr}) WITH CHECK ({bypass_expr})"
            ))
        elif cmd == "DELETE":
            conn.execute(text(
                f"CREATE POLICY {policy_name} ON {table} "
                f"AS RESTRICTIVE FOR DELETE USING ({bypass_expr})"
            ))


def _add_junction_rls_policies(conn, table: str, membership_expr: str) -> None:
    """Enable RLS for junction tables without guild_id (access via parent).

    These use PERMISSIVE policies because there is no guild_id column for a
    separate guild-isolation layer.  The initiative-membership check *is* the
    primary access control — it already verifies guild membership transitively
    through the parent queue's initiative.
    """
    conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
    conn.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))

    bypass_expr = f"({membership_expr} {BYPASS})"
    for cmd, policy_name in [
        ("SELECT", "initiative_member_select"),
        ("INSERT", "initiative_member_insert"),
        ("UPDATE", "initiative_member_update"),
        ("DELETE", "initiative_member_delete"),
    ]:
        if cmd == "SELECT":
            conn.execute(text(
                f"CREATE POLICY {policy_name} ON {table} "
                f"AS PERMISSIVE FOR SELECT USING ({bypass_expr})"
            ))
        elif cmd == "INSERT":
            conn.execute(text(
                f"CREATE POLICY {policy_name} ON {table} "
                f"AS PERMISSIVE FOR INSERT WITH CHECK ({bypass_expr})"
            ))
        elif cmd == "UPDATE":
            conn.execute(text(
                f"CREATE POLICY {policy_name} ON {table} "
                f"AS PERMISSIVE FOR UPDATE USING ({bypass_expr}) WITH CHECK ({bypass_expr})"
            ))
        elif cmd == "DELETE":
            conn.execute(text(
                f"CREATE POLICY {policy_name} ON {table} "
                f"AS PERMISSIVE FOR DELETE USING ({bypass_expr})"
            ))


def _drop_rls(conn, table: str) -> None:
    """Drop all RLS policies and disable RLS for a table."""
    for policy in [
        "guild_isolation",
        "initiative_member_select",
        "initiative_member_insert",
        "initiative_member_update",
        "initiative_member_delete",
    ]:
        conn.execute(text(f"DROP POLICY IF EXISTS {policy} ON {table}"))
    conn.execute(text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))


def upgrade() -> None:
    # -- queues --
    op.create_table(
        "queues",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.Integer(), nullable=False),
        sa.Column("initiative_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column("current_round", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"]),
        sa.ForeignKeyConstraint(["initiative_id"], ["initiatives.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_queues_guild_id", "queues", ["guild_id"])
    op.create_index("ix_queues_initiative_id", "queues", ["initiative_id"])

    # -- queue_items --
    op.create_table(
        "queue_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.Integer(), nullable=False),
        sa.Column("queue_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("color", sa.String(length=32), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_visible", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"]),
        sa.ForeignKeyConstraint(["queue_id"], ["queues.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_queue_items_guild_id", "queue_items", ["guild_id"])
    op.create_index("ix_queue_items_queue_id", "queue_items", ["queue_id"])

    # -- Add deferred FK from queues.current_item_id to queue_items --
    op.add_column(
        "queues",
        sa.Column("current_item_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_queues_current_item_id",
        "queues",
        "queue_items",
        ["current_item_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # -- queue_permissions (creates the queue_permission_level enum type) --
    op.create_table(
        "queue_permissions",
        sa.Column("queue_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.Integer(), nullable=False),
        sa.Column(
            "level",
            sa.Enum("owner", "write", "read", name="queue_permission_level"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["queue_id"], ["queues.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"]),
        sa.PrimaryKeyConstraint("queue_id", "user_id"),
    )
    op.create_index("ix_queue_permissions_user_id", "queue_permissions", ["user_id"])

    # -- queue_role_permissions --
    op.create_table(
        "queue_role_permissions",
        sa.Column("queue_id", sa.Integer(), nullable=False),
        sa.Column("initiative_role_id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.Integer(), nullable=False),
        sa.Column(
            "level",
            sa.Enum("owner", "write", "read", name="queue_permission_level", create_type=False),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["queue_id"], ["queues.id"]),
        sa.ForeignKeyConstraint(["initiative_role_id"], ["initiative_roles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"]),
        sa.PrimaryKeyConstraint("queue_id", "initiative_role_id"),
    )

    # -- queue_item_tags --
    op.create_table(
        "queue_item_tags",
        sa.Column("queue_item_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["queue_item_id"], ["queue_items.id"]),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"]),
        sa.PrimaryKeyConstraint("queue_item_id", "tag_id"),
    )
    op.create_index("ix_queue_item_tags_tag_id", "queue_item_tags", ["tag_id"])

    # -- queue_item_documents --
    op.create_table(
        "queue_item_documents",
        sa.Column("queue_item_id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.Integer(), nullable=False),
        sa.Column("attached_by_id", sa.Integer(), nullable=True),
        sa.Column("attached_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["queue_item_id"], ["queue_items.id"]),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"]),
        sa.ForeignKeyConstraint(["attached_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("queue_item_id", "document_id"),
    )

    # -- queue_item_tasks --
    op.create_table(
        "queue_item_tasks",
        sa.Column("queue_item_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.Integer(), nullable=False),
        sa.Column("attached_by_id", sa.Integer(), nullable=True),
        sa.Column("attached_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["queue_item_id"], ["queue_items.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"]),
        sa.ForeignKeyConstraint(["attached_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("queue_item_id", "task_id"),
    )

    # -- RLS policies --
    conn = op.get_bind()

    # Tables with guild_id + direct or indirect initiative access
    for table in TABLES_DIRECT_INITIATIVE:
        _add_rls_policies(conn, table, _init_member_direct(table))

    for table in TABLES_VIA_QUEUE:
        _add_rls_policies(conn, table, _init_member_via_queue(table))

    # Junction tables without guild_id — need guild check via parent
    for table in TABLES_VIA_QUEUE_ITEM:
        _add_junction_rls_policies(conn, table, _init_member_via_queue_item(table))

    # -- Update the permission_key check constraint to include new keys --
    conn.execute(text(
        "ALTER TABLE initiative_role_permissions "
        "DROP CONSTRAINT IF EXISTS ck_initiative_role_permissions_permission_key"
    ))
    conn.execute(text(
        "ALTER TABLE initiative_role_permissions "
        "ADD CONSTRAINT ck_initiative_role_permissions_permission_key "
        "CHECK (permission_key IN ("
        "'docs_enabled', 'projects_enabled', 'create_docs', 'create_projects', "
        "'queues_enabled', 'create_queues'))"
    ))

    # -- Backfill initiative role permissions for new queue keys --
    # PM/manager roles get both enabled; member roles get both disabled
    conn.execute(text("""
        INSERT INTO initiative_role_permissions (initiative_role_id, permission_key, enabled)
        SELECT ir.id, 'queues_enabled', ir.is_manager
        FROM initiative_roles ir
        WHERE NOT EXISTS (
            SELECT 1 FROM initiative_role_permissions irp
            WHERE irp.initiative_role_id = ir.id AND irp.permission_key = 'queues_enabled'
        )
    """))
    conn.execute(text("""
        INSERT INTO initiative_role_permissions (initiative_role_id, permission_key, enabled)
        SELECT ir.id, 'create_queues', ir.is_manager
        FROM initiative_roles ir
        WHERE NOT EXISTS (
            SELECT 1 FROM initiative_role_permissions irp
            WHERE irp.initiative_role_id = ir.id AND irp.permission_key = 'create_queues'
        )
    """))


def downgrade() -> None:
    conn = op.get_bind()

    # Remove backfilled permissions
    conn.execute(text(
        "DELETE FROM initiative_role_permissions "
        "WHERE permission_key IN ('queues_enabled', 'create_queues')"
    ))

    # Restore original permission_key check constraint (without queue keys)
    conn.execute(text(
        "ALTER TABLE initiative_role_permissions "
        "DROP CONSTRAINT IF EXISTS ck_initiative_role_permissions_permission_key"
    ))
    conn.execute(text(
        "ALTER TABLE initiative_role_permissions "
        "ADD CONSTRAINT ck_initiative_role_permissions_permission_key "
        "CHECK (permission_key IN ("
        "'docs_enabled', 'projects_enabled', 'create_docs', 'create_projects'))"
    ))

    # Drop RLS policies from all queue tables
    all_tables = (
        TABLES_DIRECT_INITIATIVE
        + TABLES_VIA_QUEUE
        + TABLES_VIA_QUEUE_ITEM
    )
    for table in all_tables:
        _drop_rls(conn, table)

    # Drop tables in reverse dependency order
    op.drop_table("queue_item_tasks")
    op.drop_table("queue_item_documents")
    op.drop_table("queue_item_tags")
    op.drop_table("queue_role_permissions")
    op.drop_table("queue_permissions")

    # Drop the deferred FK and column before dropping queue_items
    op.drop_constraint("fk_queues_current_item_id", "queues", type_="foreignkey")
    op.drop_column("queues", "current_item_id")

    op.drop_table("queue_items")
    op.drop_table("queues")

    # Drop the enum type
    conn.execute(text("DROP TYPE IF EXISTS queue_permission_level"))
