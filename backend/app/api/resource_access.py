"""Router-level resource authorization — one load-and-check choke point.

`authorize` is the single access decision (feature gate + manage block + DAC);
`load_authorized` and `resource_dependency` add loading on top for fetch-then-act
handlers and FastAPI-injected routes. `RESOURCE_ACCESS` is the enforcement-side
registry: one entry per `Tool`, carrying only how a row is loaded and addressed.
Everything it answers with is derived from the tool itself.
"""

# NOT `from __future__ import annotations`: resource_dependency builds a signature
# with Annotated[int, Path(alias=cfg.path_param)] closing over a local; stringized
# annotations re-evaluate it where cfg is out of scope → FastAPI drops the path
# param and 422s.

from dataclasses import dataclass
from typing import Annotated, Any, Awaitable, Callable, Optional

from fastapi import Depends, HTTPException, status

from app.api.deps import (
    ActorContext,
    GuildContext,
    get_current_active_user,
    get_guild_membership,
)
from app.core.app_scopes import AppScopeAccess, scope_name, tool_resource
from app.core.messages import AppMessages, InitiativeMessages
from app.core.tools import Tool
from app.db.guild_standing import InstallContext
from app.db.initiative_rls import governing_path
from app.models.tenant.initiative import Initiative, PermissionKey
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.models.platform.user import User
from app.schemas.tenant.resource_grant import ResourceGrantSchema, initiative_readable
from app.services import permissions as permissions_service
from app.services import rls as rls_service
from app.services import reachability
from app.services.tenant import ownership as ownership_service
from app.services.tenant import calendars as calendars_service
from app.services.tenant import counters as counters_service
from app.services.tenant import dashboards as dashboards_service
from app.services.tenant import documents as documents_service
from app.services.tenant import galleries as galleries_service
from app.services.tenant import wikis as wikis_service
from app.services.tenant import posts as posts_service
from app.services.tenant import project_grants
from app.services.tenant import queues as queues_service

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]
CurrentUserDep = Annotated[User, Depends(get_current_active_user)]


@dataclass(frozen=True)
class ResourceAccessConfig:
    """How one tool is loaded, and what it says when it refuses.

    Only the two things that are genuinely per-tool are stored: the function
    that loads a row, and the path segment it is addressed by. Every refusal is
    derived from ``tool``, so each tool has the full set and none of them can be
    written out by hand.
    """

    tool: Tool
    #: async (session, id) -> row | None
    loader: Callable[..., Awaitable[Any]]
    path_param: str
    #: async (session, id) -> row | None, for a handler that also *serializes*
    #: the row it authorized: the eager loads a read response reads off it.
    #: ``None`` where ``loader`` already carries them, which is most tools —
    #: only projects and documents answer with a graph wider than the decision
    #: needs, and loading that on every gate check would cost every caller a
    #: handful of queries none of them reads.
    hydrated_loader: Optional[Callable[..., Awaitable[Any]]] = None

    @property
    def dac_kind(self) -> Tool:
        """Key into ``permissions.DAC_RESOURCES``."""
        return self.tool

    @property
    def not_found_msg(self) -> str:
        return self.tool.not_found_code

    @property
    def feature_attr(self) -> str:
        """The initiative flag gating the whole tool."""
        return self.tool.view_permission

    @property
    def feature_disabled_msg(self) -> str:
        return self.tool.feature_disabled_code

    @property
    def grant_cannot_manage_msg(self) -> str:
        return self.tool.grant_cannot_manage_members_code

    @property
    def create_denied_msg(self) -> str:
        return self.tool.create_permission_code


