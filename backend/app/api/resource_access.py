"""Router-level resource authorization — one load-and-check choke point.

`authorize` is the single access decision (feature gate + manage block + DAC);
`load_authorized` and `resource_dependency` add loading on top for fetch-then-act
handlers and FastAPI-injected routes. `RESOURCE_ACCESS` is the enforcement-side
registry; `dac_kind` keys into `permissions.DAC_RESOURCES` (`None` = no per-row
DAC, e.g. calendar events — feature gate only).
"""

# NOT `from __future__ import annotations`: resource_dependency builds a signature
# with Annotated[int, Path(alias=cfg.path_param)] closing over a local; stringized
# annotations re-evaluate it where cfg is out of scope → FastAPI drops the path
# param and 422s.

from dataclasses import dataclass
from typing import Annotated, Any, Awaitable, Callable, Optional

from fastapi import Depends, HTTPException, Path, status

from app.api.deps import (
    GuildContext,
    RLSSessionDep,
    get_current_active_user,
    get_guild_membership,
)
from app.core.messages import (
    AdvancedToolMessages,
    CalendarEventMessages,
    CounterMessages,
    DocumentMessages,
    ProjectMessages,
    QueueMessages,
)
from app.core.pam_context import has_active_grant
from app.core.tools import Tool
from app.models.platform.guild import GuildRole
from app.models.platform.user import User
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.schemas.tenant.resource_grant import ResourceGrantSchema
from app.services import permissions as permissions_service
from app.services.tenant import advanced_tool as advanced_tool_service
from app.services.tenant import calendar_events as calendar_events_service
from app.services.tenant import counters as counters_service
from app.services.tenant import documents as documents_service
from app.services.tenant import project_grants
from app.services.tenant import queues as queues_service

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]
CurrentUserDep = Annotated[User, Depends(get_current_active_user)]


@dataclass(frozen=True)
class ResourceAccessConfig:
    dac_kind: Optional[Tool] = None  # key into DAC_RESOURCES; None = feature gate only
    feature_attr: Optional[str] = None  # initiative flag gating the feature
    feature_disabled_msg: Optional[str] = None
    grant_cannot_manage_msg: Optional[str] = None
    loader: Optional[Callable[..., Awaitable[Any]]] = (
        None  # async (session, id) -> row|None
    )
    path_param: Optional[str] = None
    not_found_msg: Optional[str] = None


RESOURCE_ACCESS: dict[Tool, ResourceAccessConfig] = {
    Tool.project: ResourceAccessConfig(
        dac_kind=Tool.project,
        grant_cannot_manage_msg=ProjectMessages.GRANT_CANNOT_MANAGE_MEMBERS,
        loader=project_grants.get_project,
        path_param="project_id",
        not_found_msg=ProjectMessages.NOT_FOUND,
    ),
    Tool.document: ResourceAccessConfig(
        dac_kind=Tool.document,
        grant_cannot_manage_msg=DocumentMessages.GRANT_CANNOT_MANAGE_MEMBERS,
        loader=documents_service.get_document_for_grants,
        path_param="document_id",
        not_found_msg=DocumentMessages.NOT_FOUND,
    ),
    Tool.queue: ResourceAccessConfig(
        dac_kind=Tool.queue,
        feature_attr=Tool.queue.view_permission,
        feature_disabled_msg=QueueMessages.FEATURE_DISABLED,
        loader=queues_service.get_queue,
        path_param="queue_id",
        not_found_msg=QueueMessages.NOT_FOUND,
    ),
    Tool.counter_group: ResourceAccessConfig(
        dac_kind=Tool.counter_group,
        feature_attr=Tool.counter_group.view_permission,
        feature_disabled_msg=CounterMessages.FEATURE_DISABLED,
        grant_cannot_manage_msg=CounterMessages.GRANT_CANNOT_MANAGE,
        loader=counters_service.get_counter_group,
        path_param="group_id",
        not_found_msg=CounterMessages.GROUP_NOT_FOUND,
    ),
    Tool.calendar_event: ResourceAccessConfig(
        dac_kind=Tool.calendar_event,
        feature_attr=Tool.calendar_event.view_permission,
        feature_disabled_msg=CalendarEventMessages.FEATURE_DISABLED,
        grant_cannot_manage_msg=CalendarEventMessages.GRANT_CANNOT_MANAGE_MEMBERS,
        loader=calendar_events_service.get_event,
        path_param="event_id",
        not_found_msg=CalendarEventMessages.NOT_FOUND,
    ),
    Tool.advanced_tool: ResourceAccessConfig(
        dac_kind=Tool.advanced_tool,
        # Only checked for initiative-scoped rows; a guild-wide advanced tool has
        # no initiative, so authorize() skips the feature gate (it's admin-only
        # by RLS instead).
        feature_attr=Tool.advanced_tool.view_permission,
        feature_disabled_msg=AdvancedToolMessages.NOT_ENABLED,
        grant_cannot_manage_msg=AdvancedToolMessages.GRANT_CANNOT_MANAGE_MEMBERS,
        loader=advanced_tool_service.get_advanced_tool,
        path_param="advanced_tool_id",
        not_found_msg=AdvancedToolMessages.NOT_FOUND,
    ),
}

