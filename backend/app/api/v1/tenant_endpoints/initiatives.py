from typing import Annotated, List, Optional, Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import selectinload, undefer
from sqlmodel import select

from app.db.session import routed_guild_id
from app.api.actor_route import ActorRoute
from app.api.deps import (
    ActorContext,
    ActorSessionDep,
    ActorUserDep,
    IncludeDeletedDep,
    RLSSessionDep,
    app_scope,
    SessionDep,
    get_current_active_user,
    get_guild_membership,
    GuildContext,
    require_guild_roles,
)
from app.core.audit_events import AuditEventType
from app.core.messages import (
    AuthMessages,
    GuildMessages,
    InitiativeMessages,
    UserMessages,
)
from app.core.tools import Tool
from app.models.tenant.initiative import (
    Initiative,
    InitiativeJoinRequest,
    InitiativeMember,
    InitiativeRoleModel,
    JoinRequestStatus,
    LOCKED_PERMISSION_ROLE_NAMES,
)
from app.models.platform.guild import GuildRole
from app.models.platform.notification import NotificationType
from app.models.platform.user import User
from app.models.platform.user_profile_view import MemberProfile
from app.schemas.tenant.initiative import (
    InitiativeCreate,
    InitiativeDirectoryEntry,
    InitiativeJoinRequestCreate,
    InitiativeJoinRequestRead,
    InitiativeListScope,
    InitiativeMemberAdd,
    InitiativeMemberUpdate,
    InitiativeRead,
    InitiativeRoleCreate,
    InitiativeRoleRead,
    InitiativeRoleUpdate,
    InitiativeUpdate,
    serialize_initiative,
    serialize_role,
)
from app.schemas.platform.user import (
    UserPublic,
    UserSummaryListResponse,
)
from app.db.query import MAX_ID_FILTER_VALUES, page_has_next, paginated_query
from app.services import audit as audit_service
from app.services import email as email_service
from app.services import notifications as notifications_service
from app.services.platform import accounts as accounts_service
from app.services.tenant import initiatives as initiatives_service
from app.services.platform import guilds as guilds_service
from app.services.platform import users as users_service
from app.services.content_sockets import sockets as content_sockets
from app.services import rls as rls_service
from app.services.membership import initiative_scope_clause

GuildAdminContext = Annotated[
    GuildContext, Depends(require_guild_roles(GuildRole.admin))
]

router = APIRouter(route_class=ActorRoute)

#: The routes an installed app may call, under the initiatives scope.
InitiativesRead = Annotated[ActorContext, Depends(app_scope("initiatives:read"))]


def _roster_options(guild_context: ActorContext) -> tuple:
    """What an initiative read loads beside the row: what the caller may do in
    it, its roster, each member's profile, and each member's role with its
    permissions.

    An installed app is not given what each role permits (the role permission
    rows are not in its reach), so its read leaves them unloaded and each
    member's tool flags come from the role's manager fact, the defaults and the
    initiative's switches."""
    role = selectinload(Initiative.memberships).selectinload(InitiativeMember.role_ref)
    return (
        undefer(Initiative.actions),
        selectinload(Initiative.memberships).selectinload(InitiativeMember.user),
        role.noload(InitiativeRoleModel.permissions)
        if guild_context.user_id is None
        else role.selectinload(InitiativeRoleModel.permissions),
    )


def _reaches_whole_guild(guild_context: ActorContext) -> bool:
    """Whether this request reads every initiative in the guild without holding
    a membership row: a guild admin, or a live PAM / break-glass grantee."""
    return guild_context.is_pam or guild_context.is_admin


async def _record_membership(
    session: SessionDep,
    *,
    event_type: AuditEventType,
    actor_user_id: int,
    member_user_id: int,
    initiative_id: int,
    guild_id: int,
    detail: dict,
) -> None:
    """One membership record: whose membership, in which initiative, and what
    the change was. Staged beside the write it describes."""
    await audit_service.record(
        session,
        event_type=event_type,
        actor_user_id=actor_user_id,
        target_user_id=member_user_id,
        guild_id=guild_id,
        target_type="initiative",
        target_id=initiative_id,
        detail=detail,
    )


#: What a record of a role edit reports on beyond its permissions.
_ROLE_AUDIT_FIELDS = ("display_name", "is_manager")


def _role_permissions(role: InitiativeRoleModel) -> dict[str, bool]:
    """A role's permission toggles, by key."""
    return {
        getattr(p.permission_key, "value", p.permission_key): p.enabled
        for p in role.permissions
    }


async def _get_initiative_or_404(
    initiative_id: int,
    session: SessionDep,
    guild_id: int | None = None,
) -> Initiative:
    """Get an initiative with memberships and role information loaded."""
    statement = (
        select(Initiative)
        .where(Initiative.id == initiative_id)
        .execution_options(populate_existing=True)
        .options(
            undefer(Initiative.actions),
            selectinload(Initiative.memberships).selectinload(InitiativeMember.user),
            selectinload(Initiative.memberships)
            .selectinload(InitiativeMember.role_ref)
            .selectinload(InitiativeRoleModel.permissions),
        )
    )
    result = await session.exec(statement)
    initiative = result.one_or_none()
    if not initiative:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=InitiativeMessages.NOT_FOUND
        )
    return initiative


async def _initiative_name_exists(
    session: SessionDep,
    name: str,
    *,
    guild_id: int,
    exclude_initiative_id: int | None = None,
) -> bool:
    normalized = name.strip().lower()
    if not normalized:
        return False
    statement = select(Initiative.id).where(
        func.lower(Initiative.name) == normalized,
    )
    if exclude_initiative_id is not None:
        statement = statement.where(Initiative.id != exclude_initiative_id)
    result = await session.exec(statement)
    return result.first() is not None


