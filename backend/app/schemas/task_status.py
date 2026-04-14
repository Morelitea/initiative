from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.task import TaskStatusCategory

# Accepts #RGB, #RRGGBB, and #RRGGBBAA — matching the 4/7/9 char lengths the
# model column allows. Keeps arbitrary strings ("red", "notcolor", …) out of
# the database so the swatch renderer never receives garbage.
HEX_COLOR_PATTERN = r"^#([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$"


class TaskStatusBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    category: TaskStatusCategory
    position: int = Field(ge=0)
    is_default: bool = False
    color: str = Field(min_length=4, max_length=9, pattern=HEX_COLOR_PATTERN)
    icon: str = Field(min_length=1, max_length=64)


class TaskStatusCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    category: TaskStatusCategory
    position: Optional[int] = Field(default=None, ge=0)
    is_default: bool = False
    color: Optional[str] = Field(
        default=None, min_length=4, max_length=9, pattern=HEX_COLOR_PATTERN
    )
    icon: Optional[str] = Field(default=None, min_length=1, max_length=64)


class TaskStatusUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    category: Optional[TaskStatusCategory] = None
    position: Optional[int] = Field(default=None, ge=0)
    is_default: Optional[bool] = None
    color: Optional[str] = Field(
        default=None, min_length=4, max_length=9, pattern=HEX_COLOR_PATTERN
    )
    icon: Optional[str] = Field(default=None, min_length=1, max_length=64)


class TaskStatusRead(TaskStatusBase):
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    id: int
    project_id: int


class TaskStatusDeleteRequest(BaseModel):
    fallback_status_id: Optional[int] = None


class TaskStatusReorderItem(BaseModel):
    id: int
    position: int


class TaskStatusReorderRequest(BaseModel):
    items: List[TaskStatusReorderItem]
