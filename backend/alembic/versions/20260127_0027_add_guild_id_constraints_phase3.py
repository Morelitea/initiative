"""Add NOT NULL constraints, foreign keys, indexes, and triggers (Phase 3 of RLS)

Revision ID: 20260127_0027
Revises: 20260127_0026
Create Date: 2026-01-27

This migration:
1. Makes guild_id columns NOT NULL (data was backfilled in Phase 2)
2. Adds foreign key constraints to guilds.id
3. Adds indexes for efficient RLS policy evaluation
4. Creates triggers to auto-populate guild_id on INSERT/UPDATE
"""

from alembic import op
import sqlalchemy as sa


revision = "20260127_0027"
down_revision = "20260127_0026"
branch_labels = None
depends_on = None


# Tables and their parent relationships for trigger creation
# Format: (table_name, parent_table, parent_fk_column, guild_id_source)
TIER2_TABLES = [
    ("projects", "initiatives", "initiative_id", "guild_id"),
    ("documents", "initiatives", "initiative_id", "guild_id"),
    ("initiative_members", "initiatives", "initiative_id", "guild_id"),
]

TIER3_TABLES = [
    ("tasks", "projects", "project_id", "guild_id"),
    ("task_statuses", "projects", "project_id", "guild_id"),
    ("subtasks", "tasks", "task_id", "guild_id"),
    ("task_assignees", "tasks", "task_id", "guild_id"),
    ("project_permissions", "projects", "project_id", "guild_id"),
    ("project_favorites", "projects", "project_id", "guild_id"),
    ("recent_project_views", "projects", "project_id", "guild_id"),
    ("project_orders", "projects", "project_id", "guild_id"),
    ("project_documents", "projects", "project_id", "guild_id"),
    ("document_permissions", "documents", "document_id", "guild_id"),
]

ALL_TABLES = TIER2_TABLES + TIER3_TABLES


def upgrade() -> None:
    # Step 1: Make guild_id NOT NULL on all tables
    for table_name, _, _, _ in ALL_TABLES:
        op.alter_column(
            table_name,
            "guild_id",
            existing_type=sa.Integer(),
            nullable=False,
        )

    # Step 2: Add foreign key constraints
    for table_name, _, _, _ in ALL_TABLES:
        op.create_foreign_key(
            f"fk_{table_name}_guild_id",
            table_name,
            "guilds",
            ["guild_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # Step 3: Add indexes for RLS policy evaluation
    for table_name, _, _, _ in ALL_TABLES:
        op.create_index(
            f"ix_{table_name}_guild_id",
            table_name,
            ["guild_id"],
        )

    # Step 4: Create triggers to auto-populate guild_id
    # Comments are special - they can be on tasks OR documents
    _create_comment_trigger()

    # Standard triggers for all other tables
    for table_name, parent_table, parent_fk_column, _ in ALL_TABLES:
        if table_name == "comments":
            continue  # Handled separately
        _create_guild_id_trigger(table_name, parent_table, parent_fk_column)


def downgrade() -> None:
    # Drop triggers first
    for table_name, _, _, _ in ALL_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS tr_{table_name}_set_guild_id ON {table_name}")
        op.execute(f"DROP FUNCTION IF EXISTS fn_{table_name}_set_guild_id()")

    # Drop indexes
    for table_name, _, _, _ in ALL_TABLES:
        op.drop_index(f"ix_{table_name}_guild_id", table_name=table_name)

    # Drop foreign key constraints
    for table_name, _, _, _ in ALL_TABLES:
        op.drop_constraint(f"fk_{table_name}_guild_id", table_name, type_="foreignkey")

    # Make guild_id nullable again
    for table_name, _, _, _ in ALL_TABLES:
        op.alter_column(
            table_name,
            "guild_id",
            existing_type=sa.Integer(),
            nullable=True,
        )


def _create_guild_id_trigger(table_name: str, parent_table: str, parent_fk_column: str) -> None:
    """Create a trigger to auto-populate guild_id from parent table."""
    function_sql = f"""
        CREATE OR REPLACE FUNCTION fn_{table_name}_set_guild_id()
        RETURNS TRIGGER AS $$
        BEGIN
            -- Only set if guild_id is NULL or if the parent FK changed
            IF NEW.guild_id IS NULL OR (TG_OP = 'UPDATE' AND OLD.{parent_fk_column} IS DISTINCT FROM NEW.{parent_fk_column}) THEN
                SELECT guild_id INTO NEW.guild_id
                FROM {parent_table}
                WHERE id = NEW.{parent_fk_column};
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """
    trigger_sql = f"""
        CREATE TRIGGER tr_{table_name}_set_guild_id
        BEFORE INSERT OR UPDATE OF {parent_fk_column} ON {table_name}
        FOR EACH ROW
        EXECUTE FUNCTION fn_{table_name}_set_guild_id();
    """
    op.execute(function_sql)
    op.execute(trigger_sql)


def _create_comment_trigger() -> None:
    """Create a special trigger for comments that handles both task and document parents."""
    function_sql = """
        CREATE OR REPLACE FUNCTION fn_comments_set_guild_id()
        RETURNS TRIGGER AS $$
        BEGIN
            -- Only set if guild_id is NULL or if the parent FK changed
            IF NEW.guild_id IS NULL OR
               (TG_OP = 'UPDATE' AND (OLD.task_id IS DISTINCT FROM NEW.task_id OR OLD.document_id IS DISTINCT FROM NEW.document_id)) THEN
                IF NEW.task_id IS NOT NULL THEN
                    SELECT guild_id INTO NEW.guild_id
                    FROM tasks
                    WHERE id = NEW.task_id;
                ELSIF NEW.document_id IS NOT NULL THEN
                    SELECT guild_id INTO NEW.guild_id
                    FROM documents
                    WHERE id = NEW.document_id;
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """
    trigger_sql = """
        CREATE TRIGGER tr_comments_set_guild_id
        BEFORE INSERT OR UPDATE OF task_id, document_id ON comments
        FOR EACH ROW
        EXECUTE FUNCTION fn_comments_set_guild_id();
    """
    op.execute(function_sql)
    op.execute(trigger_sql)