async def _require_manager_access(
    session: SessionDep,
    initiative: Initiative,
    current_user: User,
    *,
    guild_context: GuildContext | None = None,
) -> None:
    """Require that the user has manager-level access to the initiative."""
    if guild_context is not None and guild_context.is_admin:
        return
    is_manager = (
        initiative.id in guild_context.manager_initiatives
        if guild_context is not None
        else await rls_service.is_initiative_manager(
            session, initiative_id=initiative.id
        )
    )
    if not is_manager:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=InitiativeMessages.MANAGER_REQUIRED,
        )


async def _guard_guild_admin_role(
    session: SessionDep,
    *,
    guild_id: int,
    target_user_id: int,
    role: InitiativeRoleModel | None,
) -> None:
    """Restrict which initiative roles a guild admin may be assigned.

    A guild admin already has complete access to every initiative in their
    guild (see ``GuildContext.is_admin``), so their membership
    row carries a manager role — purely for manager-style features like
    notifications — and never a standard member or custom one. Every route that
    *creates* a row settles that itself
    (:func:`initiatives_service.resolve_membership_role`); this is the backstop
    for the one route that only ever changes an existing role, where silently
    substituting would answer a question nobody asked.
    """
    if role is not None and role.is_manager:
        return  # manager role is the one allowed elevation for an admin
    if await initiatives_service.is_guild_admin_member(
        session, guild_id=guild_id, user_id=target_user_id
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=InitiativeMessages.GUILD_ADMIN_ROLE_RESTRICTED,
        )


async def _guard_full_access_role(
    session: SessionDep,
    *,
    guild_id: int,
    target_user_id: int,
    role: InitiativeRoleModel | None,
    guild_context: GuildContext,
) -> None:
    """Restrict who may be placed on a role carrying "Full access".

    A guild admin settles that one. Every other role — the other manager roles
    included — stays an initiative manager's to assign.

    A guild admin as the *target* is the exception: their standing already
    reaches every initiative in the guild, so the role adds nothing to it, and
    this is the route a project manager brings an admin in by.
    """
    if role is None or not role.override_share_restrictions:
        return
    if guild_context.is_admin:
        return
    if await initiatives_service.is_guild_admin_member(
        session, guild_id=guild_id, user_id=target_user_id
    ):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=InitiativeMessages.OVERRIDE_REQUIRES_GUILD_ADMIN,
    )


async def _ensure_remaining_manager(
    session: SessionDep,
    initiative: Initiative,
    *,
    exclude_user_ids: set[int] | None = None,
) -> None:
    """Ensure at least one manager remains after excluding certain users."""
    try:
        await initiatives_service.ensure_managers_remain(
            session,
            initiative_id=initiative.id,
            excluded_user_ids=exclude_user_ids,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ============================================================================
# Initiative CRUD
# ============================================================================


@router.get("/", response_model=List[InitiativeRead])
async def list_initiatives(
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: InitiativesRead,
    scope: Annotated[InitiativeListScope, Query()] = InitiativeListScope.member,
) -> List[InitiativeRead]:
    """The initiatives the caller belongs to, or — for a guild admin asking for
    ``scope=guild`` — every initiative in the guild.

    The default is the caller's own workspace: what the sidebar and the
    initiative pickers show. A guild admin's authority over their whole guild is
    unchanged; it simply no longer decides what appears in their navigation.
    They bring an initiative into it by taking the project manager role from the
    guild-settings initiative table, which is also what ``scope=guild`` feeds.
    """
    if scope is InitiativeListScope.guild and not guild_context.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildMessages.GUILD_ADMIN_REQUIRED,
        )

    # `initiatives` is a structural table (not initiative-RLS-gated), so scope it
    # in the query. The guild-wide listing uses the ONE access rule —
    # initiative_scope_clause defers to initiative_access (admin OR PAM OR
    # member, from the request GUCs), the same predicate the content-table RLS
    # uses. A time-bound grantee holds no memberships in the guild, so their
    # session stays on that predicate too: the grant is what they navigate by.
    # An installed app's workspace is the initiatives it is placed in, which
    # its standing carries.
    if current_user is None:
        scope_clause = Initiative.id.in_(guild_context.member_initiatives)
    elif scope is InitiativeListScope.guild or guild_context.is_pam:
        scope_clause = initiative_scope_clause(current_user.id, Initiative.id)
    else:
        scope_clause = Initiative.id.in_(
            select(InitiativeMember.initiative_id).where(
                InitiativeMember.user_id == current_user.id
            )
        )

    statement = (
        select(Initiative)
        .where(
            scope_clause,
        )
        .options(*_roster_options(guild_context))
    )
    result = await session.exec(statement)
    initiatives = result.all()
    return [
        serialize_initiative(initiative, context=guild_context)
        for initiative in initiatives
    ]


@router.get("/directory", response_model=List[InitiativeDirectoryEntry])
async def list_initiative_directory(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> List[InitiativeDirectoryEntry]:
    """Initiatives in this guild that any member may discover and join.

    Open to every guild member — it lists only what each initiative published
    about itself (name, description, colour, roster size), never its content.
    Initiatives whose policy is ``private`` are listed only to their own
    members, guild admins included: an admin's authority over the guild is
    unchanged, but the front page shows what they are in and what is on offer,
    read the same way for everyone. ``/initiatives/?scope=guild`` is the
    whole-guild listing, and guild settings is where it is managed.

    Declared before ``/{initiative_id}`` so the literal path wins the match.
    """
    return await initiatives_service.list_directory_entries(
        session,
        guild_id=guild_context.guild_id,
        user_id=current_user.id,
        is_guild_admin=guild_context.is_admin,
    )


@router.post("/{initiative_id}/join", response_model=InitiativeRead)
async def join_initiative(
    initiative_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> InitiativeRead:
    """Join an ``open`` initiative as yourself, with the built-in member role.

    Idempotent: already being a member is a success, not a conflict. Any other
    join policy answers 403 — the same answer for ``private`` and ``request``,
    so it says only "not by this route".

    A guild admin walks in whatever the policy says, and on the manager role:
    the queue exists to exercise an authority they already hold, and staffing
    themselves onto an initiative is how they bring it into their own
    navigation. It is the same act as ticking themselves in guild settings.
    """
    # A grantee reaches this guild for a window; the membership row this would
    # create has no end date, so joining is for real guild members.
    if guild_context.is_pam:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=InitiativeMessages.GRANT_CANNOT_MANAGE_MEMBERS,
        )
    initiative = await _get_initiative_or_404(
        initiative_id, session, guild_context.guild_id
    )
    if (
        not initiatives_service.is_self_joinable(initiative)
        and not guild_context.is_admin
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=InitiativeMessages.NOT_JOINABLE,
        )
    try:
        await initiatives_service.self_join(
            session, initiative=initiative, user_id=current_user.id
        )
    except ValueError:
        # An initiative missing its built-in member role can't take a joiner.
        # The code is the contract; the exception text is not.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=InitiativeMessages.MEMBER_ROLE_NOT_FOUND,
        )
    await session.commit()
    initiative = await _get_initiative_or_404(
        initiative_id, session, guild_context.guild_id
    )
    return serialize_initiative(initiative, context=guild_context)


