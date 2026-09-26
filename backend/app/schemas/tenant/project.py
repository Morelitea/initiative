from __future__ import annotations

from datetime import date, datetime
from typing import List, Literal, Optional

from pydantic import ConfigDict, Field

from app.core.identity_boundary import GuildId, PersonId
from app.schemas.base import RichTextStr, SanitizedBaseModel, TitleStr
from app.schemas.tenant.archive import ToolCan, ToolState

from app.schemas.tenant.resource_grant import ResourceGrantSchema, initiative_readable
from app.schemas.tenant.initiative import InitiativeSummary
from app.schemas.tenant.ownership import OwnerAppSummary
from app.schemas.tenant.document import ProjectDocumentSummary
from app.schemas.tenant.tag import TagSummary
from app.schemas.tenant.task_status import TaskStatusRead
from app.schemas.platform.user import UserPublic
from app.schemas.tenant.comment import CommentAuthor


# The task views a project can open on. Kept as a Literal rather than a
# database enum so growing it is a code change, not an ALTER TYPE in every
# guild schema.
ProjectViewMode = Literal["table", "kanban", "calendar"]

# Matches ``Project.icon``'s column width.
PROJECT_ICON_MAX_LENGTH = 8


class ProjectBase(SanitizedBaseModel):
    name: str
    description: Optional[RichTextStr] = None
    # The emoji shown beside the project's name, bounded to match the column.
    icon: Optional[str] = Field(default=None, max_length=PROJECT_ICON_MAX_LENGTH)
    # Optional whole-day schedule; either end may be set on its own.
    start_date: Optional[date] = None
    end_date: Optional[date] = None


class ProjectCreate(ProjectBase):
    name: TitleStr
    initiative_id: Optional[int] = None
    is_template: bool = False
    template_id: Optional[int] = None
    # Initial sharing — the same grant list the PUT /grants endpoint takes.
    grants: List[ResourceGrantSchema] = Field(default_factory=initiative_readable)


class ProjectUpdate(SanitizedBaseModel):
    name: Optional[TitleStr] = None
    description: Optional[RichTextStr] = None
    icon: Optional[str] = Field(default=None, max_length=PROJECT_ICON_MAX_LENGTH)
    is_template: Optional[bool] = None
    pinned: Optional[bool] = None
    # Which task view the project opens on. Send ``null`` to clear it and fall
    # back to the client default. The vocabulary lives here rather than in a
    # database enum — see the column's note on Project.
    default_view_mode: Optional[ProjectViewMode] = None
    # Send ``null`` to clear a date; omit the field to leave it untouched.
    start_date: Optional[date] = None
    end_date: Optional[date] = None


class ProjectDuplicateRequest(SanitizedBaseModel):
    name: Optional[TitleStr] = None


class ProjectTaskSummary(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    total: int = 0
    completed: int = 0


class ProjectCan(ToolCan):
    #: Configure the project itself — pin it, set its default view, curate its
    #: filter presets (``resource_actions``).
    configure: bool = False


class ProjectRead(ProjectBase, ToolState):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    # Who owns the project: the person holding its owner-level grant, or None
    # when nobody does or an app does (``owner_app``). ``owner`` carries the
    # same fact with the user attached;
    # its ``validation_alias`` (an attribute the ORM row never has) keeps
    # ``model_validate(project)`` from reaching for a relationship that may not
    # be loaded — it is set explicitly in ``_build_project_payload``.
    owner_id: Optional[PersonId] = None
    initiative_id: int
    #: The community this project lives in — the one fact a cross-guild list
    #: needs to address the row, and what every other tool summary carries.
    #: Left out of the slim picker projection, which never leaves one guild.
    guild_id: Optional[GuildId] = None
    created_at: datetime
    updated_at: datetime
    is_template: bool
    pinned_at: Optional[datetime] = None
    default_view_mode: Optional[str] = None
    owner: Optional[UserPublic] = Field(default=None, validation_alias="owner_source")
    #: The installed app holding the owner grant, or None when a person owns
    #: the project or nobody does. At most one of ``owner_id`` and this is set.
    owner_app: Optional[OwnerAppSummary] = Field(
        default=None, validation_alias="owner_app_source"
    )
    initiative: Optional[InitiativeSummary] = None
    can: ProjectCan = Field(default_factory=ProjectCan)
    sort_order: Optional[float] = None
    is_favorited: bool = False
    last_viewed_at: Optional[datetime] = None
    documents: List[ProjectDocumentSummary] = Field(default_factory=list)
    task_summary: ProjectTaskSummary = Field(default_factory=ProjectTaskSummary)
    # The project's task statuses (ordered by position). Populated on the
    # single-project detail read and mutation responses so a caller has the
    # status ids it needs to place or move a task; left empty in list
    # projections, which stay lean. The ``validation_alias`` (an attribute the
    # ORM row never has) stops ``model_validate(project)`` from auto-pulling the
    # relationship — which would lazy-load and fail on the paths that don't
    # eager-load it; the value is set explicitly in ``_build_project_payload``.
    task_statuses: List[TaskStatusRead] = Field(
        default_factory=list, validation_alias="task_statuses_source"
    )
    # When false this entity's comment thread is off — the UI renders none
    # and the API refuses to read or post one. Tasks are unaffected; their
    # thread belongs to the task, not to the tool.
    comments_enabled: bool = True
    tags: List[TagSummary] = Field(default_factory=list)
    # The full sharing state — every resource_grants row for this resource.
    grants: List[ResourceGrantSchema] = Field(default_factory=list)


class ProjectListResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[ProjectRead]
    total_count: int
    page: int
    page_size: int
    has_next: bool


class ProjectReorderRequest(SanitizedBaseModel):
    project_ids: List[int] = Field(default_factory=list)


class ProjectFavoriteStatus(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    project_id: int
    is_favorited: bool


class ProjectActivityEntry(SanitizedBaseModel):
    comment_id: int
    content: RichTextStr
    created_at: datetime
    author: Optional[CommentAuthor] = None
    task_id: int
    task_title: str


class ProjectActivityResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[ProjectActivityEntry]
    next_page: Optional[int] = None
