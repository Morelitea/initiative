from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.schemas.user import UserRead


HEX_COLOR_PATTERN = r"^#(?:[0-9a-fA-F]{3}){1,2}$"


class InitiativeBase(BaseModel):
    name: str
    description: Optional[str] = None
    color: Optional[str] = Field(default=None, pattern=HEX_COLOR_PATTERN)


class InitiativeCreate(InitiativeBase):
    pass


class InitiativeUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = Field(default=None, pattern=HEX_COLOR_PATTERN)


class InitiativeRead(InitiativeBase):
    id: int
    created_at: datetime
    updated_at: datetime
    members: List[UserRead] = Field(default_factory=list)

    class Config:
        from_attributes = True


class InitiativeMemberAdd(BaseModel):
    user_id: int
