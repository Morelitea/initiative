from datetime import datetime, timezone
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import Column, DateTime, String
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:  # pragma: no cover
    from app.models.project import Project
    from app.models.user import User


class InitiativeMember(SQLModel, table=True):
    __tablename__ = "initiative_members"

    initiative_id: int = Field(foreign_key="initiatives.id", primary_key=True)
    user_id: int = Field(foreign_key="users.id", primary_key=True)
    joined_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class Initiative(SQLModel, table=True):
    __tablename__ = "initiatives"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True, nullable=False)
    description: Optional[str] = Field(default=None)
    color: Optional[str] = Field(
        default=None,
        sa_column=Column(String(length=32), nullable=True),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    members: List["User"] = Relationship(back_populates="initiatives", link_model=InitiativeMember)
    projects: List["Project"] = Relationship(back_populates="initiative")
