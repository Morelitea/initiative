from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any, List, Literal, Optional

from pydantic import ConfigDict, Field
from sqlalchemy import inspect as sa_inspect

from app.core.identity_boundary import PersonId
from app.schemas.base import (
    RichMentionStr,
    RichTextStr,
    SanitizedBaseModel,
    TitleStr,
    reject_null,
)
from app.schemas.query import PageMeta
from app.schemas.tenant.archive import ToolCan

from app.schemas.tenant.resource_grant import ResourceGrantSchema, initiative_readable
from app.schemas.tenant.initiative import InitiativeSummary
from app.schemas.tenant.ownership import OwnerPluginSummary, owner_profile
from app.schemas.tenant.property import PropertiesOnCreate
from app.schemas.tenant.tool import ToolSummaryBase
from app.schemas.tenant.task_status import TaskStatusRead
from app.schemas.platform.user import UserPublic
from app.schemas.tenant.comment import CommentAuthor

if TYPE_CHECKING:  # pragma: no cover
    from app.db.guild_standing import ActorContext


# The task views a project can open on. Kept as a Literal rather than a
# database enum so growing it is a code change, not an ALTER TYPE in every
# guild schema.
ProjectViewMode = Literal["table", "kanban", "calendar"]

# Matches ``Project.icon``'s column width.
PROJECT_ICON_MAX_LENGTH = 8


class ProjectBase(SanitizedBaseModel):
    name: str
    description: Optional[RichMentionStr] = None
    # The emoji shown beside the project's name, bounded to match the column.
    icon: Optional[str] = Field(default=None, max_length=PROJECT_ICON_MAX_LENGTH)
    # Optional whole-day schedule; either end may be set on its own.
    start_date: Optional[date] = None
    end_date: Optional[date] = None


class ProjectCreate(ProjectBase, PropertiesOnCreate):
    name: TitleStr
    initiative_id: Optional[int] = None
    is_template: bool = False
    template_id: Optional[int] = None
    # Initial sharing — the same grant list the PUT /grants endpoint takes.
    grants: List[ResourceGrantSchema] = Field(default_factory=initiative_readable)


class ProjectUpdate(SanitizedBaseModel):
    name: Optional[TitleStr] = None
    description: Optional[RichMentionStr] = None
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

    _required = reject_null("name", "is_template")


class ProjectTaskSummary(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    total: int = 0
    completed: int = 0


class ProjectCan(ToolCan):
    #: Configure the project itself — pin it, set its default view, curate its
    #: filter presets (``resource_actions``).
    configure: bool = False


class ProjectRead(ProjectBase, ToolSummaryBase):
    # ``validate_by_name`` so ``derived_fields`` can set ``owner``,
    # ``owner_plugin`` and ``task_statuses`` by name; their aliases keep
    # ``from_attributes`` from reading an ORM relationship.
    model_config = ConfigDict(validate_by_name=True)

    # Who owns the project: the person holding its owner-level grant, or None
    # when nobody does or a plug-in does (``owner_plugin``). ``owner`` carries the
    # same fact with the user attached.
    owner_id: Optional[PersonId] = None
    is_template: bool
    pinned_at: Optional[datetime] = None
    default_view_mode: Optional[ProjectViewMode] = None
    owner: Optional[UserPublic] = Field(default=None, validation_alias="owner_source")
    #: The installed plug-in holding the owner grant, or None when a person owns
    #: the project or nobody does. At most one of ``owner_id`` and this is set.
    owner_plugin: Optional[OwnerPluginSummary] = Field(
        default=None, validation_alias="owner_plugin_source"
    )
    initiative: Optional[InitiativeSummary] = None
    can: ProjectCan = Field(default_factory=ProjectCan)
    is_favorited: bool = False
    last_viewed_at: Optional[datetime] = None
    task_summary: ProjectTaskSummary = Field(default_factory=ProjectTaskSummary)
    # The project's task statuses (ordered by position), on a read that loaded
    # them — the detail read and a write's answer — so a caller has the status
    # ids it needs to place or move a task. Empty on a list.
    task_statuses: List[TaskStatusRead] = Field(
        default_factory=list, validation_alias="task_statuses_source"
    )

    @classmethod
    def derived_fields(
        cls, row: Any, *, context: ActorContext, user_id: Optional[int]
    ) -> dict[str, Any]:
        from app.services.tenant.ownership import owner_plugin_of, owner_user_id_of

        return {
            "can": project_can(row, user_id, context=context),
            "owner_id": owner_user_id_of(row),
            "owner": owner_profile(row),
            "owner_plugin": owner_plugin_of(row),
            "task_statuses": _task_statuses(row),
        }


def project_can(
    project: Any, user_id: Optional[int], *, context: ActorContext
) -> ProjectCan:
    """What the reader may do to the project, configuring it included."""
    from app.services.permissions import Action, allows, client_access

    return ProjectCan(
        **client_access(project, user_id, context=context),
        configure=allows(project, Action.configure),
    )


def _task_statuses(project: Any) -> List[TaskStatusRead]:
    """The project's task statuses by position, or none when the read did not
    load them — a list never does, and reaching for them would lazy-load."""
    if "task_statuses" in sa_inspect(project).unloaded:
        return []
    statuses = sorted(project.task_statuses, key=lambda s: (s.position, s.id or 0))
    return [TaskStatusRead.model_validate(status) for status in statuses]


class ProjectListResponse(PageMeta):
    items: List[ProjectRead]


class ProjectReorderRequest(SanitizedBaseModel):
    project_ids: List[int] = Field(default_factory=list)


class ProjectActivityEntry(SanitizedBaseModel):
    comment_id: int
    content: RichTextStr
    created_at: datetime
    author: Optional[CommentAuthor] = None
    task_id: int
    task_title: str


class ProjectActivityResponse(PageMeta):
    items: List[ProjectActivityEntry]
