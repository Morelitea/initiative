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
from typing import Any, TypeVar

from fastapi import HTTPException, status
from sqlalchemy import inspect
from sqlmodel import select

from app.core.capabilities import Capability, user_has_capability
from app.core.pam_context import active_grant_level, grant_satisfies, has_active_grant
from app.core.role_context import active_guild_role
from app.services.membership import guild_member_clause, initiative_scope_clause

from app.models.guild import GuildRole
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

# Permission-level enum the generic helpers operate on. Bound to Enum so each
# caller's concrete level type (ProjectPermissionLevel, DocumentPermissionLevel,
# QueuePermissionLevel) flows through to the return type.
PermLevel = TypeVar("PermLevel", bound=Enum)


def _get_user_role_ids(
    memberships: list[Any] | None,
    user_id: int,
) -> set[int]:
    """Extract the set of role IDs a user holds in an initiative's memberships."""
    if not memberships:
        return set()
    return {
        m.role_id for m in memberships if m.user_id == user_id and m.role_id is not None
    }


def role_permission_level(
    role_permissions: list[Any] | None,
    memberships: list[Any] | None,
    user_id: int,
    level_order: dict[PermLevel, int],
) -> PermLevel | None:
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

    best: PermLevel | None = None
    for rp in role_permissions:
        if rp.initiative_role_id in user_role_ids:
            if best is None or level_order.get(rp.level, 0) > level_order.get(best, 0):
                best = rp.level
    return best


def effective_permission_level(
    user_level: PermLevel | None,
    role_level: PermLevel | None,
    level_order: dict[PermLevel, int],
) -> PermLevel | None:
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

# Where a level string sits on the shared read < write < owner ladder.
_LEVEL_RANK = {"read": 0, "write": 1, "owner": 2}


def lift_level_for_grant(dac_level: str | None, guild_id: int | None) -> str | None:
    """Raise an effective permission string to the active PAM grant's level.

    The ``my_permission_level`` surfaced to the client drives whether edit
    affordances render. A PAM grantee has no permission rows, so DAC alone
    reports read-only and the UI hides editing even when a ``read_write`` grant
    would let the write through (RLS + ``require_*_access`` already honor it).
    A read grant implies ``read``; a read_write grant implies ``write``; a grant
    never confers ``owner``. Returns the higher of the DAC and grant levels.

    Shared by projects, documents, queues, and counter groups so the level the
    UI sees is consistent across every resource a grant covers.
    """
    if guild_id is None:
        return dac_level
    grant = active_grant_level(guild_id)  # "read" | "read_write" | None
    if grant is None:
        return dac_level
    grant_level = "write" if grant == "read_write" else "read"
    if dac_level is None:
        return grant_level
    return (
        dac_level if _LEVEL_RANK[dac_level] >= _LEVEL_RANK[grant_level] else grant_level
    )


# ── Visibility subqueries ────────────────────────────────────────
# Reusable subqueries that return IDs of entities a user can see.
# These eliminate the duplicated UNION pattern across endpoints.


def visible_project_ids_subquery(user_id: int):
    """Return a subquery of project IDs the user can access.

    Combines user-specific ``ProjectPermission`` rows with role-based
    ``ProjectRolePermission`` rows matched via ``InitiativeMember``.

    The explicit-permission branch is additionally gated on initiative scope
    (member / guild admin / platform bypass): a permission row left behind
    after the user was removed from the initiative must not grant access.
    The DB-level RESTRICTIVE policies used to enforce this; under
    schema-per-guild this subquery is the enforcement point.

    A third branch surfaces *every* project in a guild the user administers:
    guild admins have full access to all of their guild's data regardless of a
    permission row, so they must see all of it in listings, not only the
    projects they were explicitly granted.
    """
    user_perm_subq = (
        select(ProjectPermission.project_id)
        .join(Project, Project.id == ProjectPermission.project_id)
        .where(
            ProjectPermission.user_id == user_id,
            initiative_scope_clause(user_id, Project.initiative_id, Project.guild_id),
        )
    )
    role_perm_subq = select(ProjectRolePermission.project_id).join(
        InitiativeMember,
        (InitiativeMember.role_id == ProjectRolePermission.initiative_role_id)
        & (InitiativeMember.user_id == user_id),
    )
    guild_admin_subq = select(Project.id).where(
        guild_member_clause(user_id, Project.guild_id, role=GuildRole.admin)
    )
    return user_perm_subq.union(role_perm_subq, guild_admin_subq)


