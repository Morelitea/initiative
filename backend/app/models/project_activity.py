from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

from sqlalchemy import Column, DateTime
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:  # pragma: no cover
    from app.models.project import Project
    from app.models.user import User


class ProjectFavorite(SQLModel, table=True):
    __tablename__ = "project_favorites"

    user_id: int = Field(foreign_key="users.id", primary_key=True)
    project_id: int = Field(foreign_key="projects.id", primary_key=True)
    guild_id: Optional[int] = Field(default=None, foreign_key="guilds.id", nullable=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    user: Optional["User"] = Relationship(back_populates="favorite_projects")
    project: Optional["Project"] = Relationship(back_populates="favorite_entries")


class RecentProjectView(SQLModel, table=True):
    __tablename__ = "recent_project_views"

    user_id: int = Field(foreign_key="users.id", primary_key=True)
    project_id: int = Field(foreign_key="projects.id", primary_key=True)
    guild_id: Optional[int] = Field(default=None, foreign_key="guilds.id", nullable=True)
    last_viewed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    user: Optional["User"] = Relationship(back_populates="recent_project_views")
    project: Optional["Project"] = Relationship(back_populates="recent_view_entries")
