"""Import all models for Alembic or metadata creation."""

from app.models.platform.announcement import (
    Announcement,
    AnnouncementImage,
    AnnouncementReadReceipt,
)
from app.models.platform.app_setting import AppSetting
from app.models.platform.app_setting_secret import AppSettingSecret
from app.models.platform.guild import Guild, GuildMembership, GuildInvite
from app.models.platform.guild_administration import GuildAdministration
from app.models.tenant.app_member_consent import AppMemberConsent
from app.models.tenant.app_placement import AppPlacement
from app.models.tenant.guild_app import GuildApp
from app.models.tenant.guild_app_user_connection import GuildAppUserConnection
from app.models.tenant.guild_setting import GuildSetting
from app.models.tenant.project import Project
from app.models.tenant.filter_preset import ProjectFilterPreset
from app.models.tenant.task import Task, TaskAssignee, TaskStatus
from app.models.tenant.initiative import Initiative, InitiativeMember
from app.models.platform.user import User
from app.models.platform.user_passkey import UserPasskey

# Registers ``MemberProfile`` in the mapper registry — the tenant
# relationships that name a person resolve it by name.
from app.models.platform.user_profile_view import MemberProfile
from app.models.platform.api_key import UserApiKey
from app.models.tenant.project_activity import ProjectFavorite
from app.models.tenant.project_order import ProjectOrder
from app.models.tenant.recent_view import RecentView
from app.models.tenant.comment import Comment
from app.models.tenant.document import (
    Document,
    DocumentFileVersion,
)
from app.models.platform.notification import Notification
from app.models.platform.oidc_claim_mapping import OIDCClaimMapping
from app.models.tenant.tag import Tag
from app.models.tenant.property import (
    DocumentPropertyValue,
    PropertyDefinition,
    TaskPropertyValue,
)
from app.models.tenant.queue import (
    Queue,
    QueueItem,
)
from app.models.tenant.calendar import Calendar
from app.models.tenant.calendar_event import (
    CalendarEvent,
    CalendarEventAttendee,
)
from app.models.tenant.event_outbox import EventOutbox
from app.models.tenant.app_event_outbox import AppEventOutbox
from app.models.tenant.app_hook_delivery import AppHookDelivery
from app.models.tenant.app_schedule_run import AppScheduleRun
from app.models.tenant.search_entry import SearchEntry
from app.models.tenant.event_reminder_dispatch import EventReminderDispatch
from app.models.tenant.dashboard import Dashboard
from app.models.tenant.post import Post
from app.models.tenant.gallery import (
    Gallery,
    GalleryImage,
    GalleryImageVersion,
)
from app.models.tenant.wiki import Wiki, WikiPage
from app.models.tenant.post_read import PostRead
from app.models.tenant.post_poll import PostPoll, PostPollOption, PostPollVote
from app.models.tenant.counter import (
    Counter,
    CounterGroup,
)
from app.models.tenant.upload import Upload
from app.models.platform.user_decoration import UserDecoration
from app.models.platform.profile_favorite import ProfileFavorite
from app.models.platform.user_view_preference import UserViewPreference
from app.models.platform.user_dm_settings import UserDmSettings
from app.models.platform.user_notification_prefs import UserNotificationPrefs
from app.models.platform.email_outbox import EmailOutboxItem
from app.models.platform.legal_acceptance import LegalAcceptance
from app.models.platform.user_dm_guild_optout import UserDmGuildOptout
from app.models.platform.contact_grant import ContactGrant
from app.models.platform.user_ignore import UserIgnore
from app.models.platform.dm_device import DmDevice
from app.models.platform.dm_one_time_key import DmOneTimeKey
from app.models.platform.dm_conversation import (
    DmConversation,
    DmConversationMember,
)
from app.models.platform.dm_queue import DmQueueItem
from app.models.platform.access_grant import AccessGrant
from app.models.platform.auth_provider import AuthProvider
from app.models.platform.auth_provider_secret import AuthProviderSecret
from app.models.platform.auth_session import AuthSession
from app.models.platform.federated_identity import FederatedIdentity
from app.models.platform.federated_identity_secret import FederatedIdentitySecret
from app.models.platform.identity_ref import IdentityRef
from app.models.platform.guild_auth_policy import GuildAuthPolicy
from app.models.platform.guild_provider_connection import GuildProviderConnection
from app.models.platform.platform_provider_default import PlatformProviderDefault
from app.models.platform.guild_image import GuildImage
from app.models.platform.user_email import UserEmail
from app.models.platform.user_email_assertion import UserEmailAssertion
from app.models.platform.sign_in_lock import SignInLock
from app.models.platform.user_totp import UserTotp
from app.models.platform.user_totp_secret import UserTotpSecret
from app.models.platform.mfa_recovery_code import MfaRecoveryCode
from app.models.platform.auth_challenge import AuthChallenge
from app.models.platform.user_token import UserToken
from app.models.platform.push_token import PushToken
from app.models.platform.billing import BillingEventLog, BillingJti
from app.models.tenant.task_assignment_digest import TaskAssignmentDigestItem
from app.models.tenant.reaction import Reaction
from app.models.tenant.reaction_digest import ReactionDigestItem
from app.models.tenant.relationship import EntityRelationship
from app.models.tenant.webhook_delivery import WebhookDelivery
from app.models.tenant.webhook_subscription import WebhookSubscription
from app.models.tenant.intake import IntakeBinding, IntakeCase
from app.models.tenant.moderation import ModerationReport, ModerationReportReporter
from app.models.tenant.resource_grant import ResourceGrant
from app.models.tenant.export_job import ExportJob
from app.models.tenant.import_job import ImportJob
from app.models.platform.marketplace_registry import (
    MarketplaceMedia,
    MarketplaceRegistryStatus,
    MarketplaceTufMetadata,
)
from app.models.platform.ai_connection import PlatformAIConnection
from app.models.platform.app_service_registration import AppServiceRegistration
from app.models.platform.publisher import Publisher
from app.models.platform.app_assertion_jti import AppAssertionJti
from app.models.platform.app_install import AppInstall
from app.models.tenant.ai_connection import GuildAIConnection
from app.models.tenant.ai_member_key import GuildAIMemberKey
from app.models.tenant.ai_member_pref import GuildAIMemberPref

