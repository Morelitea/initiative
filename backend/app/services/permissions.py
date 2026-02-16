"""Discretionary Access Control (DAC) — project and document permissions.

This module handles the application-level permission layer for projects
and documents.  Unlike the mandatory RLS layer (see ``rls.py``) which is
enforced by PostgreSQL, DAC permissions are filtering tools applied in
application code to determine what a user can read, write, or own.

Security layers managed here:
  - Project permissions — ``ProjectPermission`` + ``ProjectRolePermission``
  - Document permissions — ``DocumentPermission`` + ``DocumentRolePermission``
  - Visibility subqueries — reusable UNION subqueries for listing endpoints
  - Access enforcement — ``require_project_access`` / ``require_document_access``

The complementary mandatory access control layer (guild isolation,
initiative membership, initiative RBAC) lives in ``rls.py``.
"""

from enum import Enum
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import inspect
from sqlmodel import select

from app.models.project import (
    Project,
    ProjectPermission,
    ProjectPermissionLevel,
    ProjectRolePermission,
)
from app.models.document import (
    Document,
    DocumentPermission,
    DocumentPermissionLevel,
    DocumentRolePermission,
)
from app.models.initiative import InitiativeMember
from app.models.user import User
from app.core.messages import ProjectMessages, DocumentMessages


# ---------------------------------------------------------------------------
# Generic helpers (work with both project and document permission enums)
# ---------------------------------------------------------------------------

def _get_user_role_ids(
    memberships: list[Any] | None,
    user_id: int,
) -> set[int]:
    """Extract the set of role IDs a user holds in an initiative's memberships."""
    if not memberships:
        return set()
    return {
        m.role_id
        for m in memberships
        if m.user_id == user_id and m.role_id is not None
    }


def role_permission_level(
    role_permissions: list[Any] | None,
    memberships: list[Any] | None,
    user_id: int,
    level_order: dict[Enum, int],
) -> Enum | None:
    """Get the highest role-based permission level for a user.

    Works with both ProjectPermissionLevel and DocumentPermissionLevel enums.

    Args:
        role_permissions: The role permission records (ProjectRolePermission
            or DocumentRolePermission).
        memberships: The initiative memberships (Initiative.memberships).
        user_id: The user to check.
        level_order: Mapping from permission level enum to numeric rank
            (e.g. {read: 0, write: 1, owner: 2}).

    Returns:
        The highest matching permission level, or None.
    """
    if not role_permissions:
        return None
    user_role_ids = _get_user_role_ids(memberships, user_id)
    if not user_role_ids:
        return None

    best: Enum | None = None
    for rp in role_permissions:
        if rp.initiative_role_id in user_role_ids:
            if best is None or level_order.get(rp.level, 0) > level_order.get(best, 0):
                best = rp.level
    return best


def effective_permission_level(
    user_level: Enum | None,
    role_level: Enum | None,
    level_order: dict[Enum, int],
) -> Enum | None:
    """Return the higher of two permission levels (MAX behaviour).

    Args:
        user_level: The user-specific permission level (may be None).
        role_level: The role-based permission level (may be None).
        level_order: Mapping from permission level enum to numeric rank.

    Returns:
        The higher of the two levels, or None if both are None.
    """
    if user_level is None:
        return role_level
    if role_level is None:
        return user_level
    if level_order.get(role_level, 0) > level_order.get(user_level, 0):
        return role_level
    return user_level


# ── Convenience constants ────────────────────────────────────────

PROJECT_LEVEL_ORDER: dict[ProjectPermissionLevel, int] = {
    ProjectPermissionLevel.read: 0,
    ProjectPermissionLevel.write: 1,
    ProjectPermissionLevel.owner: 2,
}

DOCUMENT_LEVEL_ORDER: dict[DocumentPermissionLevel, int] = {
    DocumentPermissionLevel.read: 0,
    DocumentPermissionLevel.write: 1,
    DocumentPermissionLevel.owner: 2,
}


# ── Visibility subqueries ────────────────────────────────────────
# Reusable subqueries that return IDs of entities a user can see.
# These eliminate the duplicated UNION pattern across endpoints.