RESOURCE_ACCESS: dict[Tool, ResourceAccessConfig] = {
    Tool.project: ResourceAccessConfig(
        Tool.project,
        project_grants.get_project,
        "project_id",
        hydrated_loader=project_grants.get_project_hydrated,
    ),
    Tool.document: ResourceAccessConfig(
        Tool.document,
        documents_service.get_document_for_grants,
        "document_id",
        hydrated_loader=documents_service.get_document_hydrated,
    ),
    Tool.queue: ResourceAccessConfig(Tool.queue, queues_service.get_queue, "queue_id"),
    Tool.counter_group: ResourceAccessConfig(
        Tool.counter_group, counters_service.get_counter_group, "group_id"
    ),
    Tool.calendar: ResourceAccessConfig(
        Tool.calendar, calendars_service.get_calendar, "calendar_id"
    ),
    Tool.dashboard: ResourceAccessConfig(
        Tool.dashboard, dashboards_service.get_dashboard, "dashboard_id"
    ),
    Tool.post: ResourceAccessConfig(Tool.post, posts_service.get_post, "post_id"),
    Tool.gallery: ResourceAccessConfig(
        Tool.gallery, galleries_service.get_gallery, "gallery_id"
    ),
    Tool.wiki: ResourceAccessConfig(Tool.wiki, wikis_service.get_wiki, "wiki_id"),
}


# The tools whose sharing can be set through the unified *local* grant flow
# (``set_resource_grants`` / the bulk endpoint) — exactly the tools registered
# above, derived so the two never drift.
GRANTABLE_KINDS: tuple[Tool, ...] = tuple(RESOURCE_ACCESS)


def governing_tool(table: str) -> Tool:
    """The tool whose sharing governs one content table's rows.

    Read from ``initiative_rls.governing_path`` — the same registry the table's
    RLS policy is rendered from — so an endpoint that reaches a sub-resource's
    parent cannot name a different tool from the one the database asked about.
    A task's is ``project``, and it is one edit away from staying that way if
    the hierarchy ever changes.
    """
    path = governing_path(table)
    if path is None:
        # Config bug, not a request error: the caller named a table whose
        # governing tool is a property of the row (a comment, a reaction) or
        # that no tool's sharing governs at all.
        raise RuntimeError(f"no single tool governs {table!r}")
    return path[0]


def require_tool_enabled(kind: Tool, initiative: Any) -> None:
    """Raise 403 unless ``initiative`` has ``kind``'s master switch on.

    Gate 3's first half at the moment of creation, where there is no row yet for
    ``require_access`` to read the switch off. The message comes from the
    registry, so a tool is gated by registering it rather than by spelling the
    refusal again at each create endpoint.

    The database asks the same question on INSERT — the rendered policy's
    ``{plural}_enabled`` leg. This runs first so the answer is a named 403
    rather than a row that silently fails to appear.
    """
    attr = RESOURCE_ACCESS[kind].feature_attr
    if attr is not None and not getattr(initiative, attr):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=RESOURCE_ACCESS[kind].feature_disabled_msg,
        )


async def require_create(
    session: Any,
    kind: Tool,
    initiative: Any,
    user: Optional[User],
    guild_context: ActorContext,
) -> None:
    """Raise 403 unless this caller may create a ``kind`` in ``initiative``.

    Gate 3 at the moment of creation: the initiative role's create right for
    the tool, with a guild admin above it. The permission key comes from the
    tool (``Tool.create_permission``) and the message from the registry, so a
    ninth tool is gated by registering it rather than by copying this.

    The database asks the same question on INSERT — the rendered policy's
    ``initiative_role_permits(..., create_<plural>, false)`` leg. This one runs
    first so the answer is a named 403.
    """
    if guild_context.is_admin:
        return
    if await rls_service.check_initiative_permission(
        session,
        initiative_id=initiative.id,
        user=user,
        permission_key=PermissionKey(kind.create_permission),
    ):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=RESOURCE_ACCESS[kind].create_denied_msg,
    )


