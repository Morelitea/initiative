from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel

from app.schemas.user import UserRead

from app.models.task import TaskPriority, TaskStatus


class TaskBase(BaseModel):
    title: str
    description: Optional[str] = None
    status: TaskStatus = TaskStatus.backlog
    priority: TaskPriority = TaskPriority.medium
    due_date: Optional[datetime] = None


class TaskCreate(TaskBase):
    project_id: int
    assignee_ids: List[int] = []


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[TaskStatus] = None
    priority: Optional[TaskPriority] = None
    assignee_ids: Optional[List[int]] = None
    due_date: Optional[datetime] = None


class TaskRead(TaskBase):
    id: int
    project_id: int
    created_at: datetime
    updated_at: datetime
    sort_order: float
    assignees: List[UserRead] = []

    class Config:
        from_attributes = True


class TaskReorderItem(BaseModel):
    id: int
    status: TaskStatus
    sort_order: float


class TaskReorderRequest(BaseModel):
    project_id: int
    items: list[TaskReorderItem]
