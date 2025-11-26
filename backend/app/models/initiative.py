from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import Boolean, Column, DateTime, String
from sqlmodel import Enum as SQLEnum, Field, Relationship, SQLModel

if TYPE_CHECKING:  # pragma: no cover
    from app.models.project import Project
    from app.models.user import User


class InitiativeRole(str, Enum):
    project_manager = "project_manager"
    member = "member"


class InitiativeMember(SQLModel, table=True):
    __tablename__ = "initiative_members"

    initiative_id: int = Field(foreign_key="initiatives.id", primary_key=True)
    user_id: int = Field(foreign_key="users.id", primary_key=True)
    role: InitiativeRole = Field(
        default=InitiativeRole.member,
        sa_column=Column(
            SQLEnum(InitiativeRole, name="initiative_role"),
            nullable=False,
            server_default=InitiativeRole.member.value,
        ),
    )
    joined_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    initiative: Optional["Initiative"] = Relationship(back_populates="memberships")
    user: Optional["User"] = Relationship(back_populates="initiative_memberships")


class Initiative(SQLModel, table=True):
    __tablename__ = "initiatives"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True, nullable=False)
    description: Optional[str] = Field(default=None)
    color: Optional[str] = Field(
        default=None,
        sa_column=Column(String(length=32), nullable=True),
    )
    is_default: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    memberships: List["InitiativeMember"] = Relationship(
        back_populates="initiative",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    projects: List["Project"] = Relationship(back_populates="initiative")
