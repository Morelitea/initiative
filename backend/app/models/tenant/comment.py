from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, Text
from sqlmodel import Field, Relationship

from app.core.tools import COMMENT_TARGETS
from app.models.tenant._mixins import CreatedByMixin, SoftDeleteMixin
from app.models.platform.user_profile_view import MemberProfile


#: The comment columns naming a parent — one per tool plus the content-level
#: extras — as the single-parent CHECK spells them. Derived from the registry
#: so the constraint and the columns below cannot name different sets.
COMMENT_PARENT_COLUMN_SQL = ", ".join(f"{target}_id" for target in COMMENT_TARGETS)


class Comment(CreatedByMixin, SoftDeleteMixin, table=True):
    __tablename__ = "comments"
    _display_field = "content"
    __table_args__ = (
        # A comment hangs off exactly ONE parent: one tool entity, or one of
        # the content-level extras. The column list is derived from
        # ``COMMENT_TARGETS``, so a new parent's column joins the rule by
        # existing rather than by being remembered here.
        CheckConstraint(
            f"num_nonnulls({COMMENT_PARENT_COLUMN_SQL}) = 1",
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
    gallery_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("galleries.id", ondelete="CASCADE"), nullable=True
        ),
    )
    wiki_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("wikis.id", ondelete="CASCADE"), nullable=True
        ),
    )
    # A wiki's conversation happens on its pages: a note about the rota belongs
    # on the rota. The wiki's own column above stays a parent so the tool is
    # commentable like every other, but the thread people use is this one.
    wiki_page_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("wiki_pages.id", ondelete="CASCADE"), nullable=True
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
