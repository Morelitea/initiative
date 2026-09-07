from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import ConfigDict, Field, computed_field, field_validator, model_validator

from app.schemas.base import RichTextStr, SanitizedBaseModel
from app.schemas.tenant.reaction import ReactionGroup
from app.models.platform.user import Presence
from app.schemas.platform.user import GuildNameVisibility, ProfileDecorations
from app.services.platform import presence


class CommentAuthor(GuildNameVisibility):
    """Who wrote a comment.

    An address never reaches a guild, so there is none here; the handle names
    the author, and ``full_name`` arrives only from a guild that shows real
    names.

    It carries what a picture needs to be drawn the way it is drawn everywhere
    else — the decorations and how they are appearing — because a comment is
    one of the places a person appears at a size where both are legible.
    Neither is private: the same two are on the public profile.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    discriminator: int
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    profile_decorations: ProfileDecorations = Field(default_factory=ProfileDecorations)

    @computed_field(return_type=Presence)  # type: ignore[misc]
    @property
    def presence(self) -> Presence:
        """How they appear, at the moment this was serialized.

        Computed rather than stamped by each endpoint: a comment author is
        built in nine places, and what a reader is shown is not a column
        anything could select — it is what the account picked narrowed by which
        sockets are open. So it is read where the shape is made rather than
        passed down to it.
        """
        return presence.online.presence_of(self.id)


class CommentBase(SanitizedBaseModel):
    content: RichTextStr

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Content is required")
        return normalized


# Every comment parent, in one place: the task plus one field per tool. The
# comments table carries a matching FK per entry, and the create/list surfaces
# take exactly one of them.
COMMENT_TARGET_FIELDS: tuple[str, ...] = (
    "task_id",
    "document_id",
    "project_id",
    "queue_id",
    "counter_group_id",
    "calendar_id",
    "dashboard_id",
    "post_id",
)


class CommentCreate(CommentBase):
    task_id: Optional[int] = Field(default=None, gt=0)
    document_id: Optional[int] = Field(default=None, gt=0)
    project_id: Optional[int] = Field(default=None, gt=0)
    queue_id: Optional[int] = Field(default=None, gt=0)
    counter_group_id: Optional[int] = Field(default=None, gt=0)
    calendar_id: Optional[int] = Field(default=None, gt=0)
    dashboard_id: Optional[int] = Field(default=None, gt=0)
    post_id: Optional[int] = Field(default=None, gt=0)
    parent_comment_id: Optional[int] = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_target(self) -> "CommentCreate":
        provided = [
            field for field in COMMENT_TARGET_FIELDS if getattr(self, field) is not None
        ]
        if len(provided) != 1:
            raise ValueError("Provide exactly one comment target")
        return self

    def target_ids(self) -> dict[str, Optional[int]]:
        """The target fields as service kwargs."""
        return {field: getattr(self, field) for field in COMMENT_TARGET_FIELDS}


class ToolCommentSettings(SanitizedBaseModel):
    """The comment switch on one tool entity — the body and the reply of the
    generic ``PUT /tools/{tool}/{tool_id}/comments`` route."""

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    comments_enabled: bool


class CommentUpdate(CommentBase):
    """Schema for updating a comment. Only content can be changed."""

    pass


class CommentRead(CommentBase):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    created_by: int
    task_id: Optional[int] = None
    document_id: Optional[int] = None
    queue_id: Optional[int] = None
    counter_group_id: Optional[int] = None
    calendar_id: Optional[int] = None
    dashboard_id: Optional[int] = None
    post_id: Optional[int] = None
    parent_comment_id: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    author: Optional[CommentAuthor] = None
    # The project this comment lives under: its own for a comment ON a
    # project, the task's for a task comment (filled by the service's
    # serializer).
    project_id: Optional[int] = None
    # Reactions ride along with the comment rather than costing a request per
    # row: a thread renders its chips from one list call. Empty until the
    # loader stamps them (see ``comments_service.attach_reactions``).
    reactions: list[ReactionGroup] = Field(default_factory=list)


class RecentActivityEntry(SanitizedBaseModel):
    # Same as the other read schemas here: a field with a default is still
    # always sent, so the generated client should see it as present rather than
    # optional.
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    comment_id: int
    content: RichTextStr
    created_at: datetime
    author: Optional[CommentAuthor] = None
    task_id: Optional[int] = None
    task_title: Optional[str] = None
    document_id: Optional[int] = None
    document_name: Optional[str] = None
    project_id: Optional[int] = None
    project_name: Optional[str] = None
    # What the comment is on, uniformly: "task" or a Tool value, with the
    # entity's id and display name. The task/document/project fields above
    # stay filled for those parents.
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    entity_name: Optional[str] = None
    # The initiative the commented-on entity lives in, so the row can link at
    # its real address. None when the parent is gone or unreadable (or the
    # parent is a guild-level calendar, which belongs to no initiative).
    initiative_id: Optional[int] = None
    # The same chips the thread shows. The feed is where a guild sees what is
    # going on, and a comment that drew six reactions reads differently from
    # one that drew none — so the row carries them rather than looking like a
    # quieter comment than it was.
    reactions: list[ReactionGroup] = Field(default_factory=list)
