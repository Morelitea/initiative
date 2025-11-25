from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime, String, Integer, ForeignKey
from sqlmodel import Field, SQLModel


class TaskAssignmentDigestItem(SQLModel, table=True):
    __tablename__ = "task_assignment_digest_items"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", nullable=False, index=True)
    task_id: int = Field(foreign_key="tasks.id", nullable=False)
    project_id: int = Field(foreign_key="projects.id", nullable=False)
    task_title: str = Field(sa_column=Column(String(255), nullable=False))
    project_name: str = Field(sa_column=Column(String(255), nullable=False))
    assigned_by_name: str = Field(sa_column=Column(String(255), nullable=False))
    assigned_by_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    processed_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
