"""Import all models for Alembic or metadata creation."""

from app.models.platform.announcement import (
    Announcement,
    AnnouncementImage,
    AnnouncementReadReceipt,
)
from app.models.platform.app_setting import AppSetting
from app.models.platform.guild import Guild, GuildMembership, GuildInvite
from app.models.platform.guild_administration import GuildAdministration
from app.models.tenant.guild_app import GuildApp
from app.models.tenant.guild_app_subject import GuildAppSubject
from app.models.tenant.guild_app_user_connection import GuildAppUserConnection
from app.models.tenant.guild_app_user_delegation import GuildAppUserDelegation
from app.models.tenant.guild_setting import GuildSetting
from app.models.tenant.project import Project
from app.models.tenant.filter_preset import ProjectFilterPreset
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
from app.models.tenant.calendar import Calendar, CalendarTag
from app.models.tenant.calendar_event import (
    CalendarEvent,
    CalendarEventAttendee,
    CalendarEventTag,
    CalendarEventDocument,
)
from app.models.tenant.event_outbox import EventOutbox
from app.models.tenant.search_entry import SearchEntry
from app.models.tenant.event_reminder_dispatch import EventReminderDispatch
from app.models.tenant.dashboard import Dashboard, DashboardTag
from app.models.tenant.counter import (
    Counter,
    CounterGroup,
)
from app.models.tenant.upload import Upload
from app.models.platform.user_decoration import UserDecoration
from app.models.platform.profile_favorite import ProfileFavorite
from app.models.platform.user_view_preference import UserViewPreference
from app.models.platform.access_grant import AccessGrant
from app.models.platform.auth_provider import AuthProvider
from app.models.platform.auth_provider_secret import AuthProviderSecret
from app.models.platform.auth_session import AuthSession
from app.models.platform.federated_identity import FederatedIdentity
from app.models.platform.federated_identity_secret import FederatedIdentitySecret
from app.models.platform.guild_auth_policy import GuildAuthPolicy
from app.models.platform.guild_image import GuildImage
from app.models.platform.audit_event import AuditEvent  # noqa: F401
from app.models.platform.user_token import UserToken
from app.models.platform.push_token import PushToken
from app.models.platform.auto_delegation_jti import AutoDelegationJti
from app.models.platform.billing import BillingEventLog, BillingJti
from app.models.tenant.task_assignment_digest import TaskAssignmentDigestItem
from app.models.tenant.reaction import Reaction
from app.models.tenant.reaction_digest import ReactionDigestItem
from app.models.tenant.webhook_delivery import WebhookDelivery
from app.models.tenant.webhook_subscription import WebhookSubscription
from app.models.tenant.resource_grant import ResourceGrant
from app.models.tenant.export_job import ExportJob
from app.models.tenant.import_job import ImportJob
from app.models.platform.marketplace_registry import (
    MarketplaceMedia,
    MarketplaceRegistryState,
)
from app.models.platform.ai_connection import PlatformAIConnection
from app.models.platform.app_service_registration import AppServiceRegistration
from app.models.platform.app_service_nonce import AppServiceNonce
from app.models.tenant.ai_connection import GuildAIConnection
from app.models.tenant.ai_member_key import GuildAIMemberKey
from app.models.tenant.ai_member_pref import GuildAIMemberPref

__all__ = [
    "Announcement",
    "AnnouncementImage",
    "AnnouncementReadReceipt",
    "User",
    "AccessGrant",
    "AuthProvider",
    "AuthProviderSecret",
    "AuthSession",
    "FederatedIdentity",
    "FederatedIdentitySecret",
    "GuildAuthPolicy",
    "ResourceGrant",
    "ExportJob",
    "ImportJob",
    "Project",
    "Task",
    "TaskAssignee",
    "TaskStatus",
    "ProjectFilterPreset",
    "Subtask",
    "AppSetting",
    "Guild",
    "GuildAdministration",
    "GuildImage",
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
    "Calendar",
    "CalendarTag",
    "CalendarEvent",
    "CalendarEventAttendee",
    "CalendarEventTag",
    "CalendarEventDocument",
    "EventOutbox",
    "SearchEntry",
    "EventReminderDispatch",
    "Dashboard",
    "DashboardTag",
    "Counter",
    "CounterGroup",
    "Upload",
    "UserDecoration",
    "ProfileFavorite",
    "UserViewPreference",
    "UserToken",
    "PushToken",
    "AutoDelegationJti",
    "BillingEventLog",
    "BillingJti",
    "TaskAssignmentDigestItem",
    "Reaction",
    "ReactionDigestItem",
    "WebhookDelivery",
    "WebhookSubscription",
    "AppServiceRegistration",
    "AppServiceNonce",
    "MarketplaceMedia",
    "MarketplaceRegistryState",
    "PlatformAIConnection",
    "GuildAIConnection",
    "GuildAIMemberKey",
    "GuildAIMemberPref",
    "GuildApp",
    "GuildAppSubject",
    "GuildAppUserConnection",
    "GuildAppUserDelegation",
]
