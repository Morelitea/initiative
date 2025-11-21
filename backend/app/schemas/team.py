from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.schemas.user import UserRead


class TeamBase(BaseModel):
    name: str
    description: Optional[str] = None


class TeamCreate(TeamBase):
    pass


class TeamUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class TeamRead(TeamBase):
    id: int
    created_at: datetime
    updated_at: datetime
    members: List[UserRead] = Field(default_factory=list)

    class Config:
        from_attributes = True


class TeamMemberAdd(BaseModel):
    user_id: int
