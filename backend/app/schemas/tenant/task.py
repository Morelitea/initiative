from datetime import datetime
from string import ascii_letters, digits
from typing import Final, List, Literal, Optional
from uuid import uuid4

from pydantic import ConfigDict, Field, field_validator

from app.core.identity_boundary import GuildId, PersonId
from app.schemas.base import RichTextStr, SanitizedBaseModel, TitleStr
from app.schemas.query import PageMeta
from app.schemas.recurrence import OccurrenceScope, TaskRule

from app.schemas.platform.user import AvatarUrl, UserPublic
from app.schemas.tenant.initiative import InitiativeSummary
from app.schemas.tenant.task_status import TaskStatusRead
from app.schemas.tenant.tag import TagSummary
from app.schemas.tenant.property import (
    PropertiesOnCreate,
    PropertiesOnUpdate,
    PropertySummary,
)

from app.models.tenant.task import TaskPriority
from app.models.platform.user import UserStatus


class TaskAssigneeSummary(SanitizedBaseModel):
    """Minimal assignee data for task lists.

    A person appears here, so it follows the same two rules every other
    guild-scoped shape does: the handle is always present and is what renders
    when there is no name to show, and ``display_name`` is the name the person
    set in this guild.
    """

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: PersonId
    username: str
    discriminator: int
    display_name: Optional[str] = None
    avatar_url: AvatarUrl = None
    status: UserStatus = UserStatus.active


#: Characters a checklist item id may hold. The client mints one per item so a
#: new line is addressable before it round-trips; anything arriving from an
#: import or the AI batch is minted here instead.
_ITEM_ID_CHARS: Final = frozenset(ascii_letters + digits + "-_")
_MAX_ITEM_ID_LENGTH: Final = 36

#: Flat code raised for an id outside that set, mapped in ``errors.json``.
INVALID_CHECKLIST_ITEM_ID = "INVALID_CHECKLIST_ITEM_ID"


def mint_checklist_item_id() -> str:
    """A fresh item id, for an item that arrived without one."""
    return uuid4().hex


