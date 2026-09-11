"""Discretionary Access Control (DAC) — per-resource sharing.

The application-level permission layer for every tool. Unlike the mandatory RLS
layer (see ``rls.py``), which PostgreSQL enforces, this resolves what a request
may read, write or own from the ``resource_grants`` rows on a resource.

What is left here is what Postgres does not answer. The guild-schema policies
apply this same sharing rule to every content table — gate 4, rendered from
``app/db/initiative_rls.py`` and calling ``public.resource_access`` — so a
statement confined to one initiative needs no sharing clause of its own. The
app layer keeps the decisions the policies do not express:

  - :func:`require_access` — a *named* refusal on a loaded row, plus the
    frozen-guild cap
  - :func:`compute_permission` — what the client renders affordances from
  - :func:`granted_scope_clause` — deliberately NARROWER than the policy for a
    list spanning initiatives (no guild-admin leg)
  - :func:`writable_scope_clause` — "which of these may I change", which a read
    policy does not answer

Guild isolation and initiative membership are separate layers, in ``rls.py`` and
Postgres.
"""

from dataclasses import dataclass
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, and_, or_, true
from sqlmodel import select

from app.core.pam_context import active_grant_level, grant_satisfies
from app.core.role_context import (
    content_read_only_active,
    is_request_guild_admin,
    request_overrides_sharing,
)
from app.services.membership import NO_SCOPE_COLUMN
from app.core.tools import Tool

from app.models.platform.guild import GuildMembership, GuildRole
from app.models.tenant.project import Project
from app.models.tenant.document import Document
from app.models.tenant.initiative import InitiativeMember, InitiativeRoleModel
from app.models.platform.user import User
from app.db.frozen import ancestor_is_frozen, row_is_frozen
from app.core.messages import (
    CommonMessages,
    SharingMessages,
    ProjectMessages,
    DocumentMessages,
    QueueMessages,
    CounterMessages,
    CalendarMessages,
    DashboardMessages,
    GalleryMessages,
    PostMessages,
)
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant


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


#: The grant levels that let somebody change a resource. ``read`` is the third.
WRITE_LEVELS = (ResourceAccessLevel.write, ResourceAccessLevel.owner)


