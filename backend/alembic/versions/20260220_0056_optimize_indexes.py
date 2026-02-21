"""Drop redundant indexes and add high-priority missing indexes

Drops 9 indexes that are redundant (subsumed by composite PK indexes,
low-cardinality booleans, or duplicates of unique constraint indexes).
Adds 6 high-priority indexes for reverse lookups on composite-PK junction
tables and FK columns on heavily-queried parent tables.

See history/indexing-plan.md for full rationale.

Revision ID: 20260220_0056
Revises: 20260220_0055
Create Date: 2026-02-20
"""

revision = "20260220_0056"
down_revision = "20260220_0055"
branch_labels = None
depends_on = None

from alembic import op


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Drop 9 redundant indexes
    # ------------------------------------------------------------------

    # Subsumed by composite PK (leading-column redundancy)
    op.drop_index("ix_task_tags_task_id", table_name="task_tags")
    op.drop_index("ix_project_tags_project_id", table_name="project_tags")
    op.drop_index("ix_document_tags_document_id", table_name="document_tags")
    op.drop_index("ix_project_favorites_user_id", table_name="project_favorites")
    op.drop_index("ix_recent_project_views_user_id", table_name="recent_project_views")
    op.drop_index("ix_project_documents_project_id", table_name="project_documents")

    # Subsumed by idx_tasks_project_archived(project_id, is_archived)
    op.drop_index("ix_tasks_is_archived", table_name="tasks")

    # Never used — all queries filter by user_id first via PK
    op.drop_index("ix_recent_project_views_last_viewed_at", table_name="recent_project_views")

    # Duplicate of unique constraint index users_email_key
    op.drop_index("ix_users_email", table_name="users")

    # ------------------------------------------------------------------
    # Add 6 high-priority indexes
    # ------------------------------------------------------------------

    # Reverse lookups on composite-PK junction tables.
    # These tables have PK (A, B) but queries frequently filter on B alone.
    op.create_index(
        "ix_task_assignees_user_id",
        "task_assignees",
        ["user_id"],
    )
    op.create_index(
        "ix_initiative_members_user_id",
        "initiative_members",
        ["user_id"],
    )
    op.create_index(
        "ix_project_permissions_user_id",
        "project_permissions",
        ["user_id"],
    )
    op.create_index(
        "ix_document_permissions_user_id",
        "document_permissions",
        ["user_id"],
    )

    # FK columns on heavily-queried parent tables
    op.create_index(
        "ix_initiatives_guild_id",
        "initiatives",
        ["guild_id"],
    )
    op.create_index(
        "ix_projects_initiative_id",
        "projects",
        ["initiative_id"],
    )


def downgrade() -> None:
    # Drop the 6 new indexes
    op.drop_index("ix_projects_initiative_id", table_name="projects")
    op.drop_index("ix_initiatives_guild_id", table_name="initiatives")
    op.drop_index("ix_document_permissions_user_id", table_name="document_permissions")
    op.drop_index("ix_project_permissions_user_id", table_name="project_permissions")
    op.drop_index("ix_initiative_members_user_id", table_name="initiative_members")
    op.drop_index("ix_task_assignees_user_id", table_name="task_assignees")

    # Re-create the 9 dropped indexes
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index(
        "ix_recent_project_views_last_viewed_at",
        "recent_project_views",
        ["last_viewed_at"],
    )
    op.create_index("ix_tasks_is_archived", "tasks", ["is_archived"])
    op.create_index(
        "ix_project_documents_project_id",
        "project_documents",
        ["project_id"],
    )
    op.create_index(
        "ix_recent_project_views_user_id",
        "recent_project_views",
        ["user_id"],
    )
    op.create_index(
        "ix_project_favorites_user_id",
        "project_favorites",
        ["user_id"],
    )
    op.create_index(
        "ix_document_tags_document_id",
        "document_tags",
        ["document_id"],
    )
    op.create_index(
        "ix_project_tags_project_id",
        "project_tags",
        ["project_id"],
    )
    op.create_index("ix_task_tags_task_id", "task_tags", ["task_id"])
