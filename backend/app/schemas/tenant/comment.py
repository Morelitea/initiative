from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import ConfigDict, Field, field_validator, model_validator

from app.schemas.base import RawTextStr, RichTextStr, SanitizedBaseModel


class MentionEntityType(str, Enum):
    user = "user"
    task = "task"
    doc = "doc"
    project = "project"


class CommentAuthor(SanitizedBaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    avatar_base64: Optional[RawTextStr] = None


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
)


class CommentCreate(CommentBase):
    task_id: Optional[int] = Field(default=None, gt=0)
    document_id: Optional[int] = Field(default=None, gt=0)
    project_id: Optional[int] = Field(default=None, gt=0)
    queue_id: Optional[int] = Field(default=None, gt=0)
    counter_group_id: Optional[int] = Field(default=None, gt=0)
    calendar_id: Optional[int] = Field(default=None, gt=0)
    dashboard_id: Optional[int] = Field(default=None, gt=0)
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
    parent_comment_id: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    author: Optional[CommentAuthor] = None
    # The project this comment lives under: its own for a comment ON a
    # project, the task's for a task comment (filled by the service's
    # serializer).
    project_id: Optional[int] = None


class RecentActivityEntry(SanitizedBaseModel):
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


class MentionSuggestion(SanitizedBaseModel):
    """A suggestion for mention autocomplete."""

    type: MentionEntityType
    id: int
    display_text: str
    subtitle: Optional[str] = None  # email for users, project name for tasks
    # Populated for ``user`` suggestions so the picker can render a face
    # (parity with the member typeaheads); ``None`` for non-user entities.
    avatar_url: Optional[str] = None
    avatar_base64: Optional[RawTextStr] = None


class MentionSuggestionListResponse(SanitizedBaseModel):
    """Paginated envelope for mention search — same shape as the member search
    responses (``UserSummaryListResponse`` et al.)."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: list[MentionSuggestion]
    total_count: int
    page: int
    page_size: int
    has_next: bool
    has_prev: bool
