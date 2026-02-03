from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, Text
from sqlmodel import Field, Relationship, SQLModel

from app.models.user import User


class Comment(SQLModel, table=True):
    __tablename__ = "comments"
    __table_args__ = (
        CheckConstraint(
            "(task_id IS NULL) <> (document_id IS NULL)",
            name="ck_comments_task_or_document",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("guilds.id"), nullable=True),
    )
    content: str = Field(sa_column=Column(Text, nullable=False))
    author_id: int = Field(
        sa_column=Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    )
    task_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True),
    )
    document_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=True),
    )
    parent_comment_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("comments.id", ondelete="CASCADE"), nullable=True),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    author: User = Relationship()
