from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    event,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Enum as SQLEnum, Field, Relationship, SQLModel

from app.core import recurrence
from app.models.tenant._mixins import ArchiveMixin, CreatedByMixin, SoftDeleteMixin

if TYPE_CHECKING:  # pragma: no cover
    from app.models.tenant.project import Project
    from app.models.platform.user_profile_view import MemberProfile


class TaskStatusCategory(str, Enum):
    backlog = "backlog"
    todo = "todo"
    in_progress = "in_progress"
    done = "done"


class TaskPriority(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    urgent = "urgent"


class TaskStatus(CreatedByMixin, table=True):
    __tablename__ = "task_statuses"

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="projects.id", nullable=False)
    name: str = Field(
        sa_column=Column(String(length=100), nullable=False),
    )
    position: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default="0"),
    )
    category: TaskStatusCategory = Field(
        sa_column=Column(
            SQLEnum(TaskStatusCategory, name="task_status_category"), nullable=False
        ),
    )
    is_default: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    color: str = Field(
        default="#94A3B8",
        sa_column=Column(String(length=9), nullable=False, server_default="#94A3B8"),
    )
    icon: str = Field(
        default="circle-dashed",
        sa_column=Column(
            String(length=64), nullable=False, server_default="circle-dashed"
        ),
    )

    project: Optional["Project"] = Relationship(back_populates="task_statuses")
    tasks: List["Task"] = Relationship(back_populates="task_status")


class TaskAssignee(SQLModel, table=True):
    __tablename__ = "task_assignees"

    # ``Task.assignees`` is a read-only view over this table, so nothing in the
    # ORM clears these rows when a task is hard-deleted. The database does.
    task_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("tasks.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        )
    )
    user_id: int = Field(foreign_key="users.id", primary_key=True, index=True)


class Task(CreatedByMixin, ArchiveMixin, SoftDeleteMixin, table=True):
    __tablename__ = "tasks"
    _display_field = "title"

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="projects.id", nullable=False)
    task_status_id: int = Field(foreign_key="task_statuses.id", nullable=False)
    title: str = Field(nullable=False)
    # TEXT in DDL (unbounded); sa_column keeps autogen quiet vs AutoString
    description: Optional[str] = Field(default=None, sa_column=Column(Text))
    # Ordered ``{"id", "text", "done"}`` objects — the task's checklist. JSONB
    # so one item can be addressed by id and rewritten in place; see
    # ``app.services.tenant.task_checklist``.
    checklist: List[dict] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default="[]"),
    )
    priority: TaskPriority = Field(
        default=TaskPriority.medium,
        sa_column=Column(SQLEnum(TaskPriority, name="task_priority"), nullable=False),
    )
    start_date: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    due_date: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    # RFC 5545 recurrence lines as picked (``app.core.recurrence``).
    recurrence: Optional[str] = Field(default=None, sa_column=Column(Text))
    # Minutes from the start's UTC time to where the repeat was picked: whole
    # days for a rule of days, the offset for a rule of hours.
    recurrence_shift: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )
    # No occurrence of the series starts after this; null when it never ends.
    # Written from ``recurrence`` on every save (see the listener below).
    recurrence_until: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    recurrence_strategy: str = Field(
        default="fixed",
        sa_column=Column(String(length=20), nullable=False, server_default="fixed"),
    )
    recurrence_occurrence_count: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default="0"),
    )
    # The first task of the repeating series this task is in, set when the
    # series first moves on. A name for the series rather than a key: the
    # series goes on when its first task is purged.
    series_id: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True, index=True)
    )
    # What an edit of just this task changed from, by field; the next task in
    # the series is made with these (``app.services.tenant.task_series``).
    recurrence_carry: Optional[dict] = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )
    position: float = Field(
        default=0,
        sa_column=Column(
            Numeric(20, 10, asdecimal=False), nullable=False, server_default="0"
        ),
    )
    # When the task entered a ``done``-category status, cleared when it leaves
    # one. Kept in step with ``task_status.category`` by
    # ``app.services.tenant.task_completion`` — never set directly.
    completed_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    project: Optional["Project"] = Relationship(back_populates="tasks")
    task_status: Optional[TaskStatus] = Relationship(back_populates="tasks")
    assignees: List["MemberProfile"] = Relationship(
        sa_relationship_kwargs={
            "secondary": "task_assignees",
            "primaryjoin": "Task.id == foreign(TaskAssignee.task_id)",
            "secondaryjoin": "foreign(TaskAssignee.user_id) == MemberProfile.id",
            "viewonly": True,
        }
    )
    # Read-only link to the author (``created_by``) so reads can expose a
    # ``creator`` summary without a separate roster fetch. The join is spelled
    # out because the target is a view, which carries no foreign key.
    creator: Optional["MemberProfile"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": "foreign(Task.created_by) == MemberProfile.id",
            "viewonly": True,
        }
    )


@event.listens_for(Task, "before_insert")
@event.listens_for(Task, "before_update")
def _write_recurrence_until(_mapper, _connection, task: Task) -> None:
    # A task series starts at its due date, or its start date without one.
    start = task.due_date or task.start_date
    task.recurrence_until = (
        recurrence.last_start(
            task.recurrence,
            start,
            task.recurrence_shift,
            done=task.recurrence_occurrence_count,
        )
        if task.recurrence and start
        else None
    )
