"""Discretionary Access Control (DAC) — project and document permissions.

This module handles the application-level permission layer for projects
and documents.  Unlike the mandatory RLS layer (see ``rls.py``) which is
enforced by PostgreSQL, DAC permissions are filtering tools applied in
application code to determine what a user can read, write, or own.

Security layers managed here:
  - Resource grants — user/role access rows in ``ResourceGrant`` (polymorphic)
  - Visibility subqueries — reusable UNION subqueries for listing endpoints
  - Access enforcement — ``require_project_access`` / ``require_document_access``

The complementary mandatory access control layer (guild isolation,
initiative membership, initiative RBAC) lives in ``rls.py``.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, TypeVar

from fastapi import HTTPException, status
from sqlalchemy import and_, or_
from sqlmodel import select

from app.core.pam_context import active_grant_level, grant_satisfies, has_active_grant
from app.core.role_context import active_guild_role, request_overrides_sharing
from app.services.membership import guild_member_clause

from app.models.platform.guild import GuildRole
from app.models.tenant.project import (
    Project,
    ProjectPermissionLevel,
)
from app.models.tenant.document import (
    Document,
    DocumentPermissionLevel,
)
from app.models.tenant.initiative import InitiativeMember, InitiativeRoleModel
from app.models.platform.user import User
from app.core.messages import (
    ProjectMessages,
    DocumentMessages,
    QueueMessages,
    CounterMessages,
    CalendarEventMessages,
)
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant


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
        role_permissions: The role-based grant records (rows with an
            ``initiative_role_id`` and ``level``).
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
# IDs of a resource the user can see, from resource_grants (one query). Run under
# RLS, so stale grants in an initiative the user left are already filtered out.


def visible_resource_ids_subquery(resource_type: str, user_id: int):
    """resource_ids of ``resource_type`` the user can access via a grant — their
    own user grant, a grant to one of their initiative roles, OR an
    all-initiative-members grant on a resource in an initiative they belong to."""
    my_roles = select(InitiativeMember.role_id).where(
        InitiativeMember.user_id == user_id
    )
    my_initiatives = select(InitiativeMember.initiative_id).where(
        InitiativeMember.user_id == user_id
    )
    return select(ResourceGrant.resource_id).where(
        ResourceGrant.resource_type == resource_type,
        or_(
            ResourceGrant.user_id == user_id,
            ResourceGrant.role_id.in_(my_roles),
            and_(
                ResourceGrant.all_initiative_members.is_(True),
                ResourceGrant.initiative_id.in_(my_initiatives),
            ),
        ),
    )


def visible_project_ids_subquery(user_id: int):
    """Project IDs the user can access: granted ∪ (all projects if guild admin)."""
    guild_admin_subq = select(Project.id).where(
        guild_member_clause(user_id, Project.guild_id, role=GuildRole.admin)
    )
    return visible_resource_ids_subquery("project", user_id).union(guild_admin_subq)


def visible_document_ids_subquery(user_id: int):
    """Document IDs the user can access: granted ∪ (all documents if guild admin)."""
    guild_admin_subq = select(Document.id).where(
        guild_member_clause(user_id, Document.guild_id, role=GuildRole.admin)
    )
    return visible_resource_ids_subquery("document", user_id).union(guild_admin_subq)


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


def request_bypasses_dac(
    guild_id: int | None,
    *,
    initiative_id: int | None = None,
    access: str = "read",
    require_owner: bool = False,
    guild_role: GuildRole | str | None = None,
) -> bool:
    """The single "sees/edits regardless of DAC rows?" check — satisfying PAM
    grant OR guild admin OR initiative "Full access". Defined once so a call site
    can't apply one leg and drop the other (the regression that hid a guild
    admin's tasks).

    The initiative "Full access" leg (``request_overrides_sharing``) is the
    initiative-scoped sibling of the guild-admin leg: like guild admin, it
    ignores ``require_owner`` (a full-access PM may manage an item's sharing —
    an owner-only operation — within their initiative).

    A guild-scoped resource always carries a ``guild_id`` (the override set is
    itself computed within a guild context), so no ``guild_id`` means no guild
    context to reason about — fail closed before any leg, including the override
    one."""
    if guild_id is None:
        return False
    if grant_satisfies(guild_id, access=access, require_owner=require_owner):
        return True
    if is_request_guild_admin(guild_id, guild_role=guild_role):
        return True
    return request_overrides_sharing(initiative_id)


def initiative_scope_ok(
    entity: Any,
    user: User,
    *,
    guild_role: GuildRole | str | None = None,
) -> bool:
    """Sync counterpart of ``initiative_scope_clause`` for single entities
    whose ``initiative.memberships`` are already eagerly loaded.

    Mirrors the old RESTRICTIVE policy expression: initiative member, OR
    admin of the entity's guild (guild-level), OR a live PAM/break-glass grant
    covering the guild (app-level reach, handled separately from the guild role).

    There is no standing ``data.bypass`` leg any more: a platform admin/owner
    reaches a guild only through an explicit break-glass grant, which surfaces
    here as ``has_active_grant``.
    """
    initiative = getattr(entity, "initiative", None)
    memberships = (
        getattr(initiative, "memberships", None) if initiative is not None else None
    ) or []
    if any(m.user_id == user.id for m in memberships):
        return True
    guild_id = getattr(entity, "guild_id", None)
    # App-level reach via an explicit, time-bound grant — kept distinct from the
    # guild role below.
    if guild_id is not None and has_active_grant(guild_id):
        return True
    # Guild-level: admin of the entity's own guild.
    return is_request_guild_admin(guild_id, guild_role=guild_role)


# ── Generic DAC engine (registry-driven) ─────────────────────────
# Every DAC resource resolves access from its ``grants`` (resource_grants rows)
# the same way — one registry row + one engine.


@dataclass(frozen=True)
class DacResource:
    name: str
    scope_gate: bool  # gate on initiative_scope_ok? (project/document yes)
    denied_msg: str
    owner_msg: str
    write_msg: str


DAC_RESOURCES: dict[str, DacResource] = {
    "project": DacResource(
        "project",
        True,
        ProjectMessages.NO_ACCESS,
        ProjectMessages.OWNER_REQUIRED,
        ProjectMessages.WRITE_ACCESS_REQUIRED,
    ),
    "document": DacResource(
        "document",
        True,
        DocumentMessages.NO_ACCESS,
        DocumentMessages.OWNER_REQUIRED,
        DocumentMessages.WRITE_ACCESS_REQUIRED,
    ),
    "queue": DacResource(
        "queue",
        False,
        QueueMessages.PERMISSION_REQUIRED,
        QueueMessages.OWNER_REQUIRED,
        QueueMessages.WRITE_ACCESS_REQUIRED,
    ),
    "counter_group": DacResource(
        "counter_group",
        False,
        CounterMessages.PERMISSION_REQUIRED,
        CounterMessages.OWNER_REQUIRED,
        CounterMessages.WRITE_ACCESS_REQUIRED,
    ),
    "calendar_event": DacResource(
        "calendar_event",
        False,
        CalendarEventMessages.PERMISSION_REQUIRED,
        CalendarEventMessages.OWNER_REQUIRED,
        CalendarEventMessages.WRITE_ACCESS_REQUIRED,
    ),
}


def _grant_level(level: Any) -> str:
    return level.value if hasattr(level, "value") else level


def serialize_grants(row: Any) -> list:
    """Serialize a resource's eager-loaded ``grants`` into the unified grant list
    — one ``ResourceGrantSchema`` per ``resource_grants`` row (user, role, or
    all-initiative-members), owner included."""
    from app.schemas.tenant.resource_grant import ResourceGrantSchema

    return [
        ResourceGrantSchema(
            level=_grant_level(g.level),
            user_id=g.user_id,
            role_id=g.role_id,
            all_initiative_members=bool(getattr(g, "all_initiative_members", False)),
        )
        for g in getattr(row, "grants", None) or []
    ]


def effective_level(resource: DacResource, row: Any, user_id: int) -> str | None:
    """Highest grant level (read<write<owner) for ``user_id`` on ``row`` — from the
    user's own grant, a grant to one of their initiative roles, or an
    all-initiative-members grant when the user is a member, else None. Reads
    eagerly-loaded ``grants`` + ``initiative.memberships``."""
    grants = getattr(row, "grants", None) or []
    initiative = getattr(row, "initiative", None)
    memberships = (
        getattr(initiative, "memberships", None) if initiative is not None else None
    ) or []
    role_ids = {
        m.role_id for m in memberships if m.user_id == user_id and m.role_id is not None
    }
    is_member = any(m.user_id == user_id for m in memberships)
    best: str | None = None
    best_rank = -1
    for g in grants:
        applies = (
            g.user_id == user_id
            or (g.role_id is not None and g.role_id in role_ids)
            or (getattr(g, "all_initiative_members", False) and is_member)
        )
        if applies:
            lvl = _grant_level(g.level)
            if _LEVEL_RANK[lvl] > best_rank:
                best_rank, best = _LEVEL_RANK[lvl], lvl
    return best


async def replace_resource_grants(
    session: Any,
    *,
    resource_type: str,
    resource_id: int,
    guild_id: int,
    initiative_id: int,
    owner_id: int,
    grants: Any,
) -> None:
    """Rebuild a resource's non-owner grants from ``grants`` (a list of
    ResourceAccessGrant rows). Each row is sorted by grantee kind — all-initiative-
    members, per-user, or per-role. The owner grant is preserved; owner-level
    entries and grantees outside the initiative are dropped. Caller commits +
    reapplies RLS."""
    all_members_level: str | None = None
    user_levels: dict[int, str] = {}
    role_levels: dict[int, str] = {}
    for g in grants:
        level = g.level
        if level not in ("read", "write"):
            continue  # owner is preserved server-side, never set via this list
        if getattr(g, "all_initiative_members", False):
            all_members_level = level
        elif g.user_id is not None and g.user_id != owner_id:
            user_levels[g.user_id] = level
        elif g.role_id is not None:
            role_levels[g.role_id] = level

    valid_users: set[int] = set()
    if user_levels:
        valid_users = set(
            (
                await session.exec(
                    select(InitiativeMember.user_id).where(
                        InitiativeMember.initiative_id == initiative_id,
                        InitiativeMember.user_id.in_(list(user_levels)),
                    )
                )
            ).all()
        )
    valid_roles: set[int] = set()
    if role_levels:
        valid_roles = set(
            (
                await session.exec(
                    select(InitiativeRoleModel.id).where(
                        InitiativeRoleModel.initiative_id == initiative_id,
                        InitiativeRoleModel.id.in_(list(role_levels)),
                    )
                )
            ).all()
        )

    existing = (
        await session.exec(
            select(ResourceGrant).where(
                ResourceGrant.resource_type == resource_type,
                ResourceGrant.resource_id == resource_id,
            )
        )
    ).all()
    for g in existing:
        if _grant_level(g.level) != "owner":
            await session.delete(g)

    def _grant(level: str, **kw: Any) -> ResourceGrant:
        return ResourceGrant(
            resource_type=resource_type,
            resource_id=resource_id,
            guild_id=guild_id,
            initiative_id=initiative_id,
            level=ResourceAccessLevel(level),
            **kw,
        )

    if all_members_level is not None:
        session.add(_grant(all_members_level, all_initiative_members=True))
    session.add_all(
        _grant(level, user_id=uid)
        for uid, level in user_levels.items()
        if uid in valid_users
    )
    session.add_all(
        _grant(level, role_id=rid)
        for rid, level in role_levels.items()
        if rid in valid_roles
    )


def require_access(
    resource: DacResource,
    row: Any,
    user: User,
    *,
    access: str = "read",
    require_owner: bool = False,
    guild_role: GuildRole | str | None = None,
) -> None:
    """Raise 403 unless ``user`` may act on ``row``: bypass (admin/PAM/Full
    access) → (scope_gate) initiative scope → effective DAC level vs requested
    access."""
    guild_id = getattr(row, "guild_id", None)
    initiative_id = getattr(row, "initiative_id", None)
    if request_bypasses_dac(
        guild_id,
        initiative_id=initiative_id,
        access=access,
        require_owner=require_owner,
        guild_role=guild_role,
    ):
        return
    if resource.scope_gate and not initiative_scope_ok(
        row, user, guild_role=guild_role
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=resource.denied_msg
        )
    effective = effective_level(resource, row, user.id)

    if require_owner:
        if effective != "owner":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=resource.owner_msg
            )
        return

    if effective is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=resource.denied_msg
        )

    if access == "write" and effective == "read":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=resource.write_msg
        )


def compute_permission(resource: DacResource, row: Any, user_id: int) -> str | None:
    """``my_permission_level`` for the client: guild admin / initiative "Full
    access" → owner, else effective DAC level lifted to any active PAM grant."""
    guild_id = getattr(row, "guild_id", None)
    initiative_id = getattr(row, "initiative_id", None)
    if is_request_guild_admin(guild_id) or request_overrides_sharing(initiative_id):
        return "owner"
    return lift_level_for_grant(effective_level(resource, row, user_id), guild_id)