def _granted_resource_ids(
    resource_type: str,
    user_id: int,
    *,
    levels: tuple[ResourceAccessLevel, ...] | None = None,
):
    """resource_ids of ``resource_type`` the user can access via a grant — their
    own user grant, a grant to one of their initiative roles, OR an
    all-initiative-members grant on a resource in an initiative they belong to.

    ``levels`` narrows to grants issued at those levels; omitted, any grant
    counts, which is what a read listing wants.

    Grant rows only. :func:`granted_scope_clause` and
    :func:`writable_scope_clause` are the public entry points and compose this
    with the rest of the decision.
    """
    my_roles = select(InitiativeMember.role_id).where(
        InitiativeMember.user_id == user_id
    )
    my_initiatives = select(InitiativeMember.initiative_id).where(
        InitiativeMember.user_id == user_id
    )
    stmt = select(ResourceGrant.resource_id).where(
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
    if levels is not None:
        stmt = stmt.where(ResourceGrant.level.in_(levels))
    return stmt


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

    ``initiative_id`` is absent from this signature on purpose: the initiative
    "Full access" override answers for one initiative at a time, and a list
    spanning them has no single initiative to ask about.

    A PAM or break-glass grantee keeps their window. They hold no membership row
    and no grant, so the grant legs would answer nothing at all — the grant is
    what they navigate by, exactly as it is in the initiative listing.

    A statement already confined to one initiative asks nothing here — see
    :func:`listing_scope_clause`.
    """
    if grant_satisfies(guild_id, access=access):
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

    **Confined to one initiative, there is nothing to add.** The question is the
    reader's standing there, and the table's own policy already asked it: every
    content table carries a sharing leg deferring to ``public.resource_access``
    (guild admin OR PAM at the level OR the "Full access" override OR a grant
    row), ANDed with initiative membership and the reader's initiative role.
    Restating it here would narrow nothing and consult ``resource_grants`` a
    second time per row.

    **Spanning initiatives** — the community front page's table, the sidebar's
    tool lists, the cross-guild ``/me/*`` views — the question is what has been
    granted to the reader, which is NARROWER than the policy: it drops the
    guild-admin leg. An admin navigates what reaches them, and reaches
    everything else the moment they ask for one initiative by name. That is a
    product rule, not an enforcement one, so :func:`granted_scope_clause`
    carries it.
    """
    if initiative_id is not None:
        return true()
    return granted_scope_clause(tool, id_col, user_id, guild_id=guild_id, access=access)


def writable_scope_clause(
    tool: Tool,
    id_col: ColumnElement[int],
    user_id: int,
    *,
    guild_id: int | None,
    initiative_id: int | None = None,
) -> ColumnElement[bool]:
    """The listing rule narrowed to what the reader may CHANGE.

    This one does NOT collapse the way :func:`listing_scope_clause` does. A read
    policy admits a row shared at any level, so "may I see it" is already
    answered and "may I edit it" is strictly narrower — the grant rows have to
    be filtered to :data:`WRITE_LEVELS` here, whatever the statement's scope.

    The two branches are the scope choice made elsewhere: confined to one
    initiative, a guild admin's authority answers; spanning them, only what has
    been granted does.
    """
    if initiative_id is not None:
        if request_bypasses_dac(guild_id, initiative_id=initiative_id, access="write"):
            return true()
    elif grant_satisfies(guild_id, access="write"):
        return true()
    return id_col.in_(_granted_resource_ids(tool, user_id, levels=WRITE_LEVELS))


# ── Generic DAC engine (registry-driven) ─────────────────────────
# Every DAC resource resolves access from its ``grants`` (resource_grants rows)
# the same way — one registry row + one engine.


@dataclass(frozen=True)
class DacResource:
    name: Tool
    denied_msg: str
    owner_msg: str
    write_msg: str


DAC_RESOURCES: dict[Tool, DacResource] = {
    Tool.project: DacResource(
        Tool.project,
        ProjectMessages.NO_ACCESS,
        ProjectMessages.OWNER_REQUIRED,
        ProjectMessages.WRITE_ACCESS_REQUIRED,
    ),
    Tool.document: DacResource(
        Tool.document,
        DocumentMessages.NO_ACCESS,
        DocumentMessages.OWNER_REQUIRED,
        DocumentMessages.WRITE_ACCESS_REQUIRED,
    ),
    Tool.queue: DacResource(
        Tool.queue,
        QueueMessages.PERMISSION_REQUIRED,
        QueueMessages.OWNER_REQUIRED,
        QueueMessages.WRITE_ACCESS_REQUIRED,
    ),
    Tool.counter_group: DacResource(
        Tool.counter_group,
        CounterMessages.PERMISSION_REQUIRED,
        CounterMessages.OWNER_REQUIRED,
        CounterMessages.WRITE_ACCESS_REQUIRED,
    ),
    Tool.calendar: DacResource(
        Tool.calendar,
        CalendarMessages.PERMISSION_REQUIRED,
        CalendarMessages.OWNER_REQUIRED,
        CalendarMessages.WRITE_ACCESS_REQUIRED,
    ),
    Tool.dashboard: DacResource(
        Tool.dashboard,
        DashboardMessages.PERMISSION_REQUIRED,
        DashboardMessages.OWNER_REQUIRED,
        DashboardMessages.WRITE_ACCESS_REQUIRED,
    ),
    Tool.post: DacResource(
        Tool.post,
        PostMessages.PERMISSION_REQUIRED,
        PostMessages.OWNER_REQUIRED,
        PostMessages.WRITE_ACCESS_REQUIRED,
    ),
    Tool.gallery: DacResource(
        Tool.gallery,
        GalleryMessages.PERMISSION_REQUIRED,
        GalleryMessages.OWNER_REQUIRED,
        GalleryMessages.WRITE_ACCESS_REQUIRED,
    ),
}


def _grant_level(level: Any) -> str:
    return level.value if hasattr(level, "value") else level


def serialize_grants(row: Any) -> list:
    """Serialize a resource's eager-loaded ``grants`` into the unified grant list
    — one ``ResourceGrantSchema`` per ``resource_grants`` row (user, role,
    all-initiative-members, or the dashboard a published view reads it
    through), owner included."""
    from app.schemas.tenant.resource_grant import ResourceGrantSchema

    return [
        ResourceGrantSchema(
            level=_grant_level(g.level),
            user_id=g.user_id,
            role_id=g.role_id,
            all_initiative_members=bool(getattr(g, "all_initiative_members", False)),
            dashboard_id=getattr(g, "dashboard_id", None),
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


def audience_user_ids(row: Any) -> set[int]:
    """Every user the resource's sharing reaches, by id.

    The list-shaped form of :func:`effective_level`: that one answers "may this
    person reach it", this one answers "who are they". Both read the same two
    eagerly-loaded collections — the resource's ``grants`` and its initiative's
    ``memberships`` — and resolve a grant the same three ways, so a notifier
    built on this cannot address anyone the per-row check would turn away.

    Standing that comes from somewhere other than a grant is deliberately not
    here. A guild admin reaches every resource in their community and a
    break-glass grantee reaches one for a window; neither asked to hear about
    it. What this answers is who a thing was shared WITH, which is the only
    honest audience for telling people something exists.

    Every recipient is checked against the initiative's current roster,
    including one named directly. A grant outlives the membership it was
    written for — leaving an initiative does not sweep them — and RLS answers
    the leftover with 404, so a notification built on the grant alone would
    carry a headline and an excerpt to somebody who can no longer open the
    thing they name. The roster is what the database enforces, so it is what
    this counts.

    Initiative-scoped resources only. On a guild-level row an all-members grant
    means the guild's members, and there is no loaded collection here that
    names them.
    """
    grants = getattr(row, "grants", None) or []
    initiative = getattr(row, "initiative", None)
    memberships = (
        getattr(initiative, "memberships", None) if initiative is not None else None
    ) or []
    members = {m.user_id for m in memberships}
    audience: set[int] = set()
    for g in grants:
        if g.user_id is not None:
            audience.add(g.user_id)
        elif g.role_id is not None:
            audience.update(m.user_id for m in memberships if m.role_id == g.role_id)
        elif getattr(g, "all_initiative_members", False):
            audience.update(members)
    return audience & members


#: What a row needs, beyond being shared with you, before it is anybody's to
#: read. A tool absent from here has nothing between "shared with me" and "I
#: can see it"; a post has its publication, and until then it is a draft.
READ_VISIBLE: dict[Tool, Callable[[Any], bool]] = {
    Tool.post: lambda row: getattr(row, "published_at", None) is not None,
}


def may_write(
    resource: DacResource,
    row: Any,
    user_id: int,
    *,
    guild_id: int | None,
    guild_role: GuildRole | str | None = None,
) -> bool:
    """Whether this caller could change the row.

    The row-shaped form of :func:`writable_scope_clause`, leg for leg: the same
    bypass check, then a grant at :data:`WRITE_LEVELS`. Deliberately not
    :func:`compute_permission`, which caps at read while a community is frozen
    — that answers "may I edit this right now", and the question here is
    whether the row is this person's at all.
    """
    if request_bypasses_dac(
        guild_id,
        initiative_id=getattr(row, "initiative_id", None),
        access="write",
        guild_role=guild_role,
    ):
        return True
    level = effective_level(resource, row, user_id)
    return level in {lvl.value for lvl in WRITE_LEVELS}


def hidden_from_reader(
    kind: Tool,
    row: Any,
    user_id: int,
    *,
    guild_role: GuildRole | str | None = None,
) -> bool:
    """Whether this row exists but is not yet this caller's to see.

    Asked at every seam that resolves a single row by id — reading it,
    exporting it, commenting on it, reacting to it — so all of them answer the
    same way. Applied after the sharing decision, so it narrows what somebody
    already reaches rather than widening it.
    """
    visible = READ_VISIBLE.get(kind)
    if visible is None or visible(row):
        return False
    return not may_write(
        DAC_RESOURCES[kind],
        row,
        user_id,
        guild_id=getattr(row, "guild_id", None),
        guild_role=guild_role,
    )


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
        if getattr(g, "dashboard_id", None) is not None:
            # Reported by this shape, never taken by it: a published view is
            # made against the dashboard that publishes it. Silently dropping
            # one here would let a caller believe they had made a share that
            # was never written.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=SharingMessages.DASHBOARD_GRANT_NOT_SET_HERE,
            )
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

    # Sharing reaches somebody only where their role already lets them use the
    # tool. The picker offers that list; saying so here too means a caller that
    # does not go through it — the API, an agent — is told the same thing
    # rather than writing a grant that does nothing. A guild-level resource
    # belongs to no initiative, so no initiative role speaks for it.
    if not guild_scoped:
        # Local: rls imports this module.
        from app.models.tenant.initiative import PermissionKey
        from app.services import rls as rls_service

        tool = Tool(resource_type)
        view_key = PermissionKey(tool.view_permission)
        permitted_users = await rls_service.members_permitted(
            session,
            initiative_id=initiative_id,
            user_ids=valid_users,
            permission_key=view_key,
        )
        permitted_roles = await rls_service.roles_permitting(
            session,
            initiative_id=initiative_id,
            role_ids=valid_roles,
            permission_key=view_key,
        )
        if valid_users - permitted_users or valid_roles - permitted_roles:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=SharingMessages.grantee_lacks_tool(tool),
            )
        valid_users, valid_roles = permitted_users, permitted_roles

    existing = (
        await session.exec(
            select(ResourceGrant).where(
                ResourceGrant.resource_type == resource_type,
                ResourceGrant.resource_id == resource_id,
            )
        )
    ).all()
    for g in existing:
        if _grant_level(g.level) == "owner":
            continue
        if g.dashboard_id is not None:
            # A published view is not in this list, and is not this call's to
            # rebuild: a client that does not know about one would delete every
            # one of them by saving the panel. Revoking one is its own act,
            # made by the owner against the dashboard that published it.
            continue
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
    allow_frozen: bool = False,
) -> None:
    """Raise 403 unless ``user`` may act on ``row``: frozen-guild read cap →
    bypass (admin/PAM/Full access) → effective DAC level vs requested access.

    No initiative-scope step. The row was loaded through a routed session, and
    every content table's policy defers to ``public.initiative_access`` before
    anything here runs — a row belonging to an initiative the caller is not in
    does not arrive to be checked. What is left is the part the policies do not
    do: saying which refusal it is.

    ``allow_frozen`` is for the write that ENDS the frozen state — unarchiving,
    which asks for write on a row that is archived by definition. The caller
    still needs the write level."""
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
    # Archived or trashed content is read-only, and so is everything under it.
    # Not a permission answer — the caller may well own it — so it carries its
    # own code and its own status, and the thing to do is bring it back first.
    if not allow_frozen and row_is_frozen(row) and (access != "read" or require_owner):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=CommonMessages.CONTENT_IS_FROZEN,
        )
    if request_bypasses_dac(
        guild_id,
        initiative_id=initiative_id,
        access=access,
        require_owner=require_owner,
        guild_role=guild_role,
    ):
        return
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
    inherits it without re-deriving the status. Archived and trashed content
    caps it the same way and for the same reason: one place, so a document in
    the trash opens with its editor already read-only rather than failing on the
    first keystroke."""
    guild_id = getattr(row, "guild_id", None)
    initiative_id = getattr(row, "initiative_id", None)
    level: str | None
    if is_request_guild_admin(guild_id) or request_overrides_sharing(initiative_id):
        level = "owner"
    else:
        level = lift_level_for_grant(effective_level(resource, row, user_id), guild_id)
    if level is not None and content_read_only_active(guild_id):
        return "read"
    if level is not None and row_is_frozen(row):
        return "read"
    return level


def may_unarchive(resource: DacResource, row: Any, user_id: int) -> bool:
    """Whether the caller may take this row back out of the archive.

    ``compute_permission`` caps a frozen row at read so that every edit
    affordance goes off at once. Coming back out is a write too, and gating it
    on that capped level would shut the only door out of the state — so it is
    answered here instead, from the level the caller would have had if the row
    were live. The endpoint asks the same question its own way
    (``allow_frozen``), so the button and the handler agree.

    Two things have to hold. The caller could write it if it were live. And the
    stamp is the row's own: a row archived along with the thing above it comes
    back with that thing, which is what the database says too, so the answer
    here is no and the client points at the parent rather than offering a button
    that would be refused.

    A read-only guild answers no throughout — its hold is not the archive's to
    lift.
    """
    if getattr(row, "archived_at", None) is None:
        return False
    guild_id = getattr(row, "guild_id", None)
    if content_read_only_active(guild_id):
        return False
    if ancestor_is_frozen(row):
        return False
    initiative_id = getattr(row, "initiative_id", None)
    if is_request_guild_admin(guild_id) or request_overrides_sharing(initiative_id):
        return True
    level = lift_level_for_grant(effective_level(resource, row, user_id), guild_id)
    return level in ("write", "owner")


def client_access(tool: Tool, row: Any, user_id: int | None) -> dict[str, Any]:
    """The two access fields a tool's read schema carries, answered together.

    They are a pair. One says what may be done to the row as it stands — capped
    at read while it is archived, so every edit affordance goes off at once. The
    other says whether the caller may end that state. Answered in one place
    because a surface that reports the first without the second tells someone
    they may not edit a thing and nothing about how to get it back, which is the
    state every archived tool was in.

    Returned as a mapping so the pair travels into a serializer as one argument
    and neither half can be passed without the other.
    """
    if user_id is None:
        return {"my_permission_level": None, "can_unarchive": False}
    resource = DAC_RESOURCES[tool]
    return {
        "my_permission_level": compute_permission(resource, row, user_id),
        "can_unarchive": may_unarchive(resource, row, user_id),
    }


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


def compute_gallery_permission(gallery: Any, user_id: int) -> str | None:
    """Effective gallery permission string for the client (delegates to the
    engine). Write access on a gallery is what adding, replacing and removing
    its pictures asks for — the pictures are the gallery's content, the way
    tasks are a project's."""
    return compute_permission(DAC_RESOURCES[Tool.gallery], gallery, user_id)


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
