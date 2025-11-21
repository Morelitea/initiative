from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import Column, DateTime, Float
from sqlmodel import Enum as SQLEnum, Field, Relationship, SQLModel

if TYPE_CHECKING:  # pragma: no cover
    from app.models.project import Project
    from app.models.user import User


class TaskStatus(str, Enum):
    backlog = "backlog"
    in_progress = "in_progress"
    blocked = "blocked"
    done = "done"


class TaskPriority(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    urgent = "urgent"


class TaskAssignee(SQLModel, table=True):
    __tablename__ = "task_assignees"

    task_id: int = Field(foreign_key="tasks.id", primary_key=True)
    user_id: int = Field(foreign_key="users.id", primary_key=True)


class Task(SQLModel, table=True):
    __tablename__ = "tasks"

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="projects.id", nullable=False)
    title: str = Field(nullable=False)
    description: Optional[str] = Field(default=None)
    status: TaskStatus = Field(
        default=TaskStatus.backlog,
        sa_column=Column(SQLEnum(TaskStatus, name="task_status"), nullable=False),
    )
    priority: TaskPriority = Field(
        default=TaskPriority.medium,
        sa_column=Column(SQLEnum(TaskPriority, name="task_priority"), nullable=False),
    )
    due_date: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    sort_order: float = Field(
        default=0,
        sa_column=Column(Float, nullable=False, server_default="0"),
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
    assignees: List["User"] = Relationship(back_populates="tasks_assigned", link_model=TaskAssignee)
