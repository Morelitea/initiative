from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import ConfigDict, Field

from app.schemas.base import RichTextStr, SanitizedBaseModel

from app.models.project import ProjectPermissionLevel
from app.schemas.initiative import InitiativeRead
from app.schemas.document import ProjectDocumentSummary
from app.schemas.tag import TagSummary
from app.schemas.user import UserPublic
from app.schemas.comment import CommentAuthor


class ProjectBase(SanitizedBaseModel):
    name: str
    description: Optional[RichTextStr] = None
    icon: Optional[str] = None


class ProjectCreate(ProjectBase):
    owner_id: Optional[int] = None
    initiative_id: Optional[int] = None
    is_template: bool = False
    template_id: Optional[int] = None
    role_permissions: Optional[List[ProjectRolePermissionCreate]] = None
    user_permissions: Optional[List[ProjectPermissionCreate]] = None


class ProjectUpdate(SanitizedBaseModel):
    name: Optional[str] = None
    description: Optional[RichTextStr] = None
    icon: Optional[str] = None
    is_template: Optional[bool] = None
    pinned: Optional[bool] = None


class ProjectDuplicateRequest(SanitizedBaseModel):
    name: Optional[str] = None


class ProjectRolePermissionCreate(SanitizedBaseModel):
    initiative_role_id: int
    level: ProjectPermissionLevel = ProjectPermissionLevel.read


class ProjectRolePermissionUpdate(SanitizedBaseModel):
    level: ProjectPermissionLevel


class ProjectRolePermissionRead(SanitizedBaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    initiative_role_id: int
    role_name: str = ""
    role_display_name: str = ""
    level: ProjectPermissionLevel
    created_at: datetime


class ProjectPermissionBase(SanitizedBaseModel):
    user_id: int
    level: ProjectPermissionLevel = ProjectPermissionLevel.write


class ProjectPermissionCreate(ProjectPermissionBase):
    pass


class ProjectPermissionBulkCreate(SanitizedBaseModel):
    user_ids: List[int]
    level: ProjectPermissionLevel = ProjectPermissionLevel.read


class ProjectPermissionBulkDelete(SanitizedBaseModel):
    user_ids: List[int]


class ProjectPermissionUpdate(SanitizedBaseModel):
    level: ProjectPermissionLevel


class ProjectPermissionRead(ProjectPermissionBase):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    created_at: datetime


class ProjectTaskSummary(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    total: int = 0
    completed: int = 0


class ProjectRead(ProjectBase):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    owner_id: int
    initiative_id: int
    created_at: datetime
    updated_at: datetime
    is_archived: bool
    is_template: bool
    archived_at: Optional[datetime] = None
    pinned_at: Optional[datetime] = None
    owner: Optional[UserPublic] = None
    initiative: Optional[InitiativeRead] = None
    permissions: List[ProjectPermissionRead] = Field(default_factory=list)
    role_permissions: List[ProjectRolePermissionRead] = Field(default_factory=list)
    sort_order: Optional[float] = None
    is_favorited: bool = False
    last_viewed_at: Optional[datetime] = None
    documents: List[ProjectDocumentSummary] = Field(default_factory=list)
    task_summary: ProjectTaskSummary = Field(default_factory=ProjectTaskSummary)
    tags: List[TagSummary] = Field(default_factory=list)
    my_permission_level: Optional[str] = None


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