# The tools whose sharing can be set through the unified *local* grant flow
# (``set_resource_grants`` / the bulk endpoint) — exactly the tools registered
# above, derived so the two never drift. (The advanced tool is a DAC tool but its
# grants are synced from the external automation service, not set here.)
GRANTABLE_KINDS: tuple[Tool, ...] = tuple(RESOURCE_ACCESS)


def authorize(
    kind: Tool,
    row: Any,
    user: Optional[User] = None,
    *,
    access: str = "read",
    require_owner: bool = False,
    manage_access: bool = False,
    guild_role: GuildRole | str | None = None,
) -> None:
    """Feature gate → manage-via-grant block → DAC decision. Reads request-scoped
    role/PAM context, so callers don't thread it."""
    cfg = RESOURCE_ACCESS[kind]
    initiative = getattr(row, "initiative", None)
    if (
        cfg.feature_attr
        and initiative is not None
        and not getattr(initiative, cfg.feature_attr)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=cfg.feature_disabled_msg
        )
    if (
        manage_access
        and cfg.grant_cannot_manage_msg
        and has_active_grant(getattr(row, "guild_id", None))
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=cfg.grant_cannot_manage_msg
        )
    if cfg.dac_kind is not None:
        permissions_service.require_access(
            permissions_service.DAC_RESOURCES[cfg.dac_kind],
            row,
            user,
            access=access,
            require_owner=require_owner,
            guild_role=guild_role,
        )


async def load_authorized(
    session: Any,
    kind: Tool,
    resource_id: int,
    user: User,
    guild_context: GuildContext,
    *,
    access: str = "read",
    require_owner: bool = False,
    manage_access: bool = False,
) -> Any:
    """Load by id (RLS scopes to the guild) → 404 if absent, then authorize."""
    cfg = RESOURCE_ACCESS[kind]
    if cfg.loader is None:
        # Config bug, not a request error: this entry is feature-gate only and
        # can't be loaded by id. Fail loudly rather than call None.
        raise RuntimeError(f"RESOURCE_ACCESS[{kind}] has no loader")
    row = await cfg.loader(session, resource_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=cfg.not_found_msg
        )
    authorize(
        kind,
        row,
        user,
        access=access,
        require_owner=require_owner,
        manage_access=manage_access,
        guild_role=guild_context.role,
    )
    return row


def resource_dependency(
    kind: Tool, access: str = "read", *, require_owner: bool = False
) -> Callable[..., Awaitable[Any]]:
    """FastAPI dependency injecting a pre-authorized resource (check before body)."""
    cfg = RESOURCE_ACCESS[kind]

    async def dependency(
        session: RLSSessionDep,
        current_user: CurrentUserDep,
        guild_context: GuildContextDep,
        resource_id: Annotated[int, Path(alias=cfg.path_param)],
    ) -> Any:
        return await load_authorized(
            session,
            kind,
            resource_id,
            current_user,
            guild_context,
            access=access,
            require_owner=require_owner,
        )

    return dependency


def my_permission_level(
    row: Any, kind: Tool, user: User, guild_context: GuildContext
) -> str | None:
    """`my_permission_level` for the client: guild admin → owner, else DAC."""
    cfg = RESOURCE_ACCESS[kind]
    if guild_context.role == GuildRole.admin:
        return "owner"
    return permissions_service.compute_permission(
        permissions_service.DAC_RESOURCES[cfg.dac_kind], row, user.id
    )