async def prepare_create(
    session: Any,
    kind: Tool,
    initiative_id: int,
    user: Optional[User],
    guild_context: ActorContext,
) -> Initiative:
    """The initiative a new ``kind`` goes into, once the caller may make one
    there: it exists (404), its switch for the tool is on
    (:func:`require_tool_enabled`) and the caller's role may create the tool
    (:func:`require_create`). Every tool's create and duplicate start here.
    """
    initiative = await session.get(Initiative, initiative_id)
    if initiative is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=InitiativeMessages.NOT_FOUND,
        )
    require_tool_enabled(kind, initiative)
    await require_create(session, kind, initiative, user, guild_context)
    return initiative


def duplicate_sharing(source: Any, *, initiative_id: int) -> list[ResourceGrantSchema]:
    """Who a duplicate of ``source`` is shared with: the same people and roles
    as ``source`` while it stays in the same initiative, where they exist, and
    the create default when it goes to another. ``source.grants`` is loaded."""
    if initiative_id != source.initiative_id:
        return initiative_readable()
    return [
        ResourceGrantSchema.model_validate(grant)
        for grant in source.grants
        if grant.level != ResourceAccessLevel.owner
        and grant.dashboard_id is None
        and grant.app_install_id is None
    ]


#: The scope an installed app holds to change a resource's sharing.
SHARING_WRITE = "sharing:write"

#: What else an installed app's sharing change reads: the initiative's roster,
#: and the roles on it, which validate the grantees and settle who keeps
#: write access afterwards.
_SHARING_READS = ("members:read", "initiatives:read")


def refuse_app_sharing(actor: ActorContext, payload: Any, *fields: str) -> None:
    """Raise 403 when an installed app's create sets any of ``fields`` — its
    initial sharing — without ``sharing:write``.

    What an app creates is owned by its install, whose owner row the tool
    table's trigger writes. With the scope, the initial sharing is applied as
    a later share would be (:func:`apply_app_initial_sharing`). A field left at
    its default is not a request to share, so only the ones the payload sets
    are refused.
    """
    if not isinstance(actor, InstallContext):
        return
    if not any(field in payload.model_fields_set for field in fields):
        return
    require_install_may_share(actor, None)


def require_install_may_share(actor: ActorContext, kind: Optional[Tool]) -> None:
    """Raise 403 unless an installed app's standing lets it change sharing:
    ``sharing:write``, the tool's write scope when ``kind`` is named, and the
    roster reads a sharing change makes. A person passes; their rung on the
    resource is asked by :func:`authorize`, as the install's is too.
    """
    if not isinstance(actor, InstallContext):
        return
    if not actor.holds(SHARING_WRITE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AppMessages.SHARING_NOT_AVAILABLE,
        )
    needed = list(_SHARING_READS)
    if kind is not None:
        needed.append(scope_name(tool_resource(kind), AppScopeAccess.write))
    if not all(actor.holds(scope) for scope in needed):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AppMessages.SCOPE_REQUIRED,
        )


def refuse_install_community_share(
    actor: ActorContext, initiative_id: Optional[int]
) -> None:
    """Raise 403 when an installed app would share a resource that belongs to
    no initiative. Such a resource is shared with the community's members,
    whom an app does not read."""
    if isinstance(actor, InstallContext) and initiative_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AppMessages.SHARING_NOT_AVAILABLE,
        )


async def apply_app_initial_sharing(
    session: Any,
    actor: ActorContext,
    kind: Tool,
    *,
    resource_id: int,
    initiative_id: Optional[int],
    payload: Any,
    grants: list[ResourceGrantSchema],
) -> None:
    """Apply the initial sharing an installed app's create asked for.

    Only when the payload set ``grants``: an app's content is otherwise shared
    with nobody beyond its owner row until it shares it. The install's own
    owner row went in with the resource, so its rung there is the owner's, and
    the database asks the same of each grant row it writes. Caller flushes.
    """
    if not isinstance(actor, InstallContext):
        return
    if "grants" not in payload.model_fields_set:
        return
    require_install_may_share(actor, kind)
    refuse_install_community_share(actor, initiative_id)
    await permissions_service.replace_resource_grants(
        session,
        resource_type=kind.value,
        resource_id=resource_id,
        guild_id=actor.guild_id,
        initiative_id=initiative_id,
        # A member token's creation is owned by the member it acts for.
        owner_id=actor.member_user_id,
        grants=grants,
        by_install=True,
    )