def visible_project_ids_subquery(user_id: int):
    """Return a subquery of project IDs the user can access.

    Combines user-specific ``ProjectPermission`` rows with role-based
    ``ProjectRolePermission`` rows matched via ``InitiativeMember``.
    """
    user_perm_subq = (
        select(ProjectPermission.project_id)
        .where(ProjectPermission.user_id == user_id)
    )
    role_perm_subq = (
        select(ProjectRolePermission.project_id)
        .join(
            InitiativeMember,
            (InitiativeMember.role_id == ProjectRolePermission.initiative_role_id)
            & (InitiativeMember.user_id == user_id),
        )
    )
    return user_perm_subq.union(role_perm_subq)


def visible_document_ids_subquery(user_id: int):
    """Return a subquery of document IDs the user can access.

    Combines user-specific ``DocumentPermission`` rows with role-based
    ``DocumentRolePermission`` rows matched via ``InitiativeMember``.
    """
    user_perm_subq = (
        select(DocumentPermission.document_id)
        .where(DocumentPermission.user_id == user_id)
    )
    role_perm_subq = (
        select(DocumentRolePermission.document_id)
        .join(
            InitiativeMember,
            (InitiativeMember.role_id == DocumentRolePermission.initiative_role_id)
            & (InitiativeMember.user_id == user_id),
        )
    )
    return user_perm_subq.union(role_perm_subq)


# ── High-level helpers for projects ─────────────────────────────

def user_permission_from_project(
    project: Any,
    user_id: int,
) -> Any | None:
    """Find the user's explicit ProjectPermission from eagerly-loaded list."""
    permissions = getattr(project, "permissions", None)
    if not permissions:
        return None
    for permission in permissions:
        if permission.user_id == user_id:
            return permission
    return None


def project_role_permission_level(
    project: Any,
    user_id: int,
) -> ProjectPermissionLevel | None:
    """Get the highest role-based project permission for a user.

    Reads from eagerly-loaded ``project.role_permissions`` and
    ``project.initiative.memberships``.
    """
    role_perms = getattr(project, "role_permissions", None)
    initiative = getattr(project, "initiative", None)
    memberships = getattr(initiative, "memberships", None) if initiative else None
    return role_permission_level(role_perms, memberships, user_id, PROJECT_LEVEL_ORDER)


def effective_project_permission(
    user_level: ProjectPermissionLevel | None,
    role_level: ProjectPermissionLevel | None,
) -> ProjectPermissionLevel | None:
    """MAX of a user-specific and role-based project permission level."""
    return effective_permission_level(user_level, role_level, PROJECT_LEVEL_ORDER)


def compute_project_permission(
    project: Project,
    user_id: int,
    *,
    is_guild_admin: bool = False,
) -> str | None:
    """Compute the effective permission level string for a user on a project.

    Uses eagerly-loaded relationships (permissions, role_permissions,
    initiative.memberships) so no DB queries are needed.
    Guild admins are treated as having owner-level access.
    """
    if is_guild_admin:
        return ProjectPermissionLevel.owner.value

    user_perm = user_permission_from_project(project, user_id)
    user_level = user_perm.level if user_perm else None
    role_level = project_role_permission_level(project, user_id)
    effective = effective_project_permission(user_level, role_level)
    return effective.value if effective else None


def _effective_project_level(
    project: Project,
    user_id: int,
) -> ProjectPermissionLevel | None:
    """Internal: compute effective project permission level enum."""
    user_perm = user_permission_from_project(project, user_id)
    user_level = user_perm.level if user_perm else None
    role_level = project_role_permission_level(project, user_id)
    return effective_project_permission(user_level, role_level)


def require_project_access(
    project: Project,
    user: User,
    *,
    access: str = "read",
    require_owner: bool = False,
) -> None:
    """Raise HTTPException if user lacks required project access.

    DAC: Access granted through explicit ProjectPermission or role-based
    permission.  Effective level = MAX(user-specific, role-based).
    """
    effective = _effective_project_level(project, user.id)

    if require_owner:
        if effective != ProjectPermissionLevel.owner:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=ProjectMessages.OWNER_REQUIRED,
            )
        return

    if effective is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ProjectMessages.NO_ACCESS,
        )

    if access == "write" and effective == ProjectPermissionLevel.read:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ProjectMessages.WRITE_ACCESS_REQUIRED,
        )


