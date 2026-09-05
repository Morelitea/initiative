from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, Text
from sqlmodel import Field, Relationship

from app.models.tenant._mixins import CreatedByMixin, SoftDeleteMixin
from app.models.platform.user_profile_view import MemberProfile


class Comment(CreatedByMixin, SoftDeleteMixin, table=True):
    __tablename__ = "comments"
    _display_field = "content"
    __table_args__ = (
        # A comment hangs off exactly ONE parent: a task, or one tool entity
        # (document, project, queue, counter group, calendar, dashboard, post).
        CheckConstraint(
            "num_nonnulls(task_id, document_id, project_id, queue_id, "
            "counter_group_id, calendar_id, dashboard_id, post_id) = 1",
            name="ck_comments_single_parent",
        ),
    )
    # Comment authorship is intentionally NOT reassignable on restore.
    # Comments are first-person speech; transferring created_by to someone
    # else would let admins put words in another user's mouth. If the
    # original author has left, the restore goes through and the comment
    # renders as "Deleted user #N" via the existing user-display helpers.

    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("guilds.id"), nullable=True),
    )
    content: str = Field(sa_column=Column(Text, nullable=False))
    created_by: int = Field(
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
    # Tool-entity parents: every Tool is commentable (drift-tested against the
    # enum in comments_test), one nullable FK per tool alongside the original
    # task/document pair. ``project_id`` means a comment ON the project itself;
    # a task comment reports its task's project through the read schema only.
    project_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
        ),
    )
    queue_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("queues.id", ondelete="CASCADE"), nullable=True
        ),
    )
    counter_group_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("counter_groups.id", ondelete="CASCADE"), nullable=True
        ),
    )
    calendar_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("calendars.id", ondelete="CASCADE"), nullable=True
        ),
    )
    dashboard_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("dashboards.id", ondelete="CASCADE"), nullable=True
        ),
    )
    post_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("posts.id", ondelete="CASCADE"), nullable=True
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
    # ``created_by``, which is what a comment's author IS. The join is spelled
    # out because the target is a view, which carries no foreign key.
    author: Optional["MemberProfile"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": "foreign(Comment.created_by) == MemberProfile.id",
            "viewonly": True,
        },
    )
