"""Import all models for Alembic or metadata creation."""

from app.models.platform.app_setting import AppSetting
from app.models.platform.guild import Guild, GuildMembership, GuildInvite
from app.models.tenant.guild_setting import GuildSetting
from app.models.tenant.project import Project
from app.models.tenant.task import Task, TaskAssignee, TaskStatus, Subtask
from app.models.tenant.initiative import Initiative, InitiativeMember
from app.models.platform.user import User
from app.models.platform.api_key import UserApiKey
from app.models.tenant.project_activity import ProjectFavorite
from app.models.tenant.recent_view import RecentView
from app.models.tenant.comment import Comment
from app.models.tenant.document import (
    Document,
    DocumentFileVersion,
    ProjectDocument,
    DocumentLink,
)
from app.models.platform.notification import Notification
from app.models.platform.oidc_claim_mapping import OIDCClaimMapping
from app.models.tenant.tag import Tag, TaskTag, ProjectTag, DocumentTag
from app.models.tenant.property import (
    DocumentPropertyValue,
    PropertyDefinition,
    TaskPropertyValue,
)
from app.models.tenant.queue import (
    Queue,
    QueueItem,
    QueueItemTag,
    QueueItemDocument,
    QueueItemTask,
)
from app.models.tenant.calendar_event import (
    CalendarEvent,
    CalendarEventAttendee,
    CalendarEventTag,
    CalendarEventDocument,
)
from app.models.tenant.event_reminder_dispatch import EventReminderDispatch
from app.models.tenant.counter import (
    Counter,
    CounterGroup,
)
from app.models.tenant.upload import Upload
from app.models.platform.user_view_preference import UserViewPreference
from app.models.platform.access_grant import AccessGrant
from app.models.platform.user_token import UserToken
from app.models.platform.push_token import PushToken
from app.models.platform.auto_delegation_jti import AutoDelegationJti
from app.models.tenant.task_assignment_digest import TaskAssignmentDigestItem
from app.models.tenant.webhook_subscription import WebhookSubscription
from app.models.tenant.resource_grant import ResourceGrant
from app.models.tenant.advanced_tool import AdvancedTool

__all__ = [
    "User",
    "AccessGrant",
    "ResourceGrant",
    "AdvancedTool",
    "Project",
    "Task",
    "TaskAssignee",
    "TaskStatus",
    "Subtask",
    "AppSetting",
    "Guild",
    "GuildMembership",
    "GuildInvite",
    "GuildSetting",
    "Initiative",
    "InitiativeMember",
    "UserApiKey",
    "ProjectFavorite",
    "RecentView",
    "Comment",
    "Document",
    "DocumentFileVersion",
    "ProjectDocument",
    "DocumentLink",
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
    "QueueItemDocument",
    "QueueItemTask",
    "CalendarEvent",
    "CalendarEventAttendee",
    "CalendarEventTag",
    "CalendarEventDocument",
    "EventReminderDispatch",
    "Counter",
    "CounterGroup",
    "Upload",
    "UserViewPreference",
    "UserToken",
    "PushToken",
    "AutoDelegationJti",
    "TaskAssignmentDigestItem",
    "WebhookSubscription",
]