# ── Unified grant-set flow ───────────────────────────────────────────────────
# One code path for replacing a resource's sharing — used by every per-resource
# ``PUT /{id}/grants`` endpoint and by the bulk endpoint. The only per-kind
# variation is an optional post-change side effect (projects unassign anyone
# dropped below write access from the project's tasks).


@dataclass(frozen=True)
class GrantHooks:
    # raise to reject the change (e.g. archived project) — runs after authorization
    precheck: Optional[Callable[[Any], None]] = None
    # snapshot of who can write *before* the change, for diffing afterwards
    writers_before: Optional[Callable[[Any], set[int]]] = None
    # post-change hook: (session, reloaded_row, writers_before) -> None
    on_changed: Optional[Callable[..., Awaitable[None]]] = None


async def _project_on_grants_changed(
    session: Any, row: Any, writers_before: set[int]
) -> None:
    """Unassign anyone the grant change dropped below project write access — you
    can't be assigned to tasks you can no longer edit. Commits + reapplies RLS
    only when something actually changed."""
    demoted = writers_before - project_grants.write_holder_ids(row)
    if demoted:
        await project_grants.remove_user_task_assignments(session, row.id, demoted)
        await session.commit()


def _reject_guild_wide_sharing(row: Any) -> None:
    """A guild-wide advanced tool (no initiative) is admin-only and holds no
    grants — and ``resource_grants.initiative_id`` is NOT NULL, so a grant can't
    even be written. Reject sharing it rather than 500 on the constraint."""
    if getattr(row, "initiative_id", None) is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AdvancedToolMessages.GUILD_WIDE_NOT_SHAREABLE,
        )


GRANT_HOOKS: dict[Tool, GrantHooks] = {
    Tool.project: GrantHooks(
        precheck=project_grants.ensure_grantable,
        writers_before=project_grants.write_holder_ids,
        on_changed=_project_on_grants_changed,
    ),
    Tool.advanced_tool: GrantHooks(precheck=_reject_guild_wide_sharing),
}


def _resolve_owner_id(row: Any) -> Optional[int]:
    """The user holding the owner-level grant, else the resource's own owner /
    creator column. Mirrors the per-resource endpoints' owner handling — the owner
    grant is preserved server-side and the owner is never written as a non-owner
    grant."""
    for g in getattr(row, "grants", None) or []:
        if g.user_id is not None and g.level == ResourceAccessLevel.owner:
            return g.user_id
    return getattr(row, "owner_id", None) or getattr(row, "created_by_id", None)


async def set_resource_grants(
    session: Any,
    kind: Tool,
    resource_id: int,
    user: User,
    guild_context: GuildContext,
    grants: list[ResourceGrantSchema],
) -> None:
    """Replace one resource's sharing the unified way: load + 404, authorize
    *managing* access (``manage_access=True``), rebuild every non-owner grant from
    ``grants`` (owner preserved), then run the resource's optional post-change side
    effect. Commits. Raises ``HTTPException`` 404 (missing) / 403 (no manage
    access). The single source of truth behind the per-resource grant endpoints and
    the bulk endpoint."""
    row = await load_authorized(
        session,
        kind,
        resource_id,
        user,
        guild_context,
        access="write",
        manage_access=True,
    )
    hooks = GRANT_HOOKS.get(kind)
    if hooks and hooks.precheck:
        hooks.precheck(row)
    writers_before = (
        hooks.writers_before(row) if hooks and hooks.writers_before else None
    )

    await permissions_service.replace_resource_grants(
        session,
        resource_type=kind,
        resource_id=row.id,
        guild_id=row.guild_id,
        initiative_id=row.initiative_id,
        owner_id=_resolve_owner_id(row),
        grants=grants,
    )
    await session.commit()

    if hooks and hooks.on_changed:
        # replace_resource_grants rewrites resource_grants rows directly (by
        # resource_type/resource_id), so ``row.grants`` in the identity map is now
        # stale — refresh just that one collection (the memberships the diff needs
        # are untouched) rather than reloading the whole graph.
        await session.refresh(row, attribute_names=["grants"])
        await hooks.on_changed(session, row, writers_before or set())
