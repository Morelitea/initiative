from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from sqlalchemy import Column, DateTime, JSON, String
from sqlmodel import Field, Index, SQLModel


class NotificationType(str, Enum):
    task_assignment = "task_assignment"
    overdue_tasks = "overdue_tasks"
    initiative_added = "initiative_added"
    initiative_join_requested = "initiative_join_requested"
    initiative_join_approved = "initiative_join_approved"
    initiative_join_denied = "initiative_join_denied"
    project_added = "project_added"
    user_pending_approval = "user_pending_approval"
    mention = "mention"
    comment_on_task = "comment_on_task"
    comment_on_resource = "comment_on_resource"
    comment_reply = "comment_reply"
    comment_reaction = "comment_reaction"
    access_grant_requested = "access_grant_requested"
    access_grant_approved = "access_grant_approved"
    access_grant_denied = "access_grant_denied"
    access_grant_revoked = "access_grant_revoked"
    event_invitation = "event_invitation"
    event_updated = "event_updated"
    event_cancelled = "event_cancelled"
    event_rsvp = "event_rsvp"
    event_reminder = "event_reminder"
    export_ready = "export_ready"
    export_failed = "export_failed"
    import_ready = "import_ready"
    import_failed = "import_failed"
    avatar_removed = "avatar_removed"
    username_changed = "username_changed"
    account_suspended = "account_suspended"
    account_unsuspended = "account_unsuspended"
    connection_requested = "connection_requested"
    connection_accepted = "connection_accepted"
    message_request_received = "message_request_received"
    message_request_accepted = "message_request_accepted"
    #: One rolled-up line per conversation with unread activity. It names the
    #: sender and counts the messages; it never carries one.
    direct_message = "direct_message"


class Notification(SQLModel, table=True):
    __tablename__ = "notifications"
    __table_args__ = (
        # The inbox query is always "my notifications, unread first", so the
        # composite carries it; a bare ``user_id`` index would be a prefix of
        # this one.
        Index("ix_notifications_user_read", "user_id", "read_at"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", ondelete="CASCADE", nullable=False)
    type: NotificationType = Field(
        sa_column=Column(String(64), nullable=False),
        default=NotificationType.task_assignment,
    )
    data: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, server_default="{}"),
    )
    read_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
