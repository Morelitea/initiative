from typing import Optional, TYPE_CHECKING

from sqlalchemy import Column, Float
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:  # pragma: no cover
    from app.models.tenant.project import Project
    from app.models.platform.user_profile_view import MemberProfile


class ProjectOrder(SQLModel, table=True):
    __tablename__ = "project_orders"

    user_id: int = Field(foreign_key="users.id", primary_key=True)
    project_id: int = Field(foreign_key="projects.id", primary_key=True)
    guild_id: Optional[int] = Field(
        default=None, foreign_key="guilds.id", nullable=True
    )
    sort_order: float = Field(
        default=0,
        sa_column=Column(Float, nullable=False, server_default="0"),
    )

    user: Optional["MemberProfile"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": "foreign(ProjectOrder.user_id) == MemberProfile.id",
            "viewonly": True,
        }
    )
    project: Optional["Project"] = Relationship(back_populates="orders")
