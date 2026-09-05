"""Discretionary Access Control (DAC) — per-resource sharing.

The application-level permission layer for every tool. Unlike the mandatory RLS
layer (see ``rls.py``), which PostgreSQL enforces, this resolves what a request
may read, write or own from the ``resource_grants`` rows on a resource.

The result is asked for in two shapes, and the second is defined in terms of the
first:

  - :func:`request_bypasses_dac` for a loaded row, behind
    :func:`require_access` / :func:`compute_permission`
  - :func:`dac_scope_clause` for a query, appended to a listing's WHERE

Guild isolation and initiative membership are separate layers, in ``rls.py`` and
Postgres, with the sync initiative-scope check beside its SQL counterpart in
``membership.py``.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, TypeVar

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, and_, or_, true
from sqlmodel import select

from app.core.pam_context import active_grant_level, grant_satisfies
from app.core.role_context import (
    content_read_only_active,
    is_request_guild_admin,
    request_overrides_sharing,
)
from app.services.membership import NO_SCOPE_COLUMN, initiative_scope_ok
from app.core.tools import Tool

from app.models.platform.guild import GuildMembership, GuildRole
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
    CalendarMessages,
    DashboardMessages,
    PostMessages,
)
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant


# ---------------------------------------------------------------------------
# Generic helpers (work with both project and document permission enums)
# ---------------------------------------------------------------------------

# Permission-level enum the generic helpers operate on. Bound to Enum so each
# caller's concrete level type (ProjectPermissionLevel, DocumentPermissionLevel,
# QueuePermissionLevel) flows through to the return type.
PermLevel = TypeVar("PermLevel", bound=Enum)


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


def _granted_resource_ids(resource_type: str, user_id: int):
    """resource_ids of ``resource_type`` the user can access via a grant — their
    own user grant, a grant to one of their initiative roles, OR an
    all-initiative-members grant on a resource in an initiative they belong to.

    Grant rows only. :func:`dac_scope_clause` is the public entry point and
    composes this with the rest of the decision.
    """
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
                or_(
                    ResourceGrant.initiative_id.in_(my_initiatives),
                    # Guild scope: a grant on a resource that belongs to no
                    # initiative. "Everyone" reads as every member of the guild,
                    # and being able to run this query at all means being in it
                    # — the rows live in that guild's schema.
                    ResourceGrant.initiative_id.is_(None),
                ),
            ),
        ),
    )


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


def granted_scope_clause(
    tool: Tool,
    id_col: ColumnElement[int],
    user_id: int,
    *,
    guild_id: int | None,
    access: str = "read",
) -> ColumnElement[bool]:
    """The WHERE leg for a listing that **spans initiatives** — the cross-guild
    ``/me/*`` views and a guild-wide tool list, which is the guild home's table.

    Such a list is answered by what has been granted to the reader: a grant
    naming them, one on an initiative role they hold, or one shared with every
    member of an initiative they are in. Guild-admin standing is not a leg here.
    An admin's authority still reaches every initiative in their community, and
    every gate that acts on one still honours it; what a list spanning
    initiatives shows is what reaches the reader, the same way their sidebar and
    the community front page list the initiatives they joined.

    That is also why ``initiative_id`` is absent from this signature where
    :func:`dac_scope_clause` has one: the initiative "Full access" override
    answers for one initiative at a time, and a list spanning them has no single
    initiative to ask about.

    A PAM or break-glass grantee keeps their window. They hold no membership row
    and no grant, so the grant legs would answer nothing at all — the grant is
    what they navigate by, exactly as it is in the initiative listing.

    Use :func:`dac_scope_clause` for a statement already confined to one
    initiative, where the reader's standing in that initiative is the question.
    """
    if grant_satisfies(guild_id, access=access):
        return true()
    return id_col.in_(_granted_resource_ids(tool, user_id))


def dac_scope_clause(
    tool: Tool,
    id_col: ColumnElement[int],
    user_id: int,
    *,
    guild_id: int | None,
    initiative_id: int | None = None,
    access: str = "read",
) -> ColumnElement[bool]:
    """The WHERE leg narrowing ``id_col`` to the ``tool`` rows this request may see.

    The query-shaped form of :func:`request_bypasses_dac`: that one answers for a
    loaded row, this one answers once for a whole statement, and both resolve
    through the same call. It returns ``true()`` when the request already covers
    the guild, so a caller appends it unconditionally rather than branching.

    ``id_col`` is whichever column names the resource — its own id, or a foreign
    key to it (``Task.project_id``). ``access`` is what the caller intends to do:
    a listing wants the default ``read``, and a grant covers only the level it
    was issued at.

    ``initiative_id`` folds in the initiative "Full access" override, which
    answers for one initiative at a time. Pass it only from a statement already
    confined to that one initiative, which is the case in which the override and
    the statement agree on scope. Omitting it matches the per-row check
    (:func:`compute_permission`) for every other leg.

    A listing that spans initiatives wants :func:`granted_scope_clause` instead:
    guild-admin standing answers "may I reach it", which is the right question
    for one initiative and the wrong one for a list across them.
    """
    if request_bypasses_dac(guild_id, initiative_id=initiative_id, access=access):
        return true()
    return id_col.in_(_granted_resource_ids(tool, user_id))


def listing_scope_clause(
    tool: Tool,
    id_col: ColumnElement[int],
    user_id: int,
    *,
    guild_id: int | None,
    initiative_id: int | None = None,
    access: str = "read",
) -> ColumnElement[bool]:
    """The WHERE leg for a tool listing, picking the rule its scope calls for.

    Confined to one initiative, the question is the reader's standing there, and
    a guild admin's reaches all of it — :func:`dac_scope_clause`.

    Spanning initiatives — the community front page's table, the sidebar's tool
    lists, the cross-guild ``/me/*`` views — the question is what has been
    granted to the reader, so :func:`granted_scope_clause` answers it. This is
    the listing-shaped form of the same rule the initiative listing follows: an
    admin navigates what reaches them, and reaches everything else the moment
    they ask for one initiative by name.

    The initiative "Full access" override stays out of the confined branch, as
    it already was at every call site here; folding it into listings is a
    separate decision from choosing between these two rules.
    """
    if initiative_id is None:
        return granted_scope_clause(
            tool, id_col, user_id, guild_id=guild_id, access=access
        )
    return dac_scope_clause(tool, id_col, user_id, guild_id=guild_id, access=access)


# ── Generic DAC engine (registry-driven) ─────────────────────────
# Every DAC resource resolves access from its ``grants`` (resource_grants rows)
# the same way — one registry row + one engine.


@dataclass(frozen=True)
class DacResource:
    name: Tool
    scope_gate: bool  # gate on initiative_scope_ok? (project/document yes)
    denied_msg: str
    owner_msg: str
    write_msg: str


DAC_RESOURCES: dict[Tool, DacResource] = {
    Tool.project: DacResource(
        Tool.project,
        True,
        ProjectMessages.NO_ACCESS,
        ProjectMessages.OWNER_REQUIRED,
        ProjectMessages.WRITE_ACCESS_REQUIRED,
    ),
    Tool.document: DacResource(
        Tool.document,
        True,
        DocumentMessages.NO_ACCESS,
        DocumentMessages.OWNER_REQUIRED,
        DocumentMessages.WRITE_ACCESS_REQUIRED,
    ),
    Tool.queue: DacResource(
        Tool.queue,
        False,
        QueueMessages.PERMISSION_REQUIRED,
        QueueMessages.OWNER_REQUIRED,
        QueueMessages.WRITE_ACCESS_REQUIRED,
    ),
    Tool.counter_group: DacResource(
        Tool.counter_group,
        False,
        CounterMessages.PERMISSION_REQUIRED,
        CounterMessages.OWNER_REQUIRED,
        CounterMessages.WRITE_ACCESS_REQUIRED,
    ),
    Tool.calendar: DacResource(
        Tool.calendar,
        True,
        CalendarMessages.PERMISSION_REQUIRED,
        CalendarMessages.OWNER_REQUIRED,
        CalendarMessages.WRITE_ACCESS_REQUIRED,
    ),
    Tool.dashboard: DacResource(
        Tool.dashboard,
        True,
        DashboardMessages.PERMISSION_REQUIRED,
        DashboardMessages.OWNER_REQUIRED,
        DashboardMessages.WRITE_ACCESS_REQUIRED,
    ),
    Tool.post: DacResource(
        Tool.post,
        True,
        PostMessages.PERMISSION_REQUIRED,
        PostMessages.OWNER_REQUIRED,
        PostMessages.WRITE_ACCESS_REQUIRED,
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
    all-members grant when the user is a member, else None. Reads
    eagerly-loaded ``grants`` + ``initiative.memberships``.

    On a guild-level row (no initiative) the all-members grant applies to every
    member of the guild. Role grants there are not resolved yet — a guild role is
    not an ``initiative_roles`` row — so guild-scope sharing is by everyone or by
    named user until that has its own design.
    """
    grants = getattr(row, "grants", None) or []
    initiative = getattr(row, "initiative", None)
    memberships = (
        getattr(initiative, "memberships", None) if initiative is not None else None
    ) or []
    role_ids = {
        m.role_id for m in memberships if m.user_id == user_id and m.role_id is not None
    }
    # A row that names no initiative is guild-level, and there "all members"
    # means the guild's. Reading the column through a sentinel rather than
    # `getattr(row, "initiative_id", None)`: a row type that has no such column
    # at all must not be mistaken for one that has it set to NULL.
    scope = getattr(row, "initiative_id", NO_SCOPE_COLUMN)
    is_member = scope is None or any(m.user_id == user_id for m in memberships)
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
    initiative_id: int | None,
    owner_id: int,
    grants: Any,
) -> None:
    """Rebuild a resource's non-owner grants from ``grants`` (a list of
    ResourceAccessGrant rows). Each row is sorted by grantee kind — all-members,
    per-user, or per-role. The owner grant is preserved; owner-level entries and
    grantees outside the resource's scope are dropped. Caller commits.

    ``initiative_id`` is None for a guild-level resource. There "all members"
    means the guild's, and a named grantee is validated against guild
    membership; role grants are not resolvable (see below)."""
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

    guild_scoped = initiative_id is None

    valid_users: set[int] = set()
    if user_levels:
        if guild_scoped:
            # The resource belongs to no initiative, so a named grantee is
            # someone in the *guild*. Validating against initiative membership
            # here would compare against NULL and match nobody, silently
            # dropping every named grant on a guild-level resource.
            valid_users = set(
                (
                    await session.exec(
                        select(GuildMembership.user_id).where(
                            GuildMembership.guild_id == guild_id,
                            GuildMembership.user_id.in_(list(user_levels)),
                        )
                    )
                ).all()
            )
        else:
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
    # Role grants are initiative roles. A guild-level resource has no initiative
    # for a role to belong to, and a guild role is not an ``initiative_roles``
    # row, so there is nothing to validate against — guild-scope sharing is by
    # everyone or by named user until guild-role principals have a design.
    if role_levels and not guild_scoped:
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

    await session.flush()

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
    """Raise 403 unless ``user`` may act on ``row``: frozen-guild read cap →
    bypass (admin/PAM/Full access) → (scope_gate) initiative scope → effective
    DAC level vs requested access."""
    guild_id = getattr(row, "guild_id", None)
    initiative_id = getattr(row, "initiative_id", None)
    # A frozen guild (read_only lifecycle status) caps EVERY real member at
    # read — before the bypass legs, so the guild-admin override can't clear
    # it. The flag is never set for PAM/break-glass requests, whose grants
    # override the status by design. The Postgres role (guild_<id>_ro) would
    # refuse the write anyway; failing here keeps the app layer in agreement
    # and the error clean.
    if content_read_only_active(guild_id) and (access != "read" or require_owner):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=resource.write_msg
        )
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
    access" → owner, else effective DAC level lifted to any active PAM grant.
    A frozen guild (read_only lifecycle status) caps the result at read — the
    single place the client-facing level reflects the hold, so every surface
    (edit affordances, writable filters, the collaboration socket's can_write)
    inherits it without re-deriving the status."""
    guild_id = getattr(row, "guild_id", None)
    initiative_id = getattr(row, "initiative_id", None)
    level: str | None
    if is_request_guild_admin(guild_id) or request_overrides_sharing(initiative_id):
        level = "owner"
    else:
        level = lift_level_for_grant(effective_level(resource, row, user_id), guild_id)
    if level is not None and content_read_only_active(guild_id):
        return "read"
    return level


# ── High-level helpers for projects ─────────────────────────────


def compute_project_permission(
    project: Project,
    user_id: int,
) -> str | None:
    """Effective project permission string for the client (delegates to the engine)."""
    return compute_permission(DAC_RESOURCES[Tool.project], project, user_id)


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
        DAC_RESOURCES[Tool.project],
        project,
        user,
        access=access,
        require_owner=require_owner,
        guild_role=guild_role,
    )


async def can_administer_project(
    session,
    project: Project,
    user: User,
    *,
    guild_role: GuildRole | str | None = None,
) -> bool:
    """Whether the user may configure the project itself.

    Configuring a project — pinning it, setting its default view, curating its
    filter presets — is a step above being able to edit its content. Three ways
    to hold it: a guild admin, a manager of the owning initiative, or the
    project's own owner. Plain write access is deliberately not enough.
    """
    from app.services import rls as rls_service  # local: rls imports this module

    if rls_service.is_guild_admin(guild_role):
        return True
    if compute_project_permission(project, user.id) == "owner":
        return True
    if project.initiative_id:
        return await rls_service.is_initiative_manager(
            session,
            initiative_id=project.initiative_id,
            user=user,
        )
    return False


async def require_project_admin(
    session,
    project: Project,
    user: User,
    *,
    guild_role: GuildRole | str | None = None,
) -> None:
    """Raise 403 unless the user may configure the project (see above)."""
    if not await can_administer_project(session, project, user, guild_role=guild_role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ProjectMessages.ADMIN_REQUIRED,
        )


def has_project_write_access(
    project: Project,
    user: User,
) -> bool:
    """Check if user has write access (synchronous, for filtering)."""
    if content_read_only_active(getattr(project, "guild_id", None)):
        return False
    return effective_level(DAC_RESOURCES[Tool.project], project, user.id) in (
        "write",
        "owner",
    )


# ── High-level helpers for documents ─────────────────────────────


def compute_document_permission(
    document: Document,
    user_id: int,
) -> str | None:
    """Effective document permission string for the client (delegates to the engine)."""
    return compute_permission(DAC_RESOURCES[Tool.document], document, user_id)


def compute_calendar_permission(calendar: Any, user_id: int) -> str | None:
    """Effective calendar permission string for the client (delegates to the engine)."""
    return compute_permission(DAC_RESOURCES[Tool.calendar], calendar, user_id)


def compute_dashboard_permission(dashboard: Any, user_id: int) -> str | None:
    """Effective dashboard permission string for the client (delegates to the
    engine). Governs authoring the canvas only — the data each widget displays
    is authorized separately, per viewer, by that data's own tool."""
    return compute_permission(DAC_RESOURCES[Tool.dashboard], dashboard, user_id)


def compute_post_permission(post: Any, user_id: int) -> str | None:
    """Effective post permission string for the client (delegates to the
    engine). Reading a post is reading the board it sits on; writing one is
    editing that notice, which is its author's or whoever they shared it
    with — pinning is a separate, initiative-level authority."""
    return compute_permission(DAC_RESOURCES[Tool.post], post, user_id)


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
        DAC_RESOURCES[Tool.document],
        document,
        user,
        access=access,
        require_owner=require_owner,
        guild_role=guild_role,
    )
