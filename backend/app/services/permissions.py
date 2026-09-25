"""Discretionary Access Control (DAC) — per-resource sharing.

The application-level permission layer for every tool. Unlike the mandatory RLS
layer (see ``rls.py``), which PostgreSQL enforces, this resolves what a request
may read, write or own from the ``resource_grants`` rows on a resource.

What is left here is what Postgres does not answer. The guild-schema policies
apply this same sharing rule to every content table — gate 4, rendered from
``app/db/initiative_rls.py`` and calling ``resource_access`` — so a
statement confined to one initiative needs no sharing clause of its own, and
the rung a request holds on a row is the schema's own ``resource_level``,
read off the loaded row by :func:`level_of`. The app layer keeps the
decisions the policies do not express:

  - :func:`require_access` — a *named* refusal on a loaded row, plus the
    frozen-guild cap
  - :func:`client_access` — what the client renders affordances from, the
    same checks the routes run (:data:`ACTIONS`)
  - :func:`granted_scope_clause` — deliberately NARROWER than the policy for a
    list spanning initiatives (no guild-admin leg)
  - :func:`writable_scope_clause` — "which of these may I change", which a read
    policy does not answer

Guild isolation and initiative membership are separate layers, in ``rls.py`` and
Postgres.
"""

from dataclasses import dataclass
from enum import Enum
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, and_, false, func, inspect, or_, true
from sqlmodel import select

from app.core.audit_events import AuditEventType
from app.db.guild_standing import ActorContext, InstallContext
from app.services import audit as audit_service
from app.core.tools import Tool

from app.models.platform.guild import GuildMembership
from app.models.tenant.project import Project
from app.models.tenant.initiative import InitiativeMember, InitiativeRoleModel
from app.db.frozen import ancestor_is_frozen, row_is_frozen
from app.db.authorization import standing_arg
from app.core.messages import (
    CommonMessages,
    ExportMessages,
    SharingMessages,
    ProjectMessages,
)
from app.models.tenant.resource_grant import (
    WRITE_LEVELS,
    ResourceAccessLevel,
    ResourceGrant,
)


def _frozen_community(context: ActorContext | None) -> bool:
    """Whether this request reads a community whose content is on hold.

    The routed role (``guild_<id>_ro``) refuses the write either way; the app
    layer agrees so every derived level reports read rather than offering an
    affordance the database will reject.
    """
    return context is not None and context.content_read_only


# ── Visibility subqueries ────────────────────────────────────────
# IDs of a resource the user can see, from resource_grants (one query). Run under
# RLS, so stale grants in an initiative the user left are already filtered out.


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