async def grant_initial_sharing(
    session: Any,
    actor: ActorContext,
    kind: Tool,
    *,
    user: Optional[User],
    resource_id: int,
    initiative_id: Optional[int],
    payload: Any,
    grants: list[ResourceGrantSchema],
) -> None:
    """Share a resource that has just been made: its maker owns it, and
    ``grants`` says who else may reach it.

    A person gets the owner row here. An installed app's is written by the
    table's own trigger as the row goes in, and only the sharing its create
    asked for is applied (:func:`apply_app_initial_sharing`). The row is
    flushed first; the caller commits.
    """
    owner = ownership_service.creator_owner_grant(
        actor, tool=kind, resource_id=resource_id, initiative_id=initiative_id
    )
    if owner is None or user is None:
        await apply_app_initial_sharing(
            session,
            actor,
            kind,
            resource_id=resource_id,
            initiative_id=initiative_id,
            payload=payload,
            grants=grants,
        )
        return
    session.add(owner)
    await permissions_service.replace_resource_grants(
        session,
        resource_type=kind.value,
        resource_id=resource_id,
        guild_id=actor.guild_id,
        initiative_id=initiative_id,
        owner_id=user.id,
        grants=grants,
        actor_user_id=user.id,
    )


def authorize(
    kind: Tool,
    row: Any,
    user: Optional[User] = None,
    *,
    context: Optional[ActorContext],
    access: str = "read",
    require_owner: bool = False,
    manage_access: bool = False,
    allow_frozen: bool = False,
) -> None:
    """Feature gate → manage-via-grant block → DAC decision.

    ``context`` is the reader's standing in the community, as the seam computed
    it — the same object the session was routed with, so what this decides and
    what the policies evaluate are the same facts.

    ``allow_frozen`` belongs to unarchiving and to nothing else — see
    ``permissions_service.require_access``."""
    cfg = RESOURCE_ACCESS[kind]
    initiative = getattr(row, "initiative", None)
    if initiative is not None and not getattr(initiative, cfg.feature_attr):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=cfg.feature_disabled_msg
        )
    if (
        manage_access
        and cfg.grant_cannot_manage_msg
        and context is not None
        and context.grant_content is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=cfg.grant_cannot_manage_msg
        )
    permissions_service.require_access(
        permissions_service.DAC_RESOURCES[cfg.dac_kind],
        row,
        context=context,
        access=access,
        allow_frozen=allow_frozen,
        require_owner=require_owner,
    )
    # Last, and only for somebody the sharing already admitted: a row that
    # exists before it is anybody's to read — a post that has not gone up.
    # Answering 404 here rather than 403 is the point; to a reader the
    # notice does not exist yet.
    reader = user is not None or (context is not None and context.user_id is None)
    if reader and permissions_service.hidden_from_reader(cfg.dac_kind, row):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=cfg.not_found_msg,
        )


async def load_authorized(
    session: Any,
    kind: Tool,
    resource_id: int,
    user: Optional[User],
    guild_context: ActorContext,
    *,
    access: str = "read",
    require_owner: bool = False,
    manage_access: bool = False,
    hydrated: bool = False,
) -> Any:
    """Load by id (RLS scopes to the guild) → 404 if absent, then authorize.

    ``hydrated=True`` takes the tool's wider loader, for a handler that goes on
    to serialize the row it just authorized.
    """
    cfg = RESOURCE_ACCESS[kind]
    loader = cfg.hydrated_loader if hydrated and cfg.hydrated_loader else cfg.loader
    row = await loader(session, resource_id)
    if row is None:
        if user is not None and await reachability.reader_is_in_the_initiative(
            kind.plural, resource_id, user.id, guild_context.guild_id
        ):
            # In the initiative, so the row is theirs to know about — sharing is
            # what refused it, and "denied" is the answer to that.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=cfg.not_found_msg
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=cfg.not_found_msg
        )
    authorize(
        kind,
        row,
        user,
        context=guild_context,
        access=access,
        require_owner=require_owner,
        manage_access=manage_access,
    )
    return row