# ── High-level helpers for projects ─────────────────────────────


def compute_project_permission(
    project: Project,
    user_id: int,
) -> str | None:
    """Effective project permission string for the client (delegates to the engine)."""
    return compute_permission(DAC_RESOURCES["project"], project, user_id)


def require_project_access(
    project: Project,
    user: User,
    *,
    access: str = "read",
    require_owner: bool = False,
    guild_role: GuildRole | str | None = None,
) -> None:
    """Raise 403 unless the user may act on the project (delegates to the engine)."""
    require_access(
        DAC_RESOURCES["project"],
        project,
        user,
        access=access,
        require_owner=require_owner,
        guild_role=guild_role,
    )


def has_project_write_access(
    project: Project,
    user: User,
) -> bool:
    """Check if user has write access (synchronous, for filtering)."""
    return effective_level(DAC_RESOURCES["project"], project, user.id) in (
        "write",
        "owner",
    )


# ── High-level helpers for documents ─────────────────────────────


def compute_document_permission(
    document: Document,
    user_id: int,
) -> str | None:
    """Effective document permission string for the client (delegates to the engine)."""
    return compute_permission(DAC_RESOURCES["document"], document, user_id)


def compute_calendar_event_permission(event: Any, user_id: int) -> str | None:
    """Effective calendar-event permission string for the client (delegates to the engine)."""
    return compute_permission(DAC_RESOURCES["calendar_event"], event, user_id)


def require_document_access(
    document: Document,
    user: User,
    *,
    access: str = "read",
    require_owner: bool = False,
    guild_role: GuildRole | str | None = None,
) -> None:
    """Raise 403 unless the user may act on the document (delegates to the engine)."""
    require_access(
        DAC_RESOURCES["document"],
        document,
        user,
        access=access,
        require_owner=require_owner,
        guild_role=guild_role,
    )
