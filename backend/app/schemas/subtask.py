from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SubtaskBase(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    is_completed: bool = False


class SubtaskCreate(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class SubtaskUpdate(BaseModel):
    content: Optional[str] = Field(default=None, min_length=1, max_length=2000)
    is_completed: Optional[bool] = None


class SubtaskBatchCreate(BaseModel):
    """Create multiple subtasks at once."""
    contents: list[str] = Field(min_length=1, max_length=50)


class SubtaskReorderItem(BaseModel):
    id: int
    position: int


class SubtaskReorderRequest(BaseModel):
    items: list[SubtaskReorderItem]


class SubtaskRead(SubtaskBase):
    id: int
    task_id: int
    position: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TaskSubtaskProgress(BaseModel):
    completed: int = 0
    total: int = 0