def visible_document_ids_subquery(user_id: int):
    """Return a subquery of document IDs the user can access.

    Combines user-specific ``DocumentPermission`` rows with role-based
    ``DocumentRolePermission`` rows matched via ``InitiativeMember``.

    The explicit-permission branch is additionally gated on initiative scope
    (member / guild admin / platform bypass) — see
    ``visible_project_ids_subquery`` for why. The third branch likewise surfaces
    every document in a guild the user administers.
    """
    user_perm_subq = (
        select(DocumentPermission.document_id)
        .join(Document, Document.id == DocumentPermission.document_id)
        .where(
            DocumentPermission.user_id == user_id,
            initiative_scope_clause(user_id, Document.initiative_id, Document.guild_id),
        )
    )
    role_perm_subq = select(DocumentRolePermission.document_id).join(
        InitiativeMember,
        (InitiativeMember.role_id == DocumentRolePermission.initiative_role_id)
        & (InitiativeMember.user_id == user_id),
    )
    guild_admin_subq = select(Document.id).where(
        guild_member_clause(user_id, Document.guild_id, role=GuildRole.admin)
    )
    return user_perm_subq.union(role_perm_subq, guild_admin_subq)


# ── Initiative-scope gate (loaded-data variant) ──────────────────


def is_request_guild_admin(
    guild_id: int | None,
    *,
    guild_role: GuildRole | str | None = None,
) -> bool:
    """Whether the request acts as a *guild admin* of ``guild_id``.

    Guild roles are strictly guild-scoped — a guild admin has full authority
    only within their own guild's schema. The role is taken from ``guild_role``
    when the caller already holds it, otherwise from the request's active-guild
    role context (``role_context`` is keyed by guild id, so a role recorded for
    one guild never bleeds into another). This is deliberately independent of
    app/platform-level roles (``data.bypass``, PAM grants), which reach across
    guilds through their own separate mechanisms — do not fold those in here.
    """
    if guild_id is None:
        return False
    role = guild_role if guild_role is not None else active_guild_role(guild_id)
    role_value = role.value if isinstance(role, GuildRole) else role
    return role_value == GuildRole.admin.value


