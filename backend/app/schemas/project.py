from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.project import ProjectPermissionLevel
from app.schemas.initiative import InitiativeRead
from app.schemas.document import ProjectDocumentSummary
from app.schemas.user import UserPublic
from app.schemas.comment import CommentAuthor


class ProjectBase(BaseModel):
    name: str
    description: Optional[str] = None
    icon: Optional[str] = None


class ProjectCreate(ProjectBase):
    owner_id: Optional[int] = None
    initiative_id: Optional[int] = None
    is_template: bool = False
    template_id: Optional[int] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    initiative_id: Optional[int] = None
    is_template: Optional[bool] = None
    pinned: Optional[bool] = None


class ProjectDuplicateRequest(BaseModel):
    name: Optional[str] = None


class ProjectPermissionBase(BaseModel):
    user_id: int
    level: ProjectPermissionLevel = ProjectPermissionLevel.write


class ProjectPermissionCreate(ProjectPermissionBase):
    pass


class ProjectPermissionBulkCreate(BaseModel):
    user_ids: List[int]
    level: ProjectPermissionLevel = ProjectPermissionLevel.read


class ProjectPermissionUpdate(BaseModel):
    level: ProjectPermissionLevel


class ProjectPermissionRead(ProjectPermissionBase):
    created_at: datetime

    class Config:
        from_attributes = True


class ProjectTaskSummary(BaseModel):
    total: int = 0
    completed: int = 0


class ProjectRead(ProjectBase):
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
    sort_order: Optional[float] = None
    is_favorited: bool = False
    last_viewed_at: Optional[datetime] = None
    documents: List[ProjectDocumentSummary] = Field(default_factory=list)
    task_summary: ProjectTaskSummary = Field(default_factory=ProjectTaskSummary)

    class Config:
        from_attributes = True


class ProjectReorderRequest(BaseModel):
    project_ids: List[int] = Field(default_factory=list)


class ProjectFavoriteStatus(BaseModel):
    project_id: int
    is_favorited: bool


class ProjectRecentViewRead(BaseModel):
    project_id: int
    last_viewed_at: datetime


class ProjectActivityEntry(BaseModel):
    comment_id: int
    content: str
    created_at: datetime
    author: Optional[CommentAuthor] = None
    task_id: int
    task_title: str


class ProjectActivityResponse(BaseModel):
    items: List[ProjectActivityEntry]
    next_page: Optional[int] = None
