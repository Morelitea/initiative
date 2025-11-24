"""Import all models for Alembic or metadata creation."""

from app.models.app_setting import AppSetting
from app.models.project import Project, ProjectMember
from app.models.task import Task, TaskAssignee
from app.models.initiative import Initiative, InitiativeMember
from app.models.user import User
from app.models.api_key import AdminApiKey
from app.models.project_activity import ProjectFavorite, RecentProjectView

__all__ = [
    "User",
    "Project",
    "Task",
    "TaskAssignee",
    "ProjectMember",
    "AppSetting",
    "Initiative",
    "InitiativeMember",
    "AdminApiKey",
    "ProjectFavorite",
    "RecentProjectView",
]