def initiative_scope_ok(
    entity: Any,
    user: User,
    *,
    guild_role: GuildRole | str | None = None,
) -> bool:
    """Sync counterpart of ``initiative_scope_clause`` for single entities
    whose ``initiative.memberships`` are already eagerly loaded.

    Mirrors the old RESTRICTIVE policy expression: initiative member, OR
    admin of the entity's guild (guild-level), OR ``data.bypass`` holder, OR a
    live PAM grant covering the guild (the latter two are app-level reach,
    handled separately from the guild role).
    """
    initiative = getattr(entity, "initiative", None)
    memberships = (
        getattr(initiative, "memberships", None) if initiative is not None else None
    ) or []
    if any(m.user_id == user.id for m in memberships):
        return True
    guild_id = getattr(entity, "guild_id", None)
    # App-level reach — kept distinct from the guild role below.
    if user_has_capability(user, Capability.DATA_BYPASS):
        return True
    if guild_id is not None and has_active_grant(guild_id):
        return True
    # Guild-level: admin of the entity's own guild.
    return is_request_guild_admin(guild_id, guild_role=guild_role)


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
) -> str | None:
    """Compute the effective permission level string for a user on a project.

    A guild admin gets ``owner`` — they have full access to all of their guild's
    data regardless of DAC (see ``require_project_access``), so the
    ``my_permission_level`` the client sees must report it or the UI would hide
    edit/delete affordances the API actually honors. This short-circuit also
    avoids the (otherwise wasted) DAC computation for admins.

    Otherwise pure DAC from eagerly-loaded relationships (permissions,
    role_permissions, initiative.memberships) so no DB queries are needed,
    lifted to any active PAM grant level.
    """
    guild_id = getattr(project, "guild_id", None)
    if is_request_guild_admin(guild_id):
        return ProjectPermissionLevel.owner.value
    user_perm = user_permission_from_project(project, user_id)
    user_level = user_perm.level if user_perm else None
    role_level = project_role_permission_level(project, user_id)
    effective = effective_project_permission(user_level, role_level)
    return lift_level_for_grant(effective.value if effective else None, guild_id)


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
    guild_role: GuildRole | str | None = None,
) -> None:
    """Raise HTTPException if user lacks required project access.

    DAC: Access granted through explicit ProjectPermission or role-based
    permission.  Effective level = MAX(user-specific, role-based).
    A live PAM grant covering the project's guild also satisfies read/write.

    Access additionally requires initiative scope (member / guild admin /
    platform bypass) — a stale permission row alone never grants access.

    A guild admin has full read/write/owner access to every project in their
    guild regardless of initiative membership or DAC, so they short-circuit the
    DAC checks below entirely.
    """
    if grant_satisfies(project.guild_id, access=access, require_owner=require_owner):
        return
    if is_request_guild_admin(project.guild_id, guild_role=guild_role):
        return
    if not initiative_scope_ok(project, user, guild_role=guild_role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ProjectMessages.NO_ACCESS,
        )
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
) -> str | None:
    """Compute the effective permission level string for a user on a document.

    A guild admin gets ``owner`` — full access to all of their guild's data
    regardless of DAC (see ``require_document_access``) — so the client renders
    edit/delete affordances; the short-circuit also skips the otherwise-wasted
    DAC computation. Otherwise pure DAC from eagerly-loaded relationships
    (permissions, role_permissions, initiative.memberships) so no DB queries are
    needed, lifted to any active PAM grant level.
    """
    guild_id = getattr(document, "guild_id", None)
    if is_request_guild_admin(guild_id):
        return DocumentPermissionLevel.owner.value
    user_level: DocumentPermissionLevel | None = None
    permissions = getattr(document, "permissions", None) or []
    for perm in permissions:
        if perm.user_id == user_id:
            user_level = perm.level
            break

    role_level = document_role_permission_level(document, user_id)
    effective = effective_document_permission(user_level, role_level)
    return lift_level_for_grant(effective.value if effective else None, guild_id)


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
    guild_role: GuildRole | str | None = None,
) -> None:
    """Raise HTTPException if user lacks required document access.

    DAC: Access granted through explicit DocumentPermission or role-based
    permission.  Effective level = MAX(user-specific, role-based).
    A live PAM grant covering the document's guild also satisfies read/write.

    Access additionally requires initiative scope (member / guild admin /
    platform bypass) — a stale permission row alone never grants access.

    A guild admin has full read/write/owner access to every document in their
    guild regardless of initiative membership or DAC, so they short-circuit the
    DAC checks below entirely.
    """
    if grant_satisfies(document.guild_id, access=access, require_owner=require_owner):
        return
    if is_request_guild_admin(document.guild_id, guild_role=guild_role):
        return
    if not initiative_scope_ok(document, user, guild_role=guild_role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=DocumentMessages.NO_ACCESS,
        )
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


def get_document_permission(
    document: Document, user_id: int
) -> DocumentPermission | None:
    """Get a user's permission for a document from the loaded permissions."""
    return next(
        (p for p in _get_loaded_document_permissions(document) if p.user_id == user_id),
        None,
    )