# ============================================================================
# Join requests (join_policy == 'request')
# ============================================================================


def _require_no_scoped_grant(guild_context: GuildContext) -> None:
    """A scoped grantee may not create or answer a join request.

    A grant reaches the guild for a window; the membership row on the other side
    of an approval has no end date, so the two are never traded for each other.
    """
    if guild_context.is_pam:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=InitiativeMessages.GRANT_CANNOT_MANAGE_MEMBERS,
        )


async def _load_pending_join_request(
    session: SessionDep,
    *,
    request_id: int,
    initiative_id: int,
) -> InitiativeJoinRequest:
    """One request of this initiative that is still open to an answer."""
    request = await initiatives_service.get_join_request(
        session, request_id=request_id, initiative_id=initiative_id
    )
    if request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=InitiativeMessages.JOIN_REQUEST_NOT_FOUND,
        )
    if request.status != JoinRequestStatus.pending.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=InitiativeMessages.JOIN_REQUEST_ALREADY_RESOLVED,
        )
    return request


async def _resolve_join_request(
    initiative_id: int,
    request_id: int,
    session: SessionDep,
    current_user: User,
    guild_context: GuildContext,
    *,
    approved: bool,
) -> InitiativeJoinRequestRead:
    """Shared body of approve and deny: same authority, same lifecycle, one
    boolean apart."""
    _require_no_scoped_grant(guild_context)
    initiative = await _get_initiative_or_404(
        initiative_id, session, guild_context.guild_id
    )
    # Answering a request grants access, so it takes exactly the authority that
    # adding a member by hand takes — no separate rule to keep in step.
    await _require_manager_access(
        session, initiative, current_user, guild_context=guild_context
    )
    request = await _load_pending_join_request(
        session, request_id=request_id, initiative_id=initiative_id
    )
    requester = await accounts_service.load_one(request.user_id)
    if requester is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND
        )
    try:
        await initiatives_service.resolve_join_request(
            session, request=request, resolver_id=current_user.id, approved=approved
        )
    except initiatives_service.JoinRequestAlreadyResolved:
        # Another manager answered it between the check above and this write.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=InitiativeMessages.JOIN_REQUEST_ALREADY_RESOLVED,
        )
    except ValueError:
        # The initiative's built-in member role is missing, so it can take no
        # joiner. The code is the contract; the exception text is not.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=InitiativeMessages.MEMBER_ROLE_NOT_FOUND,
        )
    await session.commit()

    outcome = "approved" if approved else "denied"
    await notifications_service.notify(
        session,
        NotificationType.initiative_join_approved
        if approved
        else NotificationType.initiative_join_denied,
        [requester.id],
        about=None,
        key=f"initiative.join{outcome.capitalize()}",
        values={"initiative": initiative.name},
        data={
            "request_id": request.id,
            "initiative_id": initiative.id,
            # An approval opens the initiative, whose membership now exists; a
            # denial the community's front page, which is as far as they go.
            "target_path": f"/i/{initiative.id}" if approved else "/",
        },
        email=lambda reader: email_service.initiative_join_request_pieces(
            reader, event=outcome, initiative_name=initiative.name
        ),
        email_names_line=False,
    )
    await session.commit()

    rows = await initiatives_service.list_join_requests(
        session,
        initiative_id=initiative_id,
        status=None,
        user_id=request.user_id,
    )
    return next(row for row in rows if row.id == request.id)


@router.post(
    "/{initiative_id}/join-requests",
    response_model=InitiativeJoinRequestRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_join_request(
    initiative_id: int,
    payload: InitiativeJoinRequestCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> InitiativeJoinRequestRead:
    """Knock on a ``request`` initiative and wait for a manager to answer.

    Any other join policy answers 403 — the same answer for ``private`` and
    ``open`` alike, so it says only "not by this route" and a private initiative
    stays exactly as hidden as it was.

    Being refused before does not bar asking again: only a *pending* request is
    unique, and the refusals stay on file so the manager reading the queue can
    see the repeat.
    """
    _require_no_scoped_grant(guild_context)
    initiative = await _get_initiative_or_404(
        initiative_id, session, guild_context.guild_id
    )
    if not initiatives_service.is_requestable(initiative):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=InitiativeMessages.NOT_REQUESTABLE,
        )
    # A guild admin holds the authority this queue exercises, so they walk in
    # (``POST /join``, which takes them whatever the policy says) rather than
    # knocking and waiting for a member to answer.
    if guild_context.is_admin:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=InitiativeMessages.GUILD_ADMIN_NEED_NOT_REQUEST,
        )
    if any(m.user_id == current_user.id for m in initiative.memberships):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=InitiativeMessages.ALREADY_A_MEMBER,
        )

    request, created = await initiatives_service.create_join_request(
        session,
        initiative=initiative,
        user_id=current_user.id,
        message=payload.message,
    )
    if not created:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=InitiativeMessages.JOIN_REQUEST_ALREADY_PENDING,
        )
    request_id = request.id
    await session.commit()

    manager_ids = await initiatives_service.manager_user_ids(
        session, initiative_id=initiative_id
    )
    if manager_ids:
        requester = notifications_service.actor_name(current_user)
        # Addressed to the people who can answer it, and straight to the queue
        # they answer it in. It carries no initiative content: who asked, what
        # they said, and where to answer.
        await notifications_service.notify(
            session,
            NotificationType.initiative_join_requested,
            list(manager_ids),
            about=None,
            key="initiative.joinRequested",
            values={"requester": requester, "initiative": initiative.name},
            data={
                "request_id": request_id,
                "initiative_id": initiative.id,
                "requester_id": current_user.id,
                "requester_name": requester,
                "target_path": f"/i/{initiative.id}/settings/members",
            },
            actor=current_user,
            email=lambda reader: email_service.initiative_join_request_pieces(
                reader,
                event="requested",
                initiative_name=initiative.name,
                requester=requester,
                message=payload.message,
            ),
            email_names_line=False,
        )
        await session.commit()

    rows = await initiatives_service.list_join_requests(
        session, initiative_id=initiative_id, status=None, user_id=current_user.id
    )
    return next(row for row in rows if row.id == request_id)


