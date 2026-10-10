from datetime import datetime, timezone
from sqlalchemy import Column, DateTime
from sqlmodel import Field, SQLModel


class ProjectFavorite(SQLModel, table=True):
    __tablename__ = "project_favorites"

    user_id: int = Field(foreign_key="users.id", primary_key=True)
    project_id: int = Field(
        foreign_key="projects.id", ondelete="CASCADE", primary_key=True
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