def granted_scope_clause(
    tool: Tool,
    id_col: ColumnElement[int],
    user_id: int | None,
    *,
    context: ActorContext | None,
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
    if isinstance(context, InstallContext):
        # An installed app is granted to by name or through its placements,
        # and has no admin leg to set aside: the table's own policy answers
        # exactly what reaches it.
        return true()
    if context is not None and context.grant_satisfies(access=access):
        return true()
    if user_id is None:
        raise ValueError("a listing for a person names the person")
    return id_col.in_(_granted_resource_ids(tool, user_id))


def listing_scope_clause(
    tool: Tool,
    id_col: ColumnElement[int],
    user_id: int | None,
    *,
    context: ActorContext | None,
    initiative_id: int | None = None,
    access: str = "read",
) -> ColumnElement[bool]:
    """The WHERE leg for a tool listing, picking the rule its scope calls for.

    **Confined to one initiative, there is nothing to add.** The question is the
    reader's standing there, and the table's own policy already asked it: every
    content table carries a sharing leg deferring to ``resource_access``
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
    return granted_scope_clause(tool, id_col, user_id, context=context, access=access)


def writable_scope_clause(
    tool: Tool,
    id_col: ColumnElement[int],
    user_id: int | None,
    *,
    context: ActorContext | None,
    initiative_id: int | None = None,
) -> ColumnElement[bool]:
    """The listing rule narrowed to what the reader may CHANGE.

    This one does NOT collapse the way :func:`listing_scope_clause` does. A read
    policy admits a row shared at any level, so "may I see it" is already
    answered and "may I edit it" is strictly narrower — the grant rows have to
    be filtered to :data:`WRITE_LEVELS` here, whatever the statement's scope.

    The two branches are the scope choice made elsewhere: confined to one
    initiative, the table's own gate answers, asked at write; spanning them,
    only what has been granted does.
    """
    if initiative_id is not None:
        return func.resource_access(
            tool.value, id_col, user_id, initiative_id, True, standing_arg()
        )
    if context is not None and context.grant_satisfies(access="write"):
        return true()
    if user_id is None:
        # Spanning initiatives, what may be changed is read from grants to a
        # person; an installed app asks one initiative at a time.
        return false()
    return id_col.in_(_granted_resource_ids(tool, user_id, levels=WRITE_LEVELS))


# ── Generic DAC engine (registry-driven) ─────────────────────────
# Every DAC resource resolves access from its ``grants`` (resource_grants rows)
# the same way — one registry row + one engine.


@dataclass(frozen=True)
class DacResource:
    """One tool's DAC identity: the tool itself, and the three refusals.

    The refusals are derived from ``name`` rather than stored, so a new
    ``Tool`` member arrives with its full set and none of them can be wired to
    another tool's code by a copy-paste.
    """

    name: Tool

    @property
    def denied_msg(self) -> str:
        return self.name.no_access_code

    @property
    def owner_msg(self) -> str:
        return self.name.owner_required_code

    @property
    def write_msg(self) -> str:
        return self.name.write_required_code


#: Every tool, by construction — ``tools_test`` has nothing to catch up on.
DAC_RESOURCES: dict[Tool, DacResource] = {t: DacResource(t) for t in Tool}
#: The same, by the table a tool's row is read from.
_RESOURCE_BY_TABLE: dict[str, DacResource] = {
    t.plural: r for t, r in DAC_RESOURCES.items()
}


def _grant_level(level: Any) -> str:
    return level.value if hasattr(level, "value") else level


#: The scope that lets an installed app see a resource's sharing.
SHARING_READ = "sharing:read"


def serialize_grants(row: Any, *, context: ActorContext | None) -> list:
    """Serialize a resource's eager-loaded ``grants`` into the unified grant list
    — one ``ResourceGrantSchema`` per ``resource_grants`` row (user, role,
    all-initiative-members, the dashboard a published view reads it
    through, or an installed app), owner included.

    An installed app sees the list only with ``sharing:read``; without it the
    list is empty. Who owns the resource is reported beside it either way."""
    from app.schemas.tenant.resource_grant import ResourceGrantSchema

    if isinstance(context, InstallContext) and not context.holds(SHARING_READ):
        return []
    return [
        ResourceGrantSchema(
            level=_grant_level(g.level),
            user_id=g.user_id,
            role_id=g.role_id,
            all_initiative_members=bool(getattr(g, "all_initiative_members", False)),
            dashboard_id=getattr(g, "dashboard_id", None),
            app_install_id=getattr(g, "app_install_id", None),
        )
        for g in getattr(row, "grants", None) or []
    ]


def level_of(row: Any) -> str | None:
    """The rung the request holds on ``row``, as the database answered it.

    Read off ``access_level``: mapped on every shareable model and asked of
    the schema's ``resource_level`` in the SELECT that loaded the row, so it
    was answered for the reader the session is routed as, under the standing
    the seam computed. A row loaded without it came through a loader that
    does not serialize, which is where to ask for it.
    """
    if "access_level" in inspect(row).unloaded:
        raise RuntimeError(
            f"{type(row).__name__} was loaded without its access level; "
            "undefer it in the loader"
        )
    level = row.access_level
    return _grant_level(level) if level is not None else None


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


def may_write(row: Any) -> bool:
    """Whether this caller could change the row.

    The row-shaped form of :func:`writable_scope_clause`: the rung the
    database answered, at :data:`WRITE_LEVELS`. Deliberately not
    ``allows(row, Action.edit)``, which is refused while a community is frozen
    — that answers "may I edit this right now", and the question here is
    whether the row is this person's at all.
    """
    return level_of(row) in {lvl.value for lvl in WRITE_LEVELS}


def hidden_from_reader(kind: Tool, row: Any) -> bool:
    """Whether this row exists but is not yet this caller's to see.

    Asked at every seam that resolves a single row by id — reading it,
    exporting it, commenting on it, reacting to it — so all of them answer the
    same way. Applied after the sharing decision, so it narrows what somebody
    already reaches rather than widening it.
    """
    visible = READ_VISIBLE.get(kind)
    if visible is None or visible(row):
        return False
    return not may_write(row)


#: One grantee of a resource: ``("user", id)``, ``("role", id)`` or
#: ``("all_members", None)``.
_Grantee = tuple[str, int | None]


def _levels_by_grantee(grants: Any) -> dict[_Grantee, str]:
    """The level each grantee holds, from a set of ``resource_grants`` rows.

    Owner rows, published-view rows and app-install rows are left out: none
    is part of the list a share is rebuilt from.
    """
    levels: dict[_Grantee, str] = {}
    for g in grants:
        if (
            _grant_level(g.level) == "owner"
            or g.dashboard_id is not None
            or g.app_install_id is not None
        ):
            continue
        if g.user_id is not None:
            key: _Grantee = ("user", g.user_id)
        elif g.role_id is not None:
            key = ("role", g.role_id)
        else:
            key = ("all_members", None)
        levels[key] = _grant_level(g.level)
    return levels


async def _record_grant_changes(
    session: Any,
    *,
    actor_user_id: int | None,
    resource_type: str,
    resource_id: int,
    guild_id: int,
    initiative_id: int | None,
    before: dict[_Grantee, str],
    after: dict[_Grantee, str],
) -> None:
    """One audit record per grantee whose level moved — granted, raised,
    lowered or withdrawn. A grantee that reads back the same level is not one
    of them. Staged in the caller's transaction, like every other record."""
    for key in sorted(before.keys() | after.keys(), key=repr):
        was, now = before.get(key), after.get(key)
        if was == now:
            continue
        kind, grantee_id = key
        await audit_service.record(
            session,
            event_type=AuditEventType.SHARING_GRANT_CHANGED,
            actor_user_id=actor_user_id,
            target_user_id=grantee_id if kind == "user" else None,
            guild_id=guild_id,
            target_type=getattr(resource_type, "value", resource_type),
            target_id=resource_id,
            detail={
                "initiative_id": initiative_id,
                "grantee": {"kind": kind, "id": grantee_id},
                "from": was,
                "to": now,
            },
        )


async def replace_resource_grants(
    session: Any,
    *,
    resource_type: str,
    resource_id: int,
    guild_id: int,
    initiative_id: int | None,
    owner_id: int | None,
    grants: Any,
    actor_user_id: int | None = None,
    by_install: bool = False,
) -> None:
    """Rebuild a resource's non-owner grants from ``grants`` (a list of
    ResourceAccessGrant rows). Each row is sorted by grantee kind — all-members,
    per-user, or per-role. The owner grant is preserved; owner-level entries and
    grantees outside the resource's scope are dropped. Caller commits.

    ``initiative_id`` is None for a guild-level resource. There "all members"
    means the guild's, and a named grantee is validated against guild
    membership; role grants are not resolvable (see below).

    ``owner_id`` is the person holding the owner grant, or None when nobody
    does or an installed app does; a named grantee equal to it is skipped.

    ``actor_user_id`` is who is making the change; pass it on any request path
    and the move of every grantee whose level actually changed is recorded in
    the same transaction. ``by_install`` records an installed app's change the
    same way, with no person as its actor. Left at neither, nothing is
    recorded."""
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
        if getattr(g, "app_install_id", None) is not None:
            # Reported by this shape, never taken by it: what an installed app
            # may reach is granted by the community's seat.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=SharingMessages.APP_INSTALL_GRANT_NOT_SET_HERE,
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
    before = _levels_by_grantee(existing)
    for g in existing:
        if _grant_level(g.level) == "owner":
            continue
        if g.dashboard_id is not None:
            # A published view is not in this list, and is not this call's to
            # rebuild: a client that does not know about one would delete every
            # one of them by saving the panel. Revoking one is its own act,
            # made by the owner against the dashboard that published it.
            continue
        if g.app_install_id is not None:
            # An installed app's grant is the seat's, not this list's, and
            # stays whatever the panel sends.
            continue
        await session.delete(g)

    await session.flush()

    def _grant(level: str, **kw: Any) -> ResourceGrant:
        return ResourceGrant(
            resource_type=resource_type,
            resource_id=resource_id,
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

    if actor_user_id is not None or by_install:
        after: dict[_Grantee, str] = {}
        if all_members_level is not None:
            after[("all_members", None)] = all_members_level
        after.update(
            {
                ("user", uid): level
                for uid, level in user_levels.items()
                if uid in valid_users
            }
        )
        after.update(
            {
                ("role", rid): level
                for rid, level in role_levels.items()
                if rid in valid_roles
            }
        )
        await _record_grant_changes(
            session,
            actor_user_id=actor_user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            guild_id=guild_id,
            initiative_id=initiative_id,
            before=before,
            after=after,
        )


class Action(str, Enum):
    """What somebody may do to one of a tool's rows, beyond reading it."""

    edit = "edit"
    delete = "delete"
    share = "share"
    export = "export"


#: What each action asks of the caller, as :func:`require_access` arguments.
#: The routes that do the thing pass these, and :func:`client_access` reports
#: the same checks to the client, so a flag and its guard cannot disagree.
#: Deleting a thing, changing who it is shared with and exporting it are the
#: owner's (full access to its initiative counts, as everywhere).
ACTIONS: dict[Action, dict[str, Any]] = {
    Action.edit: {"access": "write"},
    Action.delete: {"require_owner": True},
    Action.share: {"require_owner": True, "manage_access": True},
    Action.export: {"export": True},
}


def _refusal(
    resource: DacResource,
    row: Any,
    *,
    context: ActorContext | None,
    access: str = "read",
    require_owner: bool = False,
    manage_access: bool = False,
    export: bool = False,
    allow_frozen: bool = False,
) -> HTTPException | None:
    """Why the request may not act on ``row``, or ``None`` when it may.

    The body of :func:`require_access`, and of the flags :func:`client_access`
    reports."""
    # A frozen guild (read_only lifecycle status) caps EVERY real member at
    # read — before the level is read, so full authority does not clear it.
    # The flag is never set for PAM/break-glass requests, whose grants
    # override the status by design. An export changes nothing, so it is
    # answered from the rung alone.
    changes = (access != "read" or require_owner) and not export
    if changes and _frozen_community(context):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=resource.write_msg
        )
    # Archived or trashed content is read-only, and so is everything under it.
    # Not a permission answer — the caller may well own it — so it carries its
    # own code and its own status, and the thing to do is bring it back first.
    if changes and not allow_frozen and row_is_frozen(row):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=CommonMessages.CONTENT_IS_FROZEN,
        )
    # Sharing is the resource's own to give; a borrowed content grant does not
    # extend to it.
    if manage_access and context is not None and context.grant_content is not None:
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=resource.name.grant_cannot_manage_members_code,
        )
    effective = level_of(row)
    if export and effective != ResourceAccessLevel.owner.value:
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ExportMessages.EXPORT_OWNER_REQUIRED,
        )
    if require_owner and effective != ResourceAccessLevel.owner.value:
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=resource.owner_msg
        )
    if effective is None:
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=resource.denied_msg
        )
    if access == "write" and effective == ResourceAccessLevel.read.value:
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=resource.write_msg
        )
    return None