@router.get(
    "/{initiative_id}/join-requests/me",
    response_model=List[InitiativeJoinRequestRead],
)
async def list_my_join_requests(
    initiative_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> List[InitiativeJoinRequestRead]:
    """The caller's own knocks at this door, newest first.

    ``initiative_join_requests`` is a guild-level table — the schema boundary is
    its only database gate, because a requester is by definition not yet a
    member and an initiative-membership gate would hide their own row from them.
    So who may read which rows is decided here: this route is scoped to the
    caller's ``user_id`` and nothing else, and the queue below is manager-only.
    """
    await _get_initiative_or_404(initiative_id, session, guild_context.guild_id)
    return await initiatives_service.list_join_requests(
        session,
        initiative_id=initiative_id,
        status=None,
        user_id=current_user.id,
    )


@router.get(
    "/{initiative_id}/join-requests",
    response_model=List[InitiativeJoinRequestRead],
)
async def list_join_requests(
    initiative_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
    request_status: Annotated[
        JoinRequestStatus | None,
        Query(
            alias="status",
            description=(
                "Narrow the queue to one status. Omit for the pending queue — "
                "the rows that are still open to an answer."
            ),
        ),
    ] = None,
) -> List[InitiativeJoinRequestRead]:
    """The join-request queue for one initiative.

    Manager-only, matching who may answer it; a plain member of the initiative
    has no more business reading who asked to get in than a non-member does. A
    requester reads their own rows through ``/join-requests/me`` instead.
    """
    initiative = await _get_initiative_or_404(
        initiative_id, session, guild_context.guild_id
    )
    await _require_manager_access(
        session, initiative, current_user, guild_context=guild_context
    )
    return await initiatives_service.list_join_requests(
        session,
        initiative_id=initiative_id,
        status=(
            request_status.value
            if request_status is not None
            else JoinRequestStatus.pending.value
        ),
    )


@router.post(
    "/{initiative_id}/join-requests/{request_id}/approve",
    response_model=InitiativeJoinRequestRead,
)
async def approve_join_request(
    initiative_id: int,
    request_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> InitiativeJoinRequestRead:
    """Let the requester in, with the built-in ``member`` role.

    The membership row is the one every join path produces, so the requester's
    access flips through ``initiative_access`` with no policy change. Someone who
    became a member by another route while the request waited is absorbed: the
    row is resolved and the call succeeds.
    """
    return await _resolve_join_request(
        initiative_id,
        request_id,
        session,
        current_user,
        guild_context,
        approved=True,
    )


@router.post(
    "/{initiative_id}/join-requests/{request_id}/deny",
    response_model=InitiativeJoinRequestRead,
)
async def deny_join_request(
    initiative_id: int,
    request_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> InitiativeJoinRequestRead:
    """Turn the request down. No membership row, so nothing about what the
    requester can see changes; the row stays as history, and they may ask
    again."""
    return await _resolve_join_request(
        initiative_id,
        request_id,
        session,
        current_user,
        guild_context,
        approved=False,
    )


@router.get("/{initiative_id}", response_model=InitiativeRead)
async def get_initiative(
    initiative_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: InitiativesRead,
    include_deleted: IncludeDeletedDep = False,
) -> InitiativeRead:
    statement = (
        select(Initiative)
        .where(
            Initiative.id == initiative_id,
        )
        .options(*_roster_options(guild_context))
    )
    result = await session.exec(statement)
    initiative = result.first()
    # An installed app reads the initiatives it is placed in; any other is not
    # there for it.
    if not initiative or (
        current_user is None and initiative.id not in guild_context.member_initiatives
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=InitiativeMessages.NOT_FOUND
        )
    # Reachable by an initiative member, by a guild admin (the same override the
    # RLS admin leg grants), and by a PAM / break-glass grantee — who holds no
    # membership row in this guild and reads it through the grant for its window.
    if current_user is not None and not _reaches_whole_guild(guild_context):
        is_member = any(m.user_id == current_user.id for m in initiative.memberships)
        if not is_member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=InitiativeMessages.NOT_A_MEMBER,
            )
    return serialize_initiative(initiative, context=guild_context)


@router.post("/", response_model=InitiativeRead, status_code=status.HTTP_201_CREATED)
async def create_initiative(
    initiative_in: InitiativeCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[
        GuildContext, Depends(require_guild_roles(GuildRole.admin))
    ],
) -> InitiativeRead:
    guild_id = guild_context.guild_id
    if await _initiative_name_exists(session, initiative_in.name, guild_id=guild_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=InitiativeMessages.NAME_EXISTS
        )
    initiative = Initiative(
        name=initiative_in.name,
        description=initiative_in.description,
        join_policy=initiative_in.join_policy.value,
        # One master switch per toggleable tool, derived — a new Tool member
        # flows through without touching this endpoint.
        **{t.view_permission: getattr(initiative_in, t.view_permission) for t in Tool},
    )
    if initiative_in.color:
        initiative.color = initiative_in.color
    session.add(initiative)
    await session.flush()

    # Create built-in roles for this initiative
    roles = await initiatives_service.create_builtin_roles(
        session, initiative_id=initiative.id
    )

    # Add the creator: a guild admin on the moderator role, anyone else as the
    # project manager of what they just made.
    creator_role = await initiatives_service.creator_role(
        session, guild_id=guild_id, user_id=current_user.id, roles=roles
    )
    session.add(
        InitiativeMember(
            initiative_id=initiative.id,
            user_id=current_user.id,
            role_id=creator_role.id,
        )
    )
    await _record_membership(
        session,
        event_type=AuditEventType.INITIATIVE_MEMBER_ADDED,
        actor_user_id=current_user.id,
        member_user_id=current_user.id,
        initiative_id=initiative.id,
        guild_id=guild_id,
        detail={
            "role_id": creator_role.id,
            "role": creator_role.name,
            "via": "created",
        },
    )
    await session.commit()
    initiative = await _get_initiative_or_404(initiative.id, session, guild_id)
    return serialize_initiative(initiative, context=guild_context)


@router.patch("/{initiative_id}", response_model=InitiativeRead)
async def update_initiative(
    initiative_id: int,
    initiative_in: InitiativeUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> InitiativeRead:
    initiative = await _get_initiative_or_404(
        initiative_id, session, guild_context.guild_id
    )
    await _require_manager_access(
        session, initiative, current_user, guild_context=guild_context
    )

    update_data = initiative_in.model_dump(exclude_unset=True)
    # Auto-join enrols every future guild member, so it shapes onboarding for
    # the whole guild rather than for one initiative — guild admins only, the
    # same shape as the archive toggle above. join_policy stays with whoever may
    # already edit the initiative.
    if (
        update_data.get("auto_join") is not None
        and update_data["auto_join"] != initiative.auto_join
        and not guild_context.is_admin
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=InitiativeMessages.AUTO_JOIN_ADMIN_ONLY,
        )
    if "join_policy" in update_data or "auto_join" in update_data:
        # The column stores the plain string, so normalize whichever form the
        # payload validated into before comparing or persisting.
        join_policy = update_data.get("join_policy")
        join_policy = getattr(join_policy, "value", join_policy)
        try:
            initiatives_service.validate_join_settings(
                initiative,
                join_policy=join_policy,
                auto_join=update_data.get("auto_join"),
            )
        except ValueError:
            # The only way the pair is incoherent. The code is the contract;
            # the exception text is not.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=InitiativeMessages.AUTO_JOIN_REQUIRES_OPEN,
            )
        if join_policy is not None:
            update_data["join_policy"] = join_policy
    if "name" in update_data and update_data["name"] is not None:
        if await _initiative_name_exists(
            session,
            update_data["name"],
            guild_id=routed_guild_id(session),
            exclude_initiative_id=initiative_id,
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=InitiativeMessages.NAME_EXISTS,
            )
    for field, value in update_data.items():
        setattr(initiative, field, value)
    session.add(initiative)
    await session.commit()
    initiative = await _get_initiative_or_404(
        initiative_id, session, guild_context.guild_id
    )
    return serialize_initiative(initiative, context=guild_context)


@router.delete("/{initiative_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_initiative(
    initiative_id: int,
    session: RLSSessionDep,
    guild_context: GuildAdminContext,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> None:
    """Soft-delete an initiative. Cascades the same deleted_at to its
    projects, documents, queues, and calendar events; their descendants
    (tasks, comments, queue items) follow recursively. Restoring the
    initiative resurfaces everything that was cascaded together."""
    from app.services.tenant.soft_delete import trash

    initiative = await _get_initiative_or_404(
        initiative_id, session, guild_context.guild_id
    )
    if initiative.is_default:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=InitiativeMessages.CANNOT_DELETE_DEFAULT,
        )
    retention_days = await trash(
        session,
        initiative,
        deleted_by_user_id=current_user.id,
    )
    await audit_service.record(
        session,
        event_type=AuditEventType.INITIATIVE_DELETED,
        actor_user_id=current_user.id,
        guild_id=guild_context.guild_id,
        target_type="initiative",
        target_id=initiative_id,
        detail={"via": "trash", "retention_days": retention_days},
    )
    await session.commit()


# ============================================================================
# Role CRUD
# ============================================================================


@router.get("/{initiative_id}/roles", response_model=List[InitiativeRoleRead])
async def list_initiative_roles(
    initiative_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> List[InitiativeRoleRead]:
    """List all roles for an initiative with their permissions."""
    initiative = await _get_initiative_or_404(
        initiative_id, session, guild_context.guild_id
    )

    # Same readership as the initiative itself: member, guild admin, or grantee.
    if not _reaches_whole_guild(guild_context):
        is_member = any(m.user_id == current_user.id for m in initiative.memberships)
        if not is_member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=InitiativeMessages.NOT_A_MEMBER,
            )

    roles = await initiatives_service.list_initiative_roles(
        session, initiative_id=initiative_id
    )

    # Get member counts for each role
    result = []
    for role in roles:
        member_count = await initiatives_service.count_role_members(
            session, role_id=role.id
        )
        result.append(serialize_role(role, member_count=member_count))
    return result


@router.post(
    "/{initiative_id}/roles",
    response_model=InitiativeRoleRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_initiative_role(
    initiative_id: int,
    role_in: InitiativeRoleCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> InitiativeRoleRead:
    """Create a new custom role for an initiative."""
    initiative = await _get_initiative_or_404(
        initiative_id, session, guild_context.guild_id
    )
    await _require_manager_access(
        session, initiative, current_user, guild_context=guild_context
    )

    # Check for duplicate name
    existing = await initiatives_service.get_role_by_name(
        session, initiative_id=initiative_id, role_name=role_in.name
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=InitiativeMessages.ROLE_NAME_EXISTS,
        )

    role = await initiatives_service.create_custom_role(
        session,
        initiative_id=initiative_id,
        name=role_in.name,
        display_name=role_in.display_name,
        is_manager=role_in.is_manager,
        permissions=role_in.permissions,
    )
    await audit_service.record(
        session,
        event_type=AuditEventType.INITIATIVE_ROLE_CREATED,
        actor_user_id=current_user.id,
        guild_id=guild_context.guild_id,
        target_type="initiative_role",
        target_id=role.id,
        detail={
            "initiative_id": initiative_id,
            "name": role.name,
            "is_manager": role.is_manager,
            "permissions": _role_permissions(role),
        },
    )
    await session.commit()
    return serialize_role(role, member_count=0)


@router.patch("/{initiative_id}/roles/{role_id}", response_model=InitiativeRoleRead)
async def update_initiative_role(
    initiative_id: int,
    role_id: int,
    role_in: InitiativeRoleUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> InitiativeRoleRead:
    """Update a role's display name and/or permissions.

    Note: the built-ins that already hold every permission (moderator, project
    manager) cannot have theirs changed, to prevent lockouts.
    """
    initiative = await _get_initiative_or_404(
        initiative_id, session, guild_context.guild_id
    )
    await _require_manager_access(
        session, initiative, current_user, guild_context=guild_context
    )

    role = await initiatives_service.get_role_by_id(
        session, role_id=role_id, initiative_id=initiative_id
    )
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=InitiativeMessages.ROLE_NOT_FOUND,
        )

    # The built-ins that hold every permission have nothing to configure.
    if role.name in LOCKED_PERMISSION_ROLE_NAMES and role_in.permissions is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=InitiativeMessages.CANNOT_MODIFY_BUILTIN_PERMISSIONS,
        )

    before = audit_service.snapshot(role, _ROLE_AUDIT_FIELDS)
    before_permissions = _role_permissions(role)

    # Update display name if provided
    if role_in.display_name is not None:
        role.display_name = role_in.display_name
        session.add(role)

    # Update is_manager if provided (not for built-in roles)
    if role_in.is_manager is not None:
        if role.is_builtin:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=InitiativeMessages.CANNOT_CHANGE_BUILTIN_MANAGER,
            )
        # If demoting from manager, ensure at least one manager remains
        if role.is_manager and not role_in.is_manager:
            # First check if this role has any members - if not, demotion is safe
            this_role_members = await initiatives_service.count_role_members(
                session, role_id=role_id
            )
            if this_role_members > 0:
                # Count managers excluding members with this role
                stmt = (
                    select(func.count())
                    .select_from(InitiativeMember)
                    .join(
                        InitiativeRoleModel,
                        InitiativeRoleModel.id == InitiativeMember.role_id,
                    )
                    .where(
                        InitiativeMember.initiative_id == initiative_id,
                        InitiativeRoleModel.is_manager.is_(True),
                        InitiativeRoleModel.id != role_id,
                    )
                )
                result = await session.exec(stmt)
                other_managers = result.one()
                if other_managers == 0:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=InitiativeMessages.MUST_HAVE_MANAGER,
                    )
        role.is_manager = role_in.is_manager
        session.add(role)

    # Update permissions if provided
    if role_in.permissions is not None:
        role = await initiatives_service.update_role_permissions(
            session, role=role, permissions=role_in.permissions
        )

    changed = audit_service.changed_fields(
        before, audit_service.snapshot(role, _ROLE_AUDIT_FIELDS)
    )
    after_permissions = _role_permissions(role)
    permissions_changed = {
        key: {"from": before_permissions.get(key), "to": after_permissions[key]}
        for key in after_permissions
        if before_permissions.get(key) != after_permissions[key]
    }
    if changed["changed"] or permissions_changed:
        await audit_service.record(
            session,
            event_type=AuditEventType.INITIATIVE_ROLE_UPDATED,
            actor_user_id=current_user.id,
            guild_id=guild_context.guild_id,
            target_type="initiative_role",
            target_id=role.id,
            detail={
                "initiative_id": initiative_id,
                "name": role.name,
                **changed,
                "permissions_changed": permissions_changed,
            },
        )

    await session.commit()
    member_count = await initiatives_service.count_role_members(
        session, role_id=role.id
    )
    return serialize_role(role, member_count=member_count)


@router.delete(
    "/{initiative_id}/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_initiative_role(
    initiative_id: int,
    role_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> None:
    """Delete a custom role. Built-in roles cannot be deleted."""
    initiative = await _get_initiative_or_404(
        initiative_id, session, guild_context.guild_id
    )
    await _require_manager_access(
        session, initiative, current_user, guild_context=guild_context
    )

    role = await initiatives_service.get_role_by_id(
        session, role_id=role_id, initiative_id=initiative_id
    )
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=InitiativeMessages.ROLE_NOT_FOUND,
        )

    role_name = role.name
    try:
        await initiatives_service.delete_role(session, role=role)
        await audit_service.record(
            session,
            event_type=AuditEventType.INITIATIVE_ROLE_DELETED,
            actor_user_id=current_user.id,
            guild_id=guild_context.guild_id,
            target_type="initiative_role",
            target_id=role_id,
            detail={"initiative_id": initiative_id, "name": role_name},
        )
        await session.commit()
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ============================================================================
# Member management
# ============================================================================


@router.get("/{initiative_id}/members", response_model=List[UserPublic])
async def get_initiative_members(
    initiative_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> Sequence[MemberProfile]:
    """Get all members of an initiative."""
    await _get_initiative_or_404(initiative_id, session, guild_context.guild_id)

    # Check that user has access to this initiative
    membership = await initiatives_service.get_initiative_membership(
        session,
        initiative_id=initiative_id,
        user_id=current_user.id,
    )
    # A guild admin sees every initiative in their guild without holding a
    # membership row (the same override the RLS admin leg grants), and a PAM /
    # break-glass grantee has guild-wide read access but no membership row;
    # both may load the member roster (used for assignee and linked-member
    # pickers). There is no standing ``data.bypass`` bypass — a platform
    # operator/owner reaches this guild only via a grant, which surfaces as
    # ``is_pam``.
    if not membership and not guild_context.is_pam and not guild_context.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=InitiativeMessages.NOT_A_MEMBER,
        )

    # Get all initiative members
    stmt = (
        select(MemberProfile)
        .join(InitiativeMember, InitiativeMember.user_id == MemberProfile.id)
        .where(
            InitiativeMember.initiative_id == initiative_id,
            users_service.visible_to_other_people(),
        )
        .order_by(MemberProfile.username, MemberProfile.discriminator, MemberProfile.id)
    )
    result = await session.exec(stmt)
    return result.all()


@router.get("/{initiative_id}/members/search", response_model=UserSummaryListResponse)
async def search_initiative_members(
    initiative_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
    search: Optional[str] = Query(
        default=None,
        description="Case-insensitive substring match on the member's name.",
    ),
    user_id: Annotated[list[int] | None, Query(max_length=MAX_ID_FILTER_VALUES)] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=0, le=100),
) -> UserSummaryListResponse:
    """Slim, searchable, paginated roster of an initiative's members.

    Same authorization as :func:`get_initiative_members` (member, guild
    admin, or PAM/break-glass grantee); the search/id/pagination params are
    additive filters on the already-RLS-gated query. Returns
    :class:`UserSummary` for typeahead/picker surfaces instead of the full
    ``UserPublic`` roster.

    Pass ``user_id`` one or more times to resolve a known selection (a picker
    rehydrating stored ids into names/avatars) rather than searching.
    """
    await _get_initiative_or_404(initiative_id, session, guild_context.guild_id)

    membership = await initiatives_service.get_initiative_membership(
        session,
        initiative_id=initiative_id,
        user_id=current_user.id,
    )
    if not membership and not guild_context.is_pam and not guild_context.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=InitiativeMessages.NOT_A_MEMBER,
        )

    base = (
        select(MemberProfile)
        .join(InitiativeMember, InitiativeMember.user_id == MemberProfile.id)
        .where(
            InitiativeMember.initiative_id == initiative_id,
            users_service.visible_to_other_people(),
        )
    )
    shows_names = bool(guild_context.guild.show_member_names)
    closest = None
    if search and (term := search.strip()):
        matches, closest = users_service.member_match(term, shows_names=shows_names)
        base = base.where(matches)
    if user_id:
        base = base.where(MemberProfile.id.in_(user_id))

    count_stmt = select(func.count()).select_from(base.subquery())
    data_stmt = base.order_by(
        *users_service.member_order(closest, shows_names=shows_names),
        MemberProfile.username.asc(),
        MemberProfile.discriminator.asc(),
        MemberProfile.id.asc(),
    )

    users, total_count, actual_page = await paginated_query(
        session, data_stmt, count_stmt, page=page, page_size=page_size
    )

    return UserSummaryListResponse(
        items=await users_service.summaries_with_guild_role(
            session, guild_context.guild_id, users
        ),
        total_count=total_count,
        page=actual_page,
        page_size=page_size,
        has_next=page_has_next(actual_page, page_size, total_count),
        has_prev=actual_page > 1,
    )