class ChecklistItemInput(SanitizedBaseModel):
    """One checklist line as written. ``id`` is optional: an item that arrives
    without one is given a fresh id."""

    id: Optional[str] = Field(default=None, max_length=_MAX_ITEM_ID_LENGTH)
    text: str = Field(min_length=1, max_length=2000)
    done: bool = False

    @field_validator("id")
    def id_is_an_identifier(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and (not value or set(value) - _ITEM_ID_CHARS):
            raise ValueError(INVALID_CHECKLIST_ITEM_ID)
        return value


class ChecklistItem(SanitizedBaseModel):
    """One checklist line as stored and read back."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: str
    text: str
    done: bool = False


class ChecklistProgress(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    completed: int = 0
    total: int = 0


class ChecklistItemToggle(SanitizedBaseModel):
    """The one field a tick changes."""

    done: bool


#: Ceiling on a single task's checklist. A list past this is a project.
#: Enforced in ``services.tenant.task_checklist.normalize``, which can see both
#: the written list and the one it replaces — a longer list carried in by a
#: migration or an import has to stay shrinkable.
MAX_CHECKLIST_ITEMS: Final = 100


class TaskBase(SanitizedBaseModel):
    title: str
    priority: TaskPriority = TaskPriority.medium
    start_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    recurrence: Optional[str] = None
    recurrence_strategy: Literal["fixed", "rolling"] = "fixed"


class TaskCreate(TaskBase, PropertiesOnCreate):
    title: TitleStr
    description: Optional[RichTextStr] = None
    project_id: int
    recurrence: Optional[TaskRule] = None
    #: The zone ``recurrence``'s days were picked in, and ``recurrence_shift``
    #: is taken from it. Omitted, the rule's days are UTC days.
    tz: Optional[str] = Field(default=None, max_length=64)
    assignee_ids: List[PersonId] = Field(default_factory=list)
    task_status_id: Optional[int] = None
    tag_ids: List[int] = Field(default_factory=list, max_length=100)
    checklist: List[ChecklistItemInput] = Field(default_factory=list)


class TaskUpdate(PropertiesOnUpdate):
    title: Optional[TitleStr] = None
    description: Optional[RichTextStr] = None
    task_status_id: Optional[int] = None
    priority: Optional[TaskPriority] = None
    assignee_ids: Optional[List[PersonId]] = None
    start_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    recurrence: Optional[TaskRule] = None
    #: The zone ``recurrence``'s days were picked in, and ``recurrence_shift``
    #: is taken from it. Omitted, the rule's days are UTC days.
    tz: Optional[str] = Field(default=None, max_length=64)
    recurrence_strategy: Optional[Literal["fixed", "rolling"]] = None
    # PATCH semantics: None = "leave unchanged"; a list (incl. []) = replace-all.
    tag_ids: Optional[List[int]] = Field(default=None, max_length=100)
    checklist: Optional[List[ChecklistItemInput]] = None
    #: Which tasks of a repeating series the edit is for (``task_series``).
    #: Omitted, it carries forward from this task ("following"). The repeat
    #: itself always changes from this task on.
    scope: Optional[OccurrenceScope] = None


class TaskMoveRequest(SanitizedBaseModel):
    target_project_id: int = Field(gt=0)


class TaskProjectSummary(SanitizedBaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    name: str
    icon: Optional[str] = None
    initiative_id: Optional[int] = None
    initiative: Optional[InitiativeSummary] = None
    archived_at: Optional[datetime] = None
    is_template: Optional[bool] = None


class TaskRead(TaskBase):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    description: Optional[RichTextStr] = None
    id: int
    project_id: int
    task_status_id: int
    task_status: TaskStatusRead
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    position: float
    archived_at: Optional[datetime] = None
    created_by: Optional[PersonId] = None
    # Author summary — lets the detail view render "Created by …" without
    # fetching the whole guild roster to resolve ``created_by``.
    creator: Optional[UserPublic] = None
    assignees: List[UserPublic] = []
    recurrence_occurrence_count: int = 0
    recurrence_shift: int = 0
    #: No occurrence of the series starts after this; None while it goes on.
    recurrence_until: Optional[datetime] = None
    #: The first task of the repeating series; None until the series moves on.
    series_id: Optional[int] = None
    #: How many live tasks the series holds, this one included.
    series_size: int = 1
    comment_count: int = 0
    #: How many things are still holding this task up: live ``depends_on``
    #: edges whose far end has not finished. Only kinds with a reading of
    #: "finished" count — see :mod:`app.db.blocking`.
    blocked_by_open_count: int = 0
    project: Optional[TaskProjectSummary] = None
    checklist: List[ChecklistItem] = []
    checklist_progress: Optional[ChecklistProgress] = None
    tags: List[TagSummary] = []
    properties: List[PropertySummary] = []


class TaskListRead(TaskBase):
    """Lightweight schema for task list endpoints - excludes heavy nested data"""

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    #: The description's opening words as plain text, ending on a word
    #: boundary with an ellipsis when cut. The whole text is on ``TaskRead``.
    description_excerpt: Optional[str] = None
    has_description: bool = False
    id: int
    project_id: int
    task_status_id: int
    task_status: TaskStatusRead
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    position: float
    archived_at: Optional[datetime] = None
    created_by: Optional[PersonId] = None
    assignees: List[TaskAssigneeSummary] = []
    recurrence_occurrence_count: int = 0
    recurrence_shift: int = 0
    #: No occurrence of the series starts after this; None while it goes on.
    recurrence_until: Optional[datetime] = None
    comment_count: int = 0
    #: How many things are still holding this task up: live ``depends_on``
    #: edges whose far end has not finished. Only kinds with a reading of
    #: "finished" count — see :mod:`app.db.blocking`.
    blocked_by_open_count: int = 0
    guild_id: Optional[GuildId] = None
    guild_name: Optional[str] = None
    project_name: Optional[str] = None
    initiative_id: Optional[int] = None
    initiative_name: Optional[str] = None
    initiative_color: Optional[str] = None
    checklist_progress: Optional[ChecklistProgress] = None
    tags: List[TagSummary] = []
    properties: List[PropertySummary] = []


class TaskListResponse(PageMeta):
    items: List[TaskListRead]
    sorting: Optional[str] = None


class TaskReorderItem(SanitizedBaseModel):
    id: int
    task_status_id: int
    # Bounded to reject NaN/±inf (which would silently defeat the rebalance
    # gap check, where `abs(a - b) < gap` is always False for NaN). Negative
    # values are valid — dropping above a card with a fractional position can
    # legitimately produce one.
    position: float = Field(ge=-1e18, le=1e18)


class TaskReorderRequest(SanitizedBaseModel):
    project_id: int
    items: list[TaskReorderItem]
