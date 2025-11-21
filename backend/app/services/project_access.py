from collections.abc import Iterable, Sequence

from app.models.project import (
    DEFAULT_PROJECT_READ_ROLES,
    DEFAULT_PROJECT_WRITE_ROLES,
    Project,
    ProjectRole,
)
from app.models.user import UserRole


def _normalize_roles(values: Iterable[ProjectRole | str] | None, *, default: Sequence[str]) -> list[str]:
    if not values:
        return list(default)
    normalized: list[str] = []
    for value in values:
        role = ProjectRole(value) if isinstance(value, str) else value
        if role.value not in normalized:
            normalized.append(role.value)
    return normalized


def normalize_read_roles(values: Iterable[ProjectRole | str] | None) -> list[str]:
    return _normalize_roles(values, default=DEFAULT_PROJECT_READ_ROLES)


def normalize_write_roles(values: Iterable[ProjectRole | str] | None) -> list[str]:
    return _normalize_roles(values, default=DEFAULT_PROJECT_WRITE_ROLES)


def read_roles_set(project: Project) -> set[str]:
    values = project.read_roles or DEFAULT_PROJECT_READ_ROLES
    result: set[str] = set()
    for role in values:
        result.add(role if isinstance(role, str) else role.value)
    return result


def write_roles_set(project: Project) -> set[str]:
    values = project.write_roles or DEFAULT_PROJECT_WRITE_ROLES
    result: set[str] = set()
    for role in values:
        result.add(role if isinstance(role, str) else role.value)
    return result


def user_role_to_project_role(user_role: UserRole) -> ProjectRole:
    return ProjectRole(user_role.value)


def membership_has_access(project: Project, membership_role: ProjectRole, *, access: str) -> bool:
    if access == "write":
        return membership_role.value in write_roles_set(project)
    return membership_role.value in read_roles_set(project)
