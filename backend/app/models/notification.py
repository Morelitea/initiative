from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from sqlalchemy import Column, DateTime, JSON, String
from sqlmodel import Field, SQLModel


class NotificationType(str, Enum):
    task_assignment = "task_assignment"
    initiative_added = "initiative_added"
    project_added = "project_added"
    user_pending_approval = "user_pending_approval"


class Notification(SQLModel, table=True):
    __tablename__ = "notifications"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", nullable=False, index=True)
    type: NotificationType = Field(
        sa_column=Column(String(64), nullable=False),
        default=NotificationType.task_assignment,
    )
    data: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, server_default="{}"),
    )
    read_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
