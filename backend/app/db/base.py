"""Import all models for Alembic or metadata creation."""

from app.models.app_setting import AppSetting
from app.models.guild import Guild, GuildMembership, GuildInvite
from app.models.guild_setting import GuildSetting
from app.models.project import Project, ProjectPermission, ProjectRolePermission
from app.models.task import Task, TaskAssignee, TaskStatus, Subtask
from app.models.initiative import Initiative, InitiativeMember
from app.models.user import User
from app.models.api_key import AdminApiKey
from app.models.project_activity import ProjectFavorite, RecentProjectView
from app.models.comment import Comment
from app.models.document import Document, DocumentPermission, DocumentRolePermission, ProjectDocument, DocumentLink
from app.models.notification import Notification
from app.models.oidc_claim_mapping import OIDCClaimMapping
from app.models.tag import Tag, TaskTag, ProjectTag, DocumentTag
from app.models.upload import Upload

__all__ = [
    "User",
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
    "RecentProjectView",
    "Comment",
    "Document",
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
    "Upload",
]