# ── Unified grant-set flow ───────────────────────────────────────────────────
# One code path for replacing a resource's sharing — used by every per-resource
# ``PUT /{id}/grants`` endpoint and by the bulk endpoint. The only per-kind
# variation is an optional post-change side effect (projects unassign anyone
# dropped below write access from the project's tasks).


@dataclass(frozen=True)
class GrantHooks:
    # raise to reject the change (e.g. archived project) — runs after authorization
    precheck: Optional[Callable[[Any], None]] = None
    # who can write *before* the change, for diffing afterwards
    writers_before: Optional[Callable[[Any, Any], Awaitable[set[int]]]] = None
    # post-change hook: (session, reloaded_row, writers_before) -> None
    on_changed: Optional[Callable[..., Awaitable[None]]] = None


async def _project_on_grants_changed(
    session: Any, row: Any, writers_before: set[int]
) -> None:
    """Unassign anyone the grant change dropped below project write access — you
    can't be assigned to tasks you can no longer edit. Commits + reapplies RLS
    only when something actually changed."""
    demoted = writers_before - await project_grants.write_holder_ids(session, row)
    if demoted:
        await project_grants.remove_user_task_assignments(session, row.id, demoted)
        await session.commit()


GRANT_HOOKS: dict[Tool, GrantHooks] = {
    Tool.project: GrantHooks(
        precheck=project_grants.ensure_grantable,
        writers_before=project_grants.write_holder_ids,
        on_changed=_project_on_grants_changed,
    ),
}


async def set_resource_grants(
    session: Any,
    kind: Tool,
    resource_id: int,
    user: Optional[User],
    guild_context: ActorContext,
    grants: list[ResourceGrantSchema],
) -> None:
    """Replace one resource's sharing the unified way: load + 404, authorize
    *managing* access (``manage_access=True``), rebuild every non-owner grant from
    ``grants`` (owner preserved), then run the resource's optional post-change side
    effect. Commits. Raises ``HTTPException`` 404 (missing) / 403 (no manage
    access). The single source of truth behind the per-resource grant endpoints and
    the bulk endpoint.

    An installed app changes sharing where a person with its rung could, and
    only with ``sharing:write`` and the tool's write scope
    (:func:`require_install_may_share`)."""
    require_install_may_share(guild_context, kind)
    row = await load_authorized(
        session,
        kind,
        resource_id,
        user,
        guild_context,
        access="write",
        manage_access=True,
    )
    refuse_install_community_share(guild_context, row.initiative_id)
    hooks = GRANT_HOOKS.get(kind)
    if hooks and hooks.precheck:
        hooks.precheck(row)
    writers_before = (
        await hooks.writers_before(session, row)
        if hooks and hooks.writers_before
        else None
    )

    await permissions_service.replace_resource_grants(
        session,
        resource_type=kind,
        resource_id=row.id,
        guild_id=guild_context.guild_id,
        initiative_id=row.initiative_id,
        owner_id=ownership_service.owner_user_id_of(row),
        grants=grants,
        actor_user_id=guild_context.user_id,
        by_install=isinstance(guild_context, InstallContext),
    )
    await session.commit()

    if hooks and hooks.on_changed:
        # replace_resource_grants rewrites resource_grants rows directly (by
        # resource_type/resource_id), so ``row.grants`` in the identity map is now
        # stale — refresh just that one collection rather than the whole graph.
        await session.refresh(row, attribute_names=["grants"])
        await hooks.on_changed(session, row, writers_before or set())
