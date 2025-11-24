from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.schemas.user import UserRead


class InitiativeBase(BaseModel):
    name: str
    description: Optional[str] = None


class InitiativeCreate(InitiativeBase):
    pass


class InitiativeUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class InitiativeRead(InitiativeBase):
    id: int
    created_at: datetime
    updated_at: datetime
    members: List[UserRead] = Field(default_factory=list)

    class Config:
        from_attributes = True


class InitiativeMemberAdd(BaseModel):
    user_id: int
