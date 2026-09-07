"""cascade task_assignees when a task is deleted

Every other child of ``tasks`` is taken with it — comments, subtasks, tags,
property values, assignment digest items all carry ``ON DELETE CASCADE``, and
queue links are cleared by the ORM relationship. ``task_assignees`` had
neither: ``Task.assignees`` is a read-only relationship, so nothing removed
those rows, and the foreign key had no cascade to remove them either.

Hard-deleting a task that anyone was assigned to therefore failed on
``task_assignees_task_id_fkey`` — purging one from the trash by hand, and the
hourly retention worker every time it reached one.

Revision ID: 20260907_0235
Revises: 20260907_0234
Create Date: 2026-09-07
"""

from alembic import op

from app.db.guild_migrations import apply_to_all_guild_schemas

revision = "20260907_0235"
down_revision = "20260907_0234"
branch_labels = None
depends_on = None

_CONSTRAINT = "task_assignees_task_id_fkey"


def _replace(rule: str) -> tuple[str, ...]:
    return (
        f"ALTER TABLE task_assignees DROP CONSTRAINT IF EXISTS {_CONSTRAINT}",
        f"ALTER TABLE task_assignees ADD CONSTRAINT {_CONSTRAINT} "
        f"FOREIGN KEY (task_id) REFERENCES tasks(id){rule}",
    )


def upgrade() -> None:
    apply_to_all_guild_schemas(op.get_bind(), *_replace(" ON DELETE CASCADE"))


def downgrade() -> None:
    apply_to_all_guild_schemas(op.get_bind(), *_replace(""))
