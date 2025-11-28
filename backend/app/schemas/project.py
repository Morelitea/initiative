from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.project import ProjectPermissionLevel
from app.schemas.initiative import InitiativeRead
from app.schemas.document import ProjectDocumentSummary
from app.schemas.user import UserRead


class ProjectBase(BaseModel):
    name: str
    description: Optional[str] = None
    icon: Optional[str] = None
    members_can_write: bool = False


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
    members_can_write: Optional[bool] = None
    is_template: Optional[bool] = None


class ProjectDuplicateRequest(BaseModel):
    name: Optional[str] = None


class ProjectPermissionBase(BaseModel):
    user_id: int
    level: ProjectPermissionLevel = ProjectPermissionLevel.write


class ProjectPermissionCreate(ProjectPermissionBase):
    pass


class ProjectPermissionRead(ProjectPermissionBase):
    created_at: datetime

    class Config:
        from_attributes = True


class ProjectRead(ProjectBase):
    id: int
    owner_id: int
    initiative_id: int
    created_at: datetime
    updated_at: datetime
    is_archived: bool
    is_template: bool
    archived_at: Optional[datetime] = None
    owner: Optional[UserRead] = None
    initiative: Optional[InitiativeRead] = None
    permissions: List[ProjectPermissionRead] = Field(default_factory=list)
    sort_order: Optional[float] = None
    is_favorited: bool = False
    last_viewed_at: Optional[datetime] = None
    documents: List[ProjectDocumentSummary] = Field(default_factory=list)

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