@router.post(
    "/{initiative_id}/members",
    response_model=InitiativeRead,
    status_code=status.HTTP_200_OK,
)
async def add_initiative_member(
    initiative_id: int,
    payload: InitiativeMemberAdd,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> InitiativeRead:
    """Add a member to an initiative or update their role.

    Any project manager may bring in any member of the guild, guild admins
    included — an admin simply lands on the manager role their standing already
    implies, whatever role the invite named.
    """
    initiative = await _get_initiative_or_404(
        initiative_id, session, guild_context.guild_id
    )
    await _require_manager_access(
        session,
        initiative,
        current_user,
        guild_context=guild_context,
    )

    user_stmt = await session.exec(
        select(MemberProfile).where(MemberProfile.id == payload.user_id)
    )
    user = user_stmt.one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND
        )
    guild_membership = await guilds_service.get_membership(
        session,
        guild_id=routed_guild_id(session),
        user_id=user.id,
    )
    if not guild_membership:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=UserMessages.NOT_IN_GUILD,
        )

    requested_role = None
    if payload.role_id is not None:
        # Verify role exists and belongs to this initiative
        requested_role = await initiatives_service.get_role_by_id(
            session, role_id=payload.role_id, initiative_id=initiative_id
        )
        if not requested_role:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=InitiativeMessages.ROLE_NOT_FOUND,
            )

    await _guard_full_access_role(
        session,
        guild_id=routed_guild_id(session),
        target_user_id=payload.user_id,
        role=requested_role,
        guild_context=guild_context,
    )

    # The role the row actually takes: what was asked for, the built-in member
    # role when nothing was, or the moderator role for a guild admin — whose
    # standing already reaches the initiative. Settling it here is what lets a
    # project manager invite an admin without knowing they are one.
    resolved_role = await initiatives_service.resolve_membership_role(
        session,
        initiative=initiative,
        user_id=payload.user_id,
        requested=requested_role,
    )
    if not resolved_role:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=InitiativeMessages.MEMBER_ROLE_NOT_FOUND,
        )
    role_id = resolved_role.id

    stmt = select(InitiativeMember).where(
        InitiativeMember.initiative_id == initiative_id,
        InitiativeMember.user_id == payload.user_id,
    )
    result = await session.exec(stmt)
    membership = result.one_or_none()
    created = False

    if membership:
        if membership.role_id != role_id:
            # Check if demoting from manager role
            old_role = await initiatives_service.get_role_by_id(
                session, role_id=membership.role_id
            )
            new_role = await initiatives_service.get_role_by_id(
                session, role_id=role_id
            )
            if (
                old_role
                and old_role.is_manager
                and (not new_role or not new_role.is_manager)
            ):
                await _ensure_remaining_manager(
                    session, initiative, exclude_user_ids={membership.user_id}
                )
            from_role_id = membership.role_id
            membership.role_id = role_id
            session.add(membership)
            await _record_membership(
                session,
                event_type=AuditEventType.INITIATIVE_MEMBER_ROLE_CHANGED,
                actor_user_id=current_user.id,
                member_user_id=payload.user_id,
                initiative_id=initiative_id,
                guild_id=routed_guild_id(session),
                detail={
                    "from_role_id": from_role_id,
                    "from": old_role.name if old_role else None,
                    "to_role_id": role_id,
                    "to": resolved_role.name,
                },
            )
    else:
        membership = InitiativeMember(
            initiative_id=initiative_id,
            user_id=payload.user_id,
            role_id=role_id,
        )
        session.add(membership)
        created = True
        await _record_membership(
            session,
            event_type=AuditEventType.INITIATIVE_MEMBER_ADDED,
            actor_user_id=current_user.id,
            member_user_id=payload.user_id,
            initiative_id=initiative_id,
            guild_id=routed_guild_id(session),
            detail={
                "role_id": role_id,
                "role": resolved_role.name,
                "via": "manager",
            },
        )

    await session.commit()
    # Re-fetch initiative with updated memberships
    initiative = await _get_initiative_or_404(
        initiative_id, session, guild_context.guild_id
    )
    if created:
        await notifications_service.notify(
            session,
            NotificationType.initiative_added,
            [user.id],
            about=None,
            key="initiative.added",
            values={"initiative": initiative.name},
            data={
                "initiative_id": initiative.id,
                "target_path": f"/i/{initiative.id}",
            },
            email=lambda reader: email_service.initiative_added_pieces(
                reader, initiative.name
            ),
        )
        await session.commit()
    return serialize_initiative(initiative, context=guild_context)


