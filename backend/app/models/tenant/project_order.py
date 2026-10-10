from sqlalchemy import Column, Float
from sqlmodel import Field, SQLModel


class ProjectOrder(SQLModel, table=True):
    __tablename__ = "project_orders"

    user_id: int = Field(foreign_key="users.id", primary_key=True)
    project_id: int = Field(
        foreign_key="projects.id", ondelete="CASCADE", primary_key=True
    )
    sort_order: float = Field(
        default=0,
        sa_column=Column(Float, nullable=False, server_default="0"),
    )