def has_project_write_access(
    project: Project,
    user: User,
) -> bool:
    """Check if user has write access (synchronous, for filtering)."""
    effective = _effective_project_level(project, user.id)
    return effective is not None and effective in (
        ProjectPermissionLevel.owner,
        ProjectPermissionLevel.write,
    )


# ── High-level helpers for documents ─────────────────────────────

def document_role_permission_level(
    document: Any,
    user_id: int,
) -> DocumentPermissionLevel | None:
    """Get the highest role-based document permission for a user.

    Reads from eagerly-loaded ``document.role_permissions`` and
    ``document.initiative.memberships``.
    """
    role_perms = getattr(document, "role_permissions", None)
    initiative = getattr(document, "initiative", None)
    memberships = getattr(initiative, "memberships", None) if initiative else None
    return role_permission_level(role_perms, memberships, user_id, DOCUMENT_LEVEL_ORDER)


def effective_document_permission(
    user_level: DocumentPermissionLevel | None,
    role_level: DocumentPermissionLevel | None,
) -> DocumentPermissionLevel | None:
    """MAX of a user-specific and role-based document permission level."""
    return effective_permission_level(user_level, role_level, DOCUMENT_LEVEL_ORDER)


def _get_loaded_document_permissions(document: Document) -> list[DocumentPermission]:
    """Get permissions from document, asserting they were eagerly loaded."""
    state = inspect(document)
    if "permissions" not in state.dict or state.attrs.permissions.loaded_value is None:
        raise RuntimeError(
            f"Document {document.id} permissions not loaded. "
            "Use selectinload(Document.permissions) in query."
        )
    return document.permissions or []


def compute_document_permission(
    document: Document,
    user_id: int,
    *,
    is_guild_admin: bool = False,
) -> str | None:
    """Compute the effective permission level string for a user on a document.

    Uses eagerly-loaded relationships (permissions, role_permissions,
    initiative.memberships) so no DB queries are needed.
    Guild admins are treated as having owner-level access.
    """
    if is_guild_admin:
        return DocumentPermissionLevel.owner.value

    user_level: DocumentPermissionLevel | None = None
    permissions = getattr(document, "permissions", None) or []
    for perm in permissions:
        if perm.user_id == user_id:
            user_level = perm.level
            break

    role_level = document_role_permission_level(document, user_id)
    effective = effective_document_permission(user_level, role_level)
    return effective.value if effective else None


def _effective_document_level(
    document: Document,
    user: User,
) -> DocumentPermissionLevel | None:
    """Internal: compute effective document permission level enum."""
    permissions = _get_loaded_document_permissions(document)
    user_level: DocumentPermissionLevel | None = None
    for perm in permissions:
        if perm.user_id == user.id:
            user_level = perm.level
            break
    role_level = document_role_permission_level(document, user.id)
    return effective_document_permission(user_level, role_level)


def require_document_access(
    document: Document,
    user: User,
    *,
    access: str = "read",
    require_owner: bool = False,
) -> None:
    """Raise HTTPException if user lacks required document access.

    DAC: Access granted through explicit DocumentPermission or role-based
    permission.  Effective level = MAX(user-specific, role-based).
    """
    effective = _effective_document_level(document, user)

    if require_owner:
        if effective != DocumentPermissionLevel.owner:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=DocumentMessages.OWNER_REQUIRED,
            )
        return

    if effective is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=DocumentMessages.NO_ACCESS,
        )

    if access == "write" and effective == DocumentPermissionLevel.read:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=DocumentMessages.WRITE_ACCESS_REQUIRED,
        )


def get_document_permission(document: Document, user_id: int) -> DocumentPermission | None:
    """Get a user's permission for a document from the loaded permissions."""
    return next(
        (p for p in _get_loaded_document_permissions(document) if p.user_id == user_id),
        None,
    )