def require_access(
    resource: DacResource,
    row: Any,
    *,
    context: ActorContext | None,
    access: str = "read",
    require_owner: bool = False,
    manage_access: bool = False,
    export: bool = False,
    allow_frozen: bool = False,
) -> None:
    """Raise unless the request may act on ``row``: the community's hold, the
    row's archive, then the rung the database answered against what is asked.

    No initiative-scope step. The row was loaded through a routed session, and
    every content table's policy defers to ``initiative_access`` before
    anything here runs — a row belonging to an initiative the caller is not in
    does not arrive to be checked. What is left is the part the policies do not
    do: saying which refusal it is.

    An action spells its arguments from :data:`ACTIONS`. ``allow_frozen`` is
    for the write that ENDS the frozen state — unarchiving, which asks for
    write on a row that is archived by definition."""
    refusal = _refusal(
        resource,
        row,
        context=context,
        access=access,
        require_owner=require_owner,
        manage_access=manage_access,
        export=export,
        allow_frozen=allow_frozen,
    )
    if refusal is not None:
        raise refusal


def allows(row: Any, action: Action, *, context: ActorContext | None) -> bool:
    """Whether the request may take ``action`` on ``row`` — the answer
    :func:`require_access` gives the route that does it."""
    resource = _RESOURCE_BY_TABLE[row.__tablename__]
    return _refusal(resource, row, context=context, **ACTIONS[action]) is None


