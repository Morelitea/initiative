"""Import all models for Alembic or metadata creation."""

from app.models.app_setting import AppSetting
from app.models.guild import Guild, GuildMembership, GuildInvite
from app.models.guild_setting import GuildSetting
from app.models.project import Project, ProjectPermission
from app.models.task import Task, TaskAssignee, Subtask
from app.models.initiative import Initiative, InitiativeMember
from app.models.user import User
from app.models.api_key import AdminApiKey
from app.models.project_activity import ProjectFavorite, RecentProjectView
from app.models.comment import Comment
from app.models.document import Document
from app.models.notification import Notification

__all__ = [
    "User",
    "Project",
    "Task",
    "TaskAssignee",
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
    "Notification",
]
