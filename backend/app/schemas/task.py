from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.user import UserRead
from app.schemas.task_status import TaskStatusRead
from app.schemas.guild import GuildSummary

from app.models.task import TaskPriority, TaskStatusCategory


WeekdayLiteral = Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MonthlyModeLiteral = Literal["day_of_month", "weekday"]
WeekPositionLiteral = Literal["first", "second", "third", "fourth", "last"]
RecurrenceEndsLiteral = Literal["never", "on_date", "after_occurrences"]


class TaskRecurrence(BaseModel):
    frequency: Literal["daily", "weekly", "monthly", "yearly"]
    interval: int = Field(default=1, ge=1, le=365)
    weekdays: List[WeekdayLiteral] = Field(default_factory=list)
    monthly_mode: MonthlyModeLiteral = "day_of_month"
    day_of_month: Optional[int] = Field(default=None, ge=1, le=31)
    weekday_position: Optional[WeekPositionLiteral] = None
    weekday: Optional[WeekdayLiteral] = None
    month: Optional[int] = Field(default=None, ge=1, le=12)
    ends: RecurrenceEndsLiteral = "never"
    end_after_occurrences: Optional[int] = Field(default=None, ge=1, le=1000)
    end_date: Optional[datetime] = None

    @field_validator("weekdays")
    def ensure_unique_weekdays(cls, value: List[WeekdayLiteral]) -> List[WeekdayLiteral]:
        seen: list[WeekdayLiteral] = []
        for item in value:
            if item not in seen:
                seen.append(item)
        return seen

    @model_validator(mode="after")
    def validate_combinations(self) -> "TaskRecurrence":
        if self.frequency == "weekly":
            if not self.weekdays:
                raise ValueError("Weekly recurrence requires at least one weekday.")
        else:
            # Clear weekdays for non-weekly recurrences to keep payload compact/safe.
            self.weekdays = []

        if self.frequency in {"monthly", "yearly"}:
            if self.frequency == "yearly" and self.month is None:
                raise ValueError("Yearly recurrence requires a month.")
            if self.monthly_mode == "day_of_month":
                if self.day_of_month is None:
                    raise ValueError("Recurring schedule needs a day of month.")
                if not 1 <= self.day_of_month <= 31:
                    raise ValueError("Day of month must be between 1 and 31.")
                self.weekday_position = None
                self.weekday = None
            else:
                if self.weekday_position is None or self.weekday is None:
                    raise ValueError("Weekday recurrence requires position and weekday.")
                self.day_of_month = None
            if self.frequency == "monthly":
                self.month = None
        else:
            # Strip fields unrelated to the selected cadence.
            self.monthly_mode = "day_of_month"
            self.day_of_month = None
            self.weekday_position = None
            self.weekday = None
            self.month = None

        if self.ends == "on_date":
            if self.end_date is None:
                raise ValueError("End date required when ends='on_date'.")
            self.end_after_occurrences = None
        elif self.ends == "after_occurrences":
            if self.end_after_occurrences is None:
                raise ValueError("Occurrences required when ends='after_occurrences'.")
            self.end_date = None
        else:
            self.end_date = None
            self.end_after_occurrences = None

        return self


class TaskBase(BaseModel):
    title: str
    description: Optional[str] = None
    priority: TaskPriority = TaskPriority.medium
    start_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    recurrence: Optional[TaskRecurrence] = None
    recurrence_strategy: Literal["fixed", "rolling"] = "fixed"


class TaskCreate(TaskBase):
    project_id: int
    assignee_ids: List[int] = Field(default_factory=list)
    task_status_id: Optional[int] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    task_status_id: Optional[int] = None
    priority: Optional[TaskPriority] = None
    assignee_ids: Optional[List[int]] = None
    start_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    recurrence: Optional[TaskRecurrence | None] = None
    recurrence_strategy: Optional[Literal["fixed", "rolling"]] = None


class TaskMoveRequest(BaseModel):
    target_project_id: int = Field(gt=0)


class TaskProjectInitiativeSummary(BaseModel):
    id: int
    name: str
    color: Optional[str] = None

    class Config:
        from_attributes = True


class TaskProjectSummary(BaseModel):
    id: int
    name: str
    icon: Optional[str] = None
    initiative_id: Optional[int] = None
    initiative: Optional[TaskProjectInitiativeSummary] = None
    is_archived: Optional[bool] = None
    is_template: Optional[bool] = None

    class Config:
        from_attributes = True


class TaskRead(TaskBase):
    id: int
    project_id: int
    task_status_id: int
    task_status: TaskStatusRead
    created_at: datetime
    updated_at: datetime
    sort_order: float
    assignees: List[UserRead] = []
    recurrence_occurrence_count: int = 0
    comment_count: int = 0
    guild: Optional[GuildSummary] = None
    project: Optional[TaskProjectSummary] = None

    class Config:
        from_attributes = True


class TaskReorderItem(BaseModel):
    id: int
    task_status_id: int
    sort_order: float


class TaskReorderRequest(BaseModel):
    project_id: int
    items: list[TaskReorderItem]
