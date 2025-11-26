from datetime import datetime
from typing import List, Optional, TYPE_CHECKING

from pydantic import BaseModel, Field

from app.models.initiative import InitiativeRole
from app.schemas.user import UserRead

if TYPE_CHECKING:  # pragma: no cover
    from app.models.initiative import Initiative


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


class InitiativeMemberBase(BaseModel):
    user_id: int
    role: InitiativeRole = InitiativeRole.member


class InitiativeMemberAdd(InitiativeMemberBase):
    pass


class InitiativeMemberUpdate(BaseModel):
    role: InitiativeRole


class InitiativeMemberRead(BaseModel):
    user: UserRead
    role: InitiativeRole
    joined_at: datetime

    class Config:
        from_attributes = True


class InitiativeRead(InitiativeBase):
    id: int
    is_default: bool = False
    created_at: datetime
    updated_at: datetime
    members: List[InitiativeMemberRead] = Field(default_factory=list)

    class Config:
        from_attributes = True


def serialize_initiative(initiative: "Initiative") -> InitiativeRead:
    members: List[InitiativeMemberRead] = []
    for membership in getattr(initiative, "memberships", []) or []:
        if membership.user is None:
            continue
        members.append(
            InitiativeMemberRead(
                user=UserRead.model_validate(membership.user),
                role=membership.role,
                joined_at=membership.joined_at,
            )
        )
    return InitiativeRead(
        id=initiative.id,
        name=initiative.name,
        description=initiative.description,
        color=initiative.color,
        is_default=initiative.is_default,
        created_at=initiative.created_at,
        updated_at=initiative.updated_at,
        members=members,
    )