__all__ = [
    "Announcement",
    "AnnouncementImage",
    "AnnouncementReadReceipt",
    "User",
    "UserPasskey",
    "MemberProfile",
    "AccessGrant",
    "AuthProvider",
    "AuthProviderSecret",
    "AuthSession",
    "UserEmail",
    "UserEmailAssertion",
    "SignInLock",
    "FederatedIdentity",
    "FederatedIdentitySecret",
    "IdentityRef",
    "GuildAuthPolicy",
    "GuildProviderConnection",
    "PlatformProviderDefault",
    "ResourceGrant",
    "ExportJob",
    "ImportJob",
    "Project",
    "Task",
    "TaskAssignee",
    "TaskStatus",
    "ProjectFilterPreset",
    "AppSetting",
    "AppSettingSecret",
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
    "ProjectOrder",
    "RecentView",
    "Comment",
    "Document",
    "DocumentFileVersion",
    "Notification",
    "OIDCClaimMapping",
    "Tag",
    "PropertyDefinition",
    "DocumentPropertyValue",
    "TaskPropertyValue",
    "Queue",
    "QueueItem",
    "Calendar",
    "CalendarEvent",
    "CalendarEventAttendee",
    "EventOutbox",
    "AppEventOutbox",
    "AppHookDelivery",
    "AppScheduleRun",
    "SearchEntry",
    "EventReminderDispatch",
    "Dashboard",
    "Post",
    "Gallery",
    "GalleryImage",
    "GalleryImageVersion",
    "Wiki",
    "WikiPage",
    "PostRead",
    "PostPoll",
    "PostPollOption",
    "PostPollVote",
    "Counter",
    "CounterGroup",
    "Upload",
    "UserDecoration",
    "ProfileFavorite",
    "LegalAcceptance",
    "UserViewPreference",
    "UserDmSettings",
    "UserNotificationPrefs",
    "EmailOutboxItem",
    "UserDmGuildOptout",
    "ContactGrant",
    "UserIgnore",
    "DmDevice",
    "DmOneTimeKey",
    "DmConversation",
    "DmConversationMember",
    "DmQueueItem",
    "UserToken",
    "PushToken",
    "BillingEventLog",
    "BillingJti",
    "TaskAssignmentDigestItem",
    "Reaction",
    "ReactionDigestItem",
    "EntityRelationship",
    "WebhookDelivery",
    "WebhookSubscription",
    "IntakeBinding",
    "IntakeCase",
    "ModerationReport",
    "ModerationReportReporter",
    "AppServiceRegistration",
    "Publisher",
    "AppAssertionJti",
    "AppInstall",
    "MarketplaceMedia",
    "MarketplaceRegistryStatus",
    "MarketplaceTufMetadata",
    "PlatformAIConnection",
    "GuildAIConnection",
    "GuildAIMemberKey",
    "GuildAIMemberPref",
    "AppMemberConsent",
    "AppPlacement",
    "GuildApp",
    "GuildAppUserConnection",
    "UserTotp",
    "UserTotpSecret",
    "MfaRecoveryCode",
    "AuthChallenge",
]
