"""Import all models for Alembic or metadata creation."""

from app.models.app_setting import AppSetting
from app.models.guild import Guild, GuildMembership, GuildInvite
from app.models.guild_setting import GuildSetting
from app.models.project import Project, ProjectPermission, ProjectRolePermission
from app.models.task import Task, TaskAssignee, TaskStatus, Subtask
from app.models.initiative import Initiative, InitiativeMember
from app.models.user import User
from app.models.api_key import AdminApiKey
from app.models.project_activity import ProjectFavorite
from app.models.recent_view import RecentView
from app.models.comment import Comment
from app.models.document import Document, DocumentFileVersion, DocumentPermission, DocumentRolePermission, ProjectDocument, DocumentLink
from app.models.notification import Notification
from app.models.oidc_claim_mapping import OIDCClaimMapping
from app.models.tag import Tag, TaskTag, ProjectTag, DocumentTag
from app.models.property import (
    DocumentPropertyValue,
    PropertyDefinition,
    TaskPropertyValue,
)
from app.models.queue import Queue, QueueItem, QueueItemTag, QueuePermission, QueueRolePermission, QueueItemDocument, QueueItemTask
from app.models.calendar_event import CalendarEvent, CalendarEventAttendee, CalendarEventTag, CalendarEventDocument
from app.models.event_reminder_dispatch import EventReminderDispatch
from app.models.counter import Counter, CounterGroup, CounterGroupPermission, CounterGroupRolePermission
from app.models.upload import Upload
from app.models.user_view_preference import UserViewPreference
from app.models.access_grant import AccessGrant

__all__ = [
    "User",
    "AccessGrant",
    "Project",
    "Task",
    "TaskAssignee",
    "TaskStatus",
    "Subtask",
    "ProjectPermission",
    "AppSetting",
    "Guild",
    "GuildMembership",
    "GuildInvite",
    "GuildSetting",
    "Initiative",
    "InitiativeMember",
    "AdminApiKey",
    "ProjectFavorite",
    "RecentView",
    "Comment",
    "Document",
    "DocumentFileVersion",
    "DocumentPermission",
    "DocumentRolePermission",
    "ProjectDocument",
    "DocumentLink",
    "ProjectRolePermission",
    "Notification",
    "OIDCClaimMapping",
    "Tag",
    "TaskTag",
    "ProjectTag",
    "DocumentTag",
    "PropertyDefinition",
    "DocumentPropertyValue",
    "TaskPropertyValue",
    "Queue",
    "QueueItem",
    "QueueItemTag",
    "QueuePermission",
    "QueueRolePermission",
    "QueueItemDocument",
    "QueueItemTask",
    "CalendarEvent",
    "CalendarEventAttendee",
    "CalendarEventTag",
    "CalendarEventDocument",
    "EventReminderDispatch",
    "Counter",
    "CounterGroup",
    "CounterGroupPermission",
    "CounterGroupRolePermission",
    "Upload",
    "UserViewPreference",
]
