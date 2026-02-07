"""Enable RLS on tables created after Phase 5

Revision ID: 20260207_0041
Revises: 20260207_0040
Create Date: 2026-02-07

Enables RLS and creates isolation policies for tables that were added
after the original Phase 5 migration: tags, document_links, task_tags,
project_tags, document_tags.

- tags: direct guild_id column
- document_links: nullable guild_id (links may be guild-scoped or global)
- task_tags, project_tags, document_tags: junction tables linked via tag_id
  subquery to tags.guild_id
"""

from alembic import op


revision = "20260207_0041"
down_revision = "20260207_0040"
branch_labels = None
depends_on = None

CURRENT_GUILD_ID = "current_setting('app.current_guild_id', true)::int"


def upgrade() -> None:
    # --- tags: direct guild_id ---
    op.execute("ALTER TABLE tags ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tags FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY guild_isolation ON tags
        FOR ALL
        USING (guild_id = {CURRENT_GUILD_ID})
        WITH CHECK (guild_id = {CURRENT_GUILD_ID})
    """)

    # --- document_links: nullable guild_id ---
    op.execute("ALTER TABLE document_links ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE document_links FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY guild_isolation ON document_links
        FOR ALL
        USING (guild_id IS NULL OR guild_id = {CURRENT_GUILD_ID})
        WITH CHECK (guild_id IS NULL OR guild_id = {CURRENT_GUILD_ID})
    """)

    # --- Junction tables: subquery through tags.guild_id ---
    for table in ("task_tags", "project_tags", "document_tags"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY guild_isolation ON {table}
            FOR ALL
            USING (
                EXISTS (
                    SELECT 1 FROM tags
                    WHERE tags.id = {table}.tag_id
                    AND tags.guild_id = {CURRENT_GUILD_ID}
                )
            )
            WITH CHECK (
                EXISTS (
                    SELECT 1 FROM tags
                    WHERE tags.id = {table}.tag_id
                    AND tags.guild_id = {CURRENT_GUILD_ID}
                )
            )
        """)


def downgrade() -> None:
    for table in ("tags", "document_links", "task_tags", "project_tags", "document_tags"):
        op.execute(f"DROP POLICY IF EXISTS guild_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
