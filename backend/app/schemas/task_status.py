from typing import Optional

from pydantic import BaseModel, Field

from app.models.task import TaskStatusCategory


class TaskStatusBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    category: TaskStatusCategory
    position: int = Field(ge=0)
    is_default: bool = False


class TaskStatusCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    category: TaskStatusCategory
    position: Optional[int] = Field(default=None, ge=0)
    is_default: bool = False


class TaskStatusUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    category: Optional[TaskStatusCategory] = None
    position: Optional[int] = Field(default=None, ge=0)
    is_default: Optional[bool] = None


class TaskStatusRead(TaskStatusBase):
    id: int
    project_id: int

    class Config:
        from_attributes = True


class TaskStatusDeleteRequest(BaseModel):
    fallback_status_id: Optional[int] = None
