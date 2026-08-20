from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, Text
from sqlmodel import Field, Relationship

from app.models.tenant._mixins import RowAuditMixin, SoftDeleteMixin
from app.models.platform.user import User


class Comment(RowAuditMixin, SoftDeleteMixin, table=True):
    __tablename__ = "comments"
    _display_field = "content"
    __table_args__ = (
        CheckConstraint(
            "(task_id IS NULL) <> (document_id IS NULL)",
            name="ck_comments_task_or_document",
        ),
    )
    # Comment authorship is intentionally NOT reassignable on restore.
    # Comments are first-person speech; transferring created_by_id to someone
    # else would let admins put words in another user's mouth. If the
    # original author has left, the restore goes through and the comment
    # renders as "Deleted user #N" via the existing user-display helpers.

    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("guilds.id"), nullable=True),
    )
    content: str = Field(sa_column=Column(Text, nullable=False))
    created_by_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
    )
    task_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True
        ),
    )
    document_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=True
        ),
    )
    parent_comment_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("comments.id", ondelete="CASCADE"), nullable=True
        ),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    # The API calls this the author; the column is the schema-wide
    # ``created_by_id``. ``foreign_keys`` is explicit because
    # ``updated_by_id`` also relates Comment->User.
    author: User = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[Comment.created_by_id]"},
    )
