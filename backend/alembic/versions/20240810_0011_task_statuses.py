"""Introduce task_statuses table and migrate tasks.

Revision ID: 20240810_0011
Revises: 20240809_0010
Create Date: 2024-08-10 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20240810_0011"
down_revision: Union[str, None] = "20240809_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TASK_STATUS_CATEGORIES: tuple[str, ...] = ("backlog", "todo", "in_progress", "done")
DEFAULT_STATUS_ROWS: tuple[dict, ...] = (
    {
        "name": "Backlog",
        "category": "backlog",
        "position": 0,
        "is_default": True,
    },
    {
        "name": "In Progress",
        "category": "in_progress",
        "position": 1,
        "is_default": False,
    },
    {
        "name": "Blocked",
        "category": "todo",
        "position": 2,
        "is_default": False,
    },
    {
        "name": "Done",
        "category": "done",
        "position": 3,
        "is_default": False,
    },
)
LEGACY_STATUS_TO_CATEGORY: dict[str, str] = {
    "backlog": "backlog",
    "in_progress": "in_progress",
    "blocked": "todo",
    "done": "done",
}
CATEGORY_TO_LEGACY_STATUS: dict[str, str] = {
    "backlog": "backlog",
    "in_progress": "in_progress",
    "todo": "blocked",
    "done": "done",
}


def upgrade() -> None:
    bind = op.get_bind()

    enum_values = ", ".join(f"''{value}''" for value in TASK_STATUS_CATEGORIES)
    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_type WHERE typname = 'task_status_category'
                ) THEN
                    EXECUTE 'CREATE TYPE task_status_category AS ENUM ({enum_values})';
                END IF;
            END;
            $$
            """
        )
    )
    enum_column = postgresql.ENUM(
        *TASK_STATUS_CATEGORIES,
        name="task_status_category",
        create_type=False,
    )

    op.create_table(
        "task_statuses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("category", enum_column, nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index(
        "ix_task_statuses_project_position",
        "task_statuses",
        ["project_id", "position"],
    )

    op.add_column("tasks", sa.Column("task_status_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_tasks_task_status_id",
        "tasks",
        "task_statuses",
        ["task_status_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    _migrate_existing_data(bind)

    op.alter_column("tasks", "task_status_id", existing_type=sa.Integer(), nullable=False)
    op.drop_column("tasks", "status")
    op.execute("DROP TYPE IF EXISTS task_status")


def downgrade() -> None:
    bind = op.get_bind()

    legacy_status_enum = sa.Enum("backlog", "in_progress", "blocked", "done", name="task_status")
    legacy_status_enum.create(bind, checkfirst=True)

    op.add_column(
        "tasks",
        sa.Column(
            "status",
            legacy_status_enum,
            nullable=True,
            server_default=sa.text("'backlog'"),
        ),
    )

    _restore_legacy_statuses(bind)

    op.alter_column("tasks", "status", existing_type=legacy_status_enum, nullable=False)

    op.drop_constraint("fk_tasks_task_status_id", "tasks", type_="foreignkey")
    op.drop_column("tasks", "task_status_id")

    op.drop_index("ix_task_statuses_project_position", table_name="task_statuses")
    op.drop_table("task_statuses")

    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM pg_type WHERE typname = 'task_status_category'
                ) THEN
                    EXECUTE 'DROP TYPE task_status_category';
                END IF;
            END;
            $$
            """
        )
    )


def _migrate_existing_data(bind) -> None:
    project_rows = bind.execute(sa.text("SELECT id FROM projects")).fetchall()
    insert_stmt = sa.text(
        """
        INSERT INTO task_statuses (project_id, name, position, category, is_default)
        VALUES (:project_id, :name, :position, :category, :is_default)
        RETURNING id
        """
    )
    update_stmt = sa.text(
        "UPDATE tasks SET task_status_id = :status_id WHERE id = :task_id"
    )

    for (project_id,) in project_rows:
        status_ids: dict[str, int] = {}
        for payload in DEFAULT_STATUS_ROWS:
            result = bind.execute(
                insert_stmt,
                {
                    "project_id": project_id,
                    "name": payload["name"],
                    "position": payload["position"],
                    "category": payload["category"],
                    "is_default": payload["is_default"],
                },
            )
            status_id = result.scalar_one()
            status_ids[payload["category"]] = status_id

        task_rows = bind.execute(
            sa.text(
                "SELECT id, status FROM tasks WHERE project_id = :project_id"
            ),
            {"project_id": project_id},
        ).fetchall()
        for task_id, legacy_status in task_rows:
            if legacy_status is None:
                continue
            category = LEGACY_STATUS_TO_CATEGORY.get(legacy_status)
            status_id = status_ids.get(category)
            if status_id is None:
                continue
            bind.execute(update_stmt, {"status_id": status_id, "task_id": task_id})

    # ensure every task has a status
    missing_rows = bind.execute(
        sa.text("SELECT id, project_id FROM tasks WHERE task_status_id IS NULL")
    ).fetchall()
    for task_id, project_id in missing_rows:
        fallback = bind.execute(
            sa.text(
                "SELECT id FROM task_statuses WHERE project_id = :project_id ORDER BY position, id LIMIT 1"
            ),
            {"project_id": project_id},
        ).scalar_one_or_none()
        if fallback is not None:
            bind.execute(update_stmt, {"status_id": fallback, "task_id": task_id})


def _restore_legacy_statuses(bind) -> None:
    status_rows = bind.execute(
        sa.text("SELECT id, category FROM task_statuses")
    ).fetchall()
    status_category: dict[int, str] = {row[0]: row[1] for row in status_rows}

    update_stmt = sa.text("UPDATE tasks SET status = :status WHERE id = :task_id")

    task_rows = bind.execute(
        sa.text("SELECT id, task_status_id FROM tasks")
    ).fetchall()
    for task_id, status_id in task_rows:
        category = status_category.get(status_id)
        legacy_status = CATEGORY_TO_LEGACY_STATUS.get(category, "backlog")
        bind.execute(update_stmt, {"status": legacy_status, "task_id": task_id})
