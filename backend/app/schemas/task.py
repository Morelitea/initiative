import re
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.user import UserPublic
from app.schemas.task_status import TaskStatusRead
from app.schemas.guild import GuildSummary
from app.schemas.subtask import TaskSubtaskProgress
from app.schemas.tag import TagSummary
from app.schemas.property import PropertySummary

from app.models.task import TaskPriority
from app.models.user import UserStatus


class TaskAssigneeSummary(BaseModel):
    """Minimal assignee data for task lists.

    Includes ``status`` so the frontend can render the "Deleted user
    #{id}" placeholder for anonymized assignees inline.
    """
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    id: int
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    avatar_base64: Optional[str] = None
    status: UserStatus = UserStatus.active


WeekdayLiteral = Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MonthlyModeLiteral = Literal["day_of_month", "weekday"]
WeekPositionLiteral = Literal["first", "second", "third", "fourth", "last"]
RecurrenceEndsLiteral = Literal["never", "on_date", "after_occurrences"]


class TaskRecurrence(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

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


_HTML_TAG_RE = re.compile(r"<[^>]+>", re.DOTALL)
# Event handler attributes e.g. onerror=, onclick=, onmouseover= …
_EVENT_HANDLER_RE = re.compile(
    r'\bon\w+\s*=\s*(?:"[^"]*"|\'[^\']*\'|[^\s>]*)', re.IGNORECASE
)
# javascript: and data: URI schemes inside attribute values
_DANGEROUS_URI_RE = re.compile(
    r'(?:javascript|data|vbscript)\s*:', re.IGNORECASE
)


def _strip_html(value: str) -> str:
    """Remove all HTML tags from a plain-text field (e.g. task title)."""
    return _HTML_TAG_RE.sub("", value).strip()


def _sanitize_html(value: str) -> str:
    """Strip dangerous HTML from a rich-text field (e.g. task description).

    Removes:
    - All inline event handlers (onerror=, onclick=, …)
    - javascript: / data: / vbscript: URI schemes
    - <script>, <iframe>, <object>, <embed>, <form>, <input> tags entirely
    Leaves safe structural/formatting tags intact so markdown-rendered
    content round-trips correctly.
    """
    # Strip dangerous elements including everything between their open/close tags.
    # Must handle both self-closing and paired tags, e.g.:
    #   <script>alert(1)</script>  → stripped entirely (tags + content)
    #   <input type="hidden">      → stripped (self-closing / void)
    _dangerous_names = (
        r"script|iframe|object|embed|form|input|base|link|meta|style"
    )
    # Paired tags: strip open tag, content, and close tag together
    paired = re.compile(
        rf"<\s*({_dangerous_names})(?:\s[^>]*)?>.*?</\s*\1\s*>",
        re.IGNORECASE | re.DOTALL,
    )
    value = paired.sub("", value)
    # Remaining unpaired / self-closing open tags (e.g. <input ...>)
    unpaired = re.compile(
        rf"<\s*/?\s*(?:{_dangerous_names})(?:\s[^>]*)?>",
        re.IGNORECASE | re.DOTALL,
    )
    value = unpaired.sub("", value)
    # Strip event handler attributes from remaining tags
    value = _EVENT_HANDLER_RE.sub("", value)
    # Strip dangerous URI schemes
    value = _DANGEROUS_URI_RE.sub("blocked:", value)
    return value.strip()


class TaskBase(BaseModel):
    title: str
    description: Optional[str] = None
    priority: TaskPriority = TaskPriority.medium

    @field_validator("title", mode="before")
    @classmethod
    def sanitize_title(cls, v: object) -> object:
        """Task titles are plain text — strip all HTML tags."""
        if isinstance(v, str):
            return _strip_html(v)
        return v

    @field_validator("description", mode="before")
    @classmethod
    def sanitize_description(cls, v: object) -> object:
        """Strip dangerous HTML from task descriptions."""
        if isinstance(v, str):
            return _sanitize_html(v)
        return v
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

    @field_validator("title", mode="before")
    @classmethod
    def sanitize_title(cls, v: object) -> object:
        if isinstance(v, str):
            return _strip_html(v)
        return v

    @field_validator("description", mode="before")
    @classmethod
    def sanitize_description(cls, v: object) -> object:
        if isinstance(v, str):
            return _sanitize_html(v)
        return v
    priority: Optional[TaskPriority] = None
    assignee_ids: Optional[List[int]] = None
    start_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    recurrence: Optional[TaskRecurrence | None] = None
    recurrence_strategy: Optional[Literal["fixed", "rolling"]] = None
    is_archived: Optional[bool] = None


class TaskMoveRequest(BaseModel):
    target_project_id: int = Field(gt=0)


class TaskProjectInitiativeSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    id: int
    name: str
    color: Optional[str] = None


class TaskProjectSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    id: int
    name: str
    icon: Optional[str] = None
    initiative_id: Optional[int] = None
    initiative: Optional[TaskProjectInitiativeSummary] = None
    is_archived: Optional[bool] = None
    is_template: Optional[bool] = None


class TaskRead(TaskBase):
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    id: int
    project_id: int
    task_status_id: int
    task_status: TaskStatusRead
    created_at: datetime
    updated_at: datetime
    sort_order: float
    is_archived: bool = False
    created_by_id: Optional[int] = None
    assignees: List[UserPublic] = []
    recurrence_occurrence_count: int = 0
    comment_count: int = 0
    guild: Optional[GuildSummary] = None
    project: Optional[TaskProjectSummary] = None
    subtask_progress: Optional[TaskSubtaskProgress] = None
    tags: List[TagSummary] = []
    properties: List[PropertySummary] = []


class TaskListRead(TaskBase):
    """Lightweight schema for task list endpoints - excludes heavy nested data"""
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    id: int
    project_id: int
    task_status_id: int
    task_status: TaskStatusRead
    created_at: datetime
    updated_at: datetime
    sort_order: float
    is_archived: bool = False
    created_by_id: Optional[int] = None
    assignees: List[TaskAssigneeSummary] = []
    recurrence_occurrence_count: int = 0
    comment_count: int = 0
    guild_id: Optional[int] = None
    guild_name: Optional[str] = None
    project_name: Optional[str] = None
    initiative_id: Optional[int] = None
    initiative_name: Optional[str] = None
    initiative_color: Optional[str] = None
    subtask_progress: Optional[TaskSubtaskProgress] = None
    tags: List[TagSummary] = []
    properties: List[PropertySummary] = []


class TaskListResponse(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[TaskListRead]
    total_count: int
    page: int
    page_size: int
    has_next: bool
    has_prev: bool
    sorting: Optional[str] = None


class TaskReorderItem(BaseModel):
    id: int
    task_status_id: int
    sort_order: float


class TaskReorderRequest(BaseModel):
    project_id: int
    items: list[TaskReorderItem]
