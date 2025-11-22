from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.project import ProjectRole
from app.schemas.team import TeamRead
from app.schemas.user import UserRead


class ProjectBase(BaseModel):
    name: str
    description: Optional[str] = None
    icon: Optional[str] = None


class ProjectCreate(ProjectBase):
    owner_id: Optional[int] = None
    team_id: Optional[int] = None
    read_roles: Optional[List[ProjectRole]] = None
    write_roles: Optional[List[ProjectRole]] = None
    is_template: bool = False
    template_id: Optional[int] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    team_id: Optional[int] = None
    read_roles: Optional[List[ProjectRole]] = None
    write_roles: Optional[List[ProjectRole]] = None
    is_template: Optional[bool] = None


class ProjectDuplicateRequest(BaseModel):
    name: Optional[str] = None


class ProjectMemberBase(BaseModel):
    user_id: int
    role: ProjectRole = ProjectRole.member


class ProjectMemberCreate(ProjectMemberBase):
    pass


class ProjectMemberRead(ProjectMemberBase):
    joined_at: datetime

    class Config:
        from_attributes = True


class ProjectRead(ProjectBase):
    id: int
    owner_id: int
    team_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    read_roles: List[ProjectRole] = Field(default_factory=list)
    write_roles: List[ProjectRole] = Field(default_factory=list)
    is_archived: bool
    is_template: bool
    archived_at: Optional[datetime] = None
    owner: Optional[UserRead] = None
    team: Optional[TeamRead] = None
    members: List[ProjectMemberRead] = Field(default_factory=list)
    sort_order: Optional[float] = None

    class Config:
        from_attributes = True


class ProjectReorderRequest(BaseModel):
    project_ids: List[int] = Field(default_factory=list)
