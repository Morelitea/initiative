"""Backfill guild_id values from parent tables (Phase 2 of RLS)

Revision ID: 20260127_0026
Revises: 20260127_0025
Create Date: 2026-01-27

This migration backfills guild_id values from parent tables:
- Tier 2 tables get guild_id from their initiative
- Tier 3 tables get guild_id from their project (or document for comments)
"""

from alembic import op


revision = "20260127_0026"
down_revision = "20260127_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Tier 2: Get guild_id from initiative
    # Projects: project.initiative_id -> initiative.guild_id
    op.execute("""
        UPDATE projects p
        SET guild_id = i.guild_id
        FROM initiatives i
        WHERE p.initiative_id = i.id
          AND p.guild_id IS NULL
    """)

    # Documents: document.initiative_id -> initiative.guild_id
    op.execute("""
        UPDATE documents d
        SET guild_id = i.guild_id
        FROM initiatives i
        WHERE d.initiative_id = i.id
          AND d.guild_id IS NULL
    """)

    # InitiativeMembers: initiative_member.initiative_id -> initiative.guild_id
    op.execute("""
        UPDATE initiative_members im
        SET guild_id = i.guild_id
        FROM initiatives i
        WHERE im.initiative_id = i.id
          AND im.guild_id IS NULL
    """)

    # Tier 3: Get guild_id from project
    # Tasks: task.project_id -> project.guild_id
    op.execute("""
        UPDATE tasks t
        SET guild_id = p.guild_id
        FROM projects p
        WHERE t.project_id = p.id
          AND t.guild_id IS NULL
    """)

    # TaskStatuses: task_status.project_id -> project.guild_id
    op.execute("""
        UPDATE task_statuses ts
        SET guild_id = p.guild_id
        FROM projects p
        WHERE ts.project_id = p.id
          AND ts.guild_id IS NULL
    """)

    # Subtasks: subtask.task_id -> task.guild_id (already backfilled from project)
    op.execute("""
        UPDATE subtasks s
        SET guild_id = t.guild_id
        FROM tasks t
        WHERE s.task_id = t.id
          AND s.guild_id IS NULL
    """)

    # TaskAssignees: task_assignee.task_id -> task.guild_id
    op.execute("""
        UPDATE task_assignees ta
        SET guild_id = t.guild_id
        FROM tasks t
        WHERE ta.task_id = t.id
          AND ta.guild_id IS NULL
    """)

    # Comments: polymorphic - get from task or document
    # First, comments on tasks
    op.execute("""
        UPDATE comments c
        SET guild_id = t.guild_id
        FROM tasks t
        WHERE c.task_id = t.id
          AND c.guild_id IS NULL
    """)
    # Then, comments on documents
    op.execute("""
        UPDATE comments c
        SET guild_id = d.guild_id
        FROM documents d
        WHERE c.document_id = d.id
          AND c.guild_id IS NULL
    """)

    # ProjectPermissions: project_permission.project_id -> project.guild_id
    op.execute("""
        UPDATE project_permissions pp
        SET guild_id = p.guild_id
        FROM projects p
        WHERE pp.project_id = p.id
          AND pp.guild_id IS NULL
    """)

    # ProjectFavorites: project_favorite.project_id -> project.guild_id
    op.execute("""
        UPDATE project_favorites pf
        SET guild_id = p.guild_id
        FROM projects p
        WHERE pf.project_id = p.id
          AND pf.guild_id IS NULL
    """)

    # RecentProjectViews: recent_project_view.project_id -> project.guild_id
    op.execute("""
        UPDATE recent_project_views rpv
        SET guild_id = p.guild_id
        FROM projects p
        WHERE rpv.project_id = p.id
          AND rpv.guild_id IS NULL
    """)

    # ProjectOrders: project_order.project_id -> project.guild_id
    op.execute("""
        UPDATE project_orders po
        SET guild_id = p.guild_id
        FROM projects p
        WHERE po.project_id = p.id
          AND po.guild_id IS NULL
    """)

    # ProjectDocuments: can get from either project or document (both should match)
    op.execute("""
        UPDATE project_documents pd
        SET guild_id = p.guild_id
        FROM projects p
        WHERE pd.project_id = p.id
          AND pd.guild_id IS NULL
    """)

    # DocumentPermissions: document_permission.document_id -> document.guild_id
    op.execute("""
        UPDATE document_permissions dp
        SET guild_id = d.guild_id
        FROM documents d
        WHERE dp.document_id = d.id
          AND dp.guild_id IS NULL
    """)


def downgrade() -> None:
    # Set all guild_id columns back to NULL
    # (The columns themselves are removed in the previous migration's downgrade)
    op.execute("UPDATE projects SET guild_id = NULL")
    op.execute("UPDATE documents SET guild_id = NULL")
    op.execute("UPDATE initiative_members SET guild_id = NULL")
    op.execute("UPDATE tasks SET guild_id = NULL")
    op.execute("UPDATE task_statuses SET guild_id = NULL")
    op.execute("UPDATE subtasks SET guild_id = NULL")
    op.execute("UPDATE task_assignees SET guild_id = NULL")
    op.execute("UPDATE comments SET guild_id = NULL")
    op.execute("UPDATE project_permissions SET guild_id = NULL")
    op.execute("UPDATE project_favorites SET guild_id = NULL")
    op.execute("UPDATE recent_project_views SET guild_id = NULL")
    op.execute("UPDATE project_orders SET guild_id = NULL")
    op.execute("UPDATE project_documents SET guild_id = NULL")
    op.execute("UPDATE document_permissions SET guild_id = NULL")
