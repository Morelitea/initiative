from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, JSON, String, Text
from sqlmodel import Enum as SQLEnum, Field, Relationship, SQLModel

if TYPE_CHECKING:  # pragma: no cover
    from app.models.project import Project
    from app.models.user import User


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


class TaskStatus(SQLModel, table=True):
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
        sa_column=Column(SQLEnum(TaskStatusCategory, name="task_status_category"), nullable=False),
    )
    is_default: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )

    project: Optional["Project"] = Relationship(back_populates="task_statuses")
    tasks: List["Task"] = Relationship(back_populates="task_status")


class TaskAssignee(SQLModel, table=True):
    __tablename__ = "task_assignees"

    task_id: int = Field(foreign_key="tasks.id", primary_key=True)
    user_id: int = Field(foreign_key="users.id", primary_key=True)


class Subtask(SQLModel, table=True):
    __tablename__ = "subtasks"

    id: Optional[int] = Field(default=None, primary_key=True)
    task_id: int = Field(foreign_key="tasks.id", nullable=False)
    content: str = Field(sa_column=Column(Text, nullable=False))
    is_completed: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    position: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default="0"),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    task: Optional["Task"] = Relationship(back_populates="subtasks")


class Task(SQLModel, table=True):
    __tablename__ = "tasks"

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="projects.id", nullable=False)
    task_status_id: int = Field(foreign_key="task_statuses.id", nullable=False)
    title: str = Field(nullable=False)
    description: Optional[str] = Field(default=None)
    priority: TaskPriority = Field(
        default=TaskPriority.medium,
        sa_column=Column(SQLEnum(TaskPriority, name="task_priority"), nullable=False),
    )
    start_date: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    due_date: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    recurrence: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    recurrence_strategy: str = Field(
        default="fixed",
        sa_column=Column(String(length=20), nullable=False, server_default="fixed"),
    )
    recurrence_occurrence_count: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default="0"),
    )
    sort_order: float = Field(
        default=0,
        sa_column=Column(Float, nullable=False, server_default="0"),
    )
    is_archived: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false", index=True),
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
    assignees: List["User"] = Relationship(back_populates="tasks_assigned", link_model=TaskAssignee)
    subtasks: List["Subtask"] = Relationship(
        back_populates="task",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
