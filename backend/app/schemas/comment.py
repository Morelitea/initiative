from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class CommentAuthor(BaseModel):
    id: int
    email: str
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    avatar_base64: Optional[str] = None

    class Config:
        from_attributes = True


class CommentBase(BaseModel):
    content: str

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Content is required")
        return normalized


class CommentCreate(CommentBase):
    task_id: Optional[int] = Field(default=None, gt=0)
    document_id: Optional[int] = Field(default=None, gt=0)
    parent_comment_id: Optional[int] = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_target(self) -> "CommentCreate":
        has_task = self.task_id is not None
        has_document = self.document_id is not None
        if has_task == has_document:
            raise ValueError("Provide exactly one of task_id or document_id")
        return self


class CommentUpdate(CommentBase):
    """Schema for updating a comment. Only content can be changed."""

    pass


class CommentRead(CommentBase):
    id: int
    author_id: int
    task_id: Optional[int] = None
    document_id: Optional[int] = None
    parent_comment_id: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    author: Optional[CommentAuthor] = None
    project_id: Optional[int] = None

    class Config:
        from_attributes = True


class RecentActivityEntry(BaseModel):
    comment_id: int
    content: str
    created_at: datetime
    author: Optional[CommentAuthor] = None
    task_id: Optional[int] = None
    task_title: Optional[str] = None
    document_id: Optional[int] = None
    document_title: Optional[str] = None
    project_id: Optional[int] = None
    project_name: Optional[str] = None


class MentionSuggestion(BaseModel):
    """A suggestion for mention autocomplete."""

    type: str  # "user", "task", "doc", "project"
    id: int
    display_text: str
    subtitle: Optional[str] = None  # email for users, project name for tasks