@router.delete("/{initiative_id}/members/{user_id}", response_model=InitiativeRead)
async def remove_initiative_member(
    initiative_id: int,
    user_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> InitiativeRead:
    """Remove a member from an initiative."""
    initiative = await _get_initiative_or_404(
        initiative_id, session, guild_context.guild_id
    )
    await _require_manager_access(
        session,
        initiative,
        current_user,
        guild_context=guild_context,
    )

    stmt = (
        select(InitiativeMember)
        .options(selectinload(InitiativeMember.role_ref))
        .where(
            InitiativeMember.initiative_id == initiative_id,
            InitiativeMember.user_id == user_id,
        )
    )
    result = await session.exec(stmt)
    membership = result.one_or_none()

    if membership:
        role_name = membership.role_ref.name if membership.role_ref else None
        # Removing a member is never blocked by them being the initiative's last
        # manager — the initiative is simply left without one until an admin
        # appoints another. (Demoting the last manager still is blocked; that
        # edits a live membership rather than ending it.)
        await session.delete(membership)
        await session.flush()
        await _record_membership(
            session,
            event_type=AuditEventType.INITIATIVE_MEMBER_REMOVED,
            actor_user_id=current_user.id,
            member_user_id=user_id,
            initiative_id=initiative_id,
            guild_id=guild_context.guild_id,
            detail={"role": role_name, "via": "manager"},
        )

        await session.commit()
        # Removed from the initiative — drop this user's live content streams in
        # the guild immediately (initiative-level access change).
        await content_sockets.revoke_user(guild_context.guild_id, user_id)

    # Re-fetch initiative with updated memberships
    initiative = await _get_initiative_or_404(
        initiative_id, session, guild_context.guild_id
    )
    return serialize_initiative(initiative, context=guild_context)


@router.patch("/{initiative_id}/members/{user_id}", response_model=InitiativeRead)
async def update_initiative_member(
    initiative_id: int,
    user_id: int,
    payload: InitiativeMemberUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> InitiativeRead:
    """Update a member's role."""
    initiative = await _get_initiative_or_404(
        initiative_id, session, guild_context.guild_id
    )
    await _require_manager_access(
        session,
        initiative,
        current_user,
        guild_context=guild_context,
    )

    # Verify role exists and belongs to this initiative
    new_role = await initiatives_service.get_role_by_id(
        session, role_id=payload.role_id, initiative_id=initiative_id
    )
    if not new_role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=InitiativeMessages.ROLE_NOT_FOUND,
        )

    # Guild admins may only be elevated to a manager role, never assigned a
    # standard member or custom role (they already have full access).
    await _guard_guild_admin_role(
        session,
        guild_id=routed_guild_id(session),
        target_user_id=user_id,
        role=new_role,
    )
    await _guard_full_access_role(
        session,
        guild_id=routed_guild_id(session),
        target_user_id=user_id,
        role=new_role,
        guild_context=guild_context,
    )

    stmt = (
        select(InitiativeMember)
        .options(selectinload(InitiativeMember.role_ref))
        .where(
            InitiativeMember.initiative_id == initiative_id,
            InitiativeMember.user_id == user_id,
        )
    )
    result = await session.exec(stmt)
    membership = result.one_or_none()
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=InitiativeMessages.MEMBER_NOT_FOUND,
        )

    if membership.role_id != payload.role_id:
        # Check if demoting from manager role
        if (
            membership.role_ref
            and membership.role_ref.is_manager
            and not new_role.is_manager
        ):
            await _ensure_remaining_manager(
                session, initiative, exclude_user_ids={user_id}
            )
        from_role_id = membership.role_id
        from_role_name = membership.role_ref.name if membership.role_ref else None
        membership.role_id = payload.role_id
        session.add(membership)
        await _record_membership(
            session,
            event_type=AuditEventType.INITIATIVE_MEMBER_ROLE_CHANGED,
            actor_user_id=current_user.id,
            member_user_id=user_id,
            initiative_id=initiative_id,
            guild_id=guild_context.guild_id,
            detail={
                "from_role_id": from_role_id,
                "from": from_role_name,
                "to_role_id": payload.role_id,
                "to": new_role.name,
            },
        )
        await session.commit()
        # Role change may reduce content access — re-check this user's live
        # content streams immediately (initiative-level access change).
        await content_sockets.revoke_user(guild_context.guild_id, user_id)

    # Re-fetch initiative with updated memberships
    initiative = await _get_initiative_or_404(
        initiative_id, session, guild_context.guild_id
    )
    return serialize_initiative(initiative, context=guild_context)
