from __future__ import annotations

from datetime import date, datetime
from typing import List, Literal, Optional

from pydantic import ConfigDict, Field

from app.schemas.base import RichTextStr, SanitizedBaseModel

from app.schemas.tenant.resource_grant import ResourceGrantSchema
from app.schemas.tenant.initiative import InitiativeRead
from app.schemas.tenant.document import ProjectDocumentSummary
from app.schemas.tenant.tag import TagSummary
from app.schemas.tenant.task_status import TaskStatusRead
from app.schemas.platform.user import UserPublic
from app.schemas.tenant.comment import CommentAuthor


# The task views a project can open on. Kept as a Literal rather than a
# database enum so growing it is a code change, not an ALTER TYPE in every
# guild schema.
ProjectViewMode = Literal["table", "kanban", "calendar"]


class ProjectBase(SanitizedBaseModel):
    name: str
    description: Optional[RichTextStr] = None
    icon: Optional[str] = None
    # Optional whole-day schedule; either end may be set on its own.
    start_date: Optional[date] = None
    end_date: Optional[date] = None


class ProjectCreate(ProjectBase):
    owner_id: Optional[int] = None
    initiative_id: Optional[int] = None
    is_template: bool = False
    template_id: Optional[int] = None
    # Initial sharing — the same grant list the PUT /grants endpoint takes.
    # Defaults to Viewer for all initiative members.
    grants: List[ResourceGrantSchema] = Field(
        default_factory=lambda: [
            ResourceGrantSchema(all_initiative_members=True, level="read")
        ]
    )


class ProjectUpdate(SanitizedBaseModel):
    name: Optional[str] = None
    description: Optional[RichTextStr] = None
    icon: Optional[str] = None
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
    name: Optional[str] = None


class ProjectTaskSummary(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    total: int = 0
    completed: int = 0


class ProjectRead(ProjectBase):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    # Who administers the project: the holder of its owner-level grant, or None
    # when nobody does. ``owner`` carries the same fact with the user attached;
    # its ``validation_alias`` (an attribute the ORM row never has) keeps
    # ``model_validate(project)`` from reaching for a relationship that may not
    # be loaded — it is set explicitly in ``_build_project_payload``.
    owner_id: Optional[int] = None
    initiative_id: int
    created_at: datetime
    updated_at: datetime
    is_archived: bool
    is_template: bool
    archived_at: Optional[datetime] = None
    pinned_at: Optional[datetime] = None
    default_view_mode: Optional[str] = None
    owner: Optional[UserPublic] = Field(default=None, validation_alias="owner_source")
    initiative: Optional[InitiativeRead] = None
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
    # Advanced setting: when true this entity's comment thread is off — the
    # UI renders none and the API refuses to read or post one. Tasks are
    # unaffected; their thread belongs to the task, not to the tool.
    comments_disabled: bool = False
    tags: List[TagSummary] = Field(default_factory=list)
    # The current user's effective level on this resource (what *I* can do).
    my_permission_level: Optional[str] = None
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