#: What exporting one tool asks for. An export hands the whole thing over at
#: once, so it takes the rung that may also delete it: an owner grant, or full
#: access to its initiative (its managers, the community's admins). The
#: initiative and community backups read what their scope reaches instead, and
#: pass ``"read"``.
EXPORT_ACCESS = "owner"


def require_export_access(
    resource: DacResource,
    row: Any,
    *,
    context: ActorContext | None,
    access: str = EXPORT_ACCESS,
) -> None:
    """Raise unless the request may export ``row``: :data:`ACTIONS`' export for
    a tool exported on its own, a read for one inside a backup."""
    if access == EXPORT_ACCESS:
        require_access(resource, row, context=context, **ACTIONS[Action.export])
    else:
        require_access(resource, row, context=context)


def may_unarchive(row: Any, *, context: ActorContext | None) -> bool:
    """Whether the caller may take this row back out of the archive.

    Every other change is refused while a row is archived, so this is answered
    from the level the caller would have had if the row were live — the
    endpoint asks the same question its own way (``allow_frozen``), so the
    button and the handler agree.

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
    if _frozen_community(context):
        return False
    if ancestor_is_frozen(row):
        return False
    return may_write(row)


def client_access(
    row: Any, user_id: int | None, *, context: ActorContext | None
) -> dict[str, bool]:
    """What the caller may do to ``row``, for its read schema's ``can``.

    Each flag is the check the route that does the thing runs, so the client
    reads its affordances rather than working them out from a rung."""
    if user_id is None and not isinstance(context, InstallContext):
        return {}
    return {
        **{action.value: allows(row, action, context=context) for action in Action},
        "unarchive": may_unarchive(row, context=context),
    }


# ── Project helpers above the generic engine ────────────────────


def can_configure_project(project: Project, *, context: ActorContext | None) -> bool:
    """Whether the request may configure the project itself.

    Configuring a project — pinning it, setting its default view, curating its
    filter presets — is a step above being able to edit its content. Three
    ways to hold it: a guild admin, a manager of the owning initiative, or the
    project's own owner. Plain write access is deliberately not enough, and
    nobody configures a project while it or its community is frozen.

    Read off the standing and the level the database answered, so the routes
    that configure a project and the ``can.configure`` a project reports are
    the same answer.
    """
    if context is None or _frozen_community(context) or row_is_frozen(project):
        return False
    if context.is_admin:
        return True
    # The owner's rung, which is what deleting it asks.
    if allows(project, Action.delete, context=context):
        return True
    return project.initiative_id in context.manager_initiatives


def require_project_configure(
    project: Project, *, context: ActorContext | None
) -> None:
    """Raise 403 unless the request may configure the project (see above)."""
    if not can_configure_project(project, context=context):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ProjectMessages.CONFIGURE_REQUIRED,
        )
