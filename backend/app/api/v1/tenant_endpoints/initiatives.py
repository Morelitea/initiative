from typing import Annotated, List, Optional, Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlmodel import select, delete

from app.api.deps import (
    IncludeDeletedDep,
    RLSSessionDep,
    SessionDep,
    get_current_active_user,
    get_guild_membership,
    GuildContext,
    require_guild_roles,
)
from app.core.messages import (
    AuthMessages,
    GuildMessages,
    InitiativeMessages,
)
from app.core.tools import CORE_TOOLS, TOGGLEABLE_TOOLS, Tool
from app.models.tenant.document import Document
from app.models.tenant.project import Project
from app.models.tenant.resource_grant import ResourceGrant, ResourceAccessLevel
from app.models.tenant.initiative import (
    Initiative,
    InitiativeMember,
    InitiativeRoleModel,
    PermissionKey,
)
from app.models.platform.guild import GuildMembership, GuildRole
from app.models.tenant.task import Task, TaskAssignee
from app.models.platform.user import User
from app.schemas.tenant.initiative import (
    InitiativeCreate,
    InitiativeMemberAdd,
    InitiativeMemberUpdate,
    InitiativeRead,
    InitiativeRoleCreate,
    InitiativeRoleRead,
    InitiativeRoleUpdate,
    InitiativeUpdate,
    MyInitiativePermissions,
    serialize_initiative,
    serialize_role,
)
from app.schemas.platform.user import (
    UserPublic,
    UserSummary,
    UserSummaryListResponse,
)
from app.db.query import MAX_ID_FILTER_VALUES, page_has_next, paginated_query
from app.services import notifications as notifications_service
from app.services.tenant import initiatives as initiatives_service
from app.services.platform import guilds as guilds_service
from app.services.stream_authz import authority as stream_authority
from app.services import rls as rls_service
from app.services.membership import initiative_scope_clause

GuildAdminContext = Annotated[
    GuildContext, Depends(require_guild_roles(GuildRole.admin))
]

router = APIRouter()


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
            selectinload(Initiative.memberships).selectinload(InitiativeMember.user),
            selectinload(Initiative.memberships)
            .selectinload(InitiativeMember.role_ref)
            .selectinload(InitiativeRoleModel.permissions),
        )
    )
    if guild_id is not None:
        statement = statement.where(Initiative.guild_id == guild_id)
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
        Initiative.guild_id == guild_id,
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
    guild_role: GuildRole | None = None,
) -> None:
    """Require that the user has manager-level access to the initiative."""
    if guild_role is not None and rls_service.is_guild_admin(guild_role):
        return
    is_manager = await rls_service.is_initiative_manager(
        session,
        initiative_id=initiative.id,
        user=current_user,
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
    guild_membership: GuildMembership | None = None,
) -> None:
    """Restrict which initiative roles a guild admin may be assigned.

    A guild admin already has complete access to every initiative in their
    guild (see ``role_context.is_request_guild_admin``), so they are implicit
    full-access members. They may *additionally* hold a manager role — purely
    for manager-style features like notifications — but must never be assigned a
    standard member or custom role. This keeps the admin's standing access
    distinct from per-initiative DAC and is enforced server-side for safety.
    """
    if role is not None and role.is_manager:
        return  # manager role is the one allowed elevation for an admin
    membership = guild_membership or await guilds_service.get_membership(
        session, guild_id=guild_id, user_id=target_user_id
    )
    if membership and membership.role == GuildRole.admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=InitiativeMessages.GUILD_ADMIN_ROLE_RESTRICTED,
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
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> List[InitiativeRead]:
    # `initiatives` is a structural table (not initiative-RLS-gated), so scope it
    # in the query with the ONE access rule — initiative_scope_clause defers to
    # public.initiative_access (admin OR PAM OR member, from the request GUCs),
    # the same predicate the content-table RLS uses — instead of re-deriving the
    # admin/PAM/member split here.
    statement = (
        select(Initiative)
        .where(
            Initiative.guild_id == guild_context.guild_id,
            initiative_scope_clause(current_user.id, Initiative.id),
        )
        .options(
            selectinload(Initiative.memberships).selectinload(InitiativeMember.user),
            selectinload(Initiative.memberships)
            .selectinload(InitiativeMember.role_ref)
            .selectinload(InitiativeRoleModel.permissions),
        )
    )
    result = await session.exec(statement)
    initiatives = result.all()
    return [serialize_initiative(initiative) for initiative in initiatives]


@router.get("/{initiative_id}", response_model=InitiativeRead)
async def get_initiative(
    initiative_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
    include_deleted: IncludeDeletedDep = False,
) -> InitiativeRead:
    statement = (
        select(Initiative)
        .where(
            Initiative.id == initiative_id,
            Initiative.guild_id == guild_context.guild_id,
        )
        .options(
            selectinload(Initiative.memberships).selectinload(InitiativeMember.user),
            selectinload(Initiative.memberships)
            .selectinload(InitiativeMember.role_ref)
            .selectinload(InitiativeRoleModel.permissions),
        )
    )
    result = await session.exec(statement)
    initiative = result.first()
    if not initiative:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=InitiativeMessages.NOT_FOUND
        )
    # Check access: must be guild admin or initiative member
    if not rls_service.is_guild_admin(guild_context.role):
        is_member = any(m.user_id == current_user.id for m in initiative.memberships)
        if not is_member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=InitiativeMessages.NOT_A_MEMBER,
            )
    return serialize_initiative(initiative)


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
        guild_id=guild_id,
        # One master switch per toggleable tool, derived — a new Tool member
        # flows through without touching this endpoint.
        **{
            t.view_permission: getattr(initiative_in, t.view_permission)
            for t in TOGGLEABLE_TOOLS
        },
    )
    if initiative_in.color:
        initiative.color = initiative_in.color
    session.add(initiative)
    await session.flush()

    # Create built-in roles for this initiative
    pm_role, _member_role = await initiatives_service.create_builtin_roles(
        session, initiative_id=initiative.id
    )

    # Add creator as PM
    session.add(
        InitiativeMember(
            initiative_id=initiative.id,
            user_id=current_user.id,
            role_id=pm_role.id,
            guild_id=guild_id,
        )
    )
    await session.commit()
    initiative = await _get_initiative_or_404(initiative.id, session, guild_id)
    return serialize_initiative(initiative)


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
        session, initiative, current_user, guild_role=guild_context.role
    )

    update_data = initiative_in.dict(exclude_unset=True)
    # Archiving hides the initiative from every member's sidebar — a guild-wide
    # visibility change. The UI only exposes the toggle to guild admins; this is
    # the matching server-side backstop, using the existing guild-admin-required
    # code (no new message to maintain).
    if (
        update_data.get("is_archived") is not None
        and update_data["is_archived"] != initiative.is_archived
        and not rls_service.is_guild_admin(guild_context.role)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildMessages.GUILD_ADMIN_REQUIRED,
        )
    if "name" in update_data and update_data["name"] is not None:
        if await _initiative_name_exists(
            session,
            update_data["name"],
            guild_id=initiative.guild_id,
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
    return serialize_initiative(initiative)


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
    from app.services.platform import guilds as guilds_service
    from app.services.tenant.soft_delete import soft_delete_entity

    initiative = await _get_initiative_or_404(
        initiative_id, session, guild_context.guild_id
    )
    if initiative.is_default:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=InitiativeMessages.CANNOT_DELETE_DEFAULT,
        )
    retention_days = await guilds_service.get_guild_retention_days(
        session, guild_context.guild_id
    )
    await soft_delete_entity(
        session,
        initiative,
        deleted_by_user_id=current_user.id,
        retention_days=retention_days,
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

    # Check access: must be guild admin or initiative member
    if not rls_service.is_guild_admin(guild_context.role):
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
        session, initiative, current_user, guild_role=guild_context.role
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

    Note: PM role permissions cannot be changed to prevent lockouts.
    """
    initiative = await _get_initiative_or_404(
        initiative_id, session, guild_context.guild_id
    )
    await _require_manager_access(
        session, initiative, current_user, guild_role=guild_context.role
    )

    role = await initiatives_service.get_role_by_id(
        session, role_id=role_id, initiative_id=initiative_id
    )
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=InitiativeMessages.ROLE_NOT_FOUND,
        )

    # Prevent modifying PM role permissions
    if role.name == "project_manager" and role_in.permissions is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=InitiativeMessages.CANNOT_MODIFY_PM_PERMISSIONS,
        )

    # "Full access" (override_share_restrictions): the endpoint is manager-
    # accessible (a PM can edit roles), so this single field needs its own,
    # stricter guard — otherwise a PM could flip it on their own role and
    # self-escalate. Field-level, not endpoint-level:
    #   * only a guild admin may change it (no in-initiative escalation), and
    #   * only on the built-in project_manager role (its tool permissions are
    #     already locked on, so "view/edit everything regardless of sharing" is
    #     coherent there; on a lesser role it would contradict gate-3).
    if (
        role_in.override_share_restrictions is not None
        and role_in.override_share_restrictions != role.override_share_restrictions
    ):
        if not rls_service.is_guild_admin(guild_context.role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=InitiativeMessages.OVERRIDE_REQUIRES_GUILD_ADMIN,
            )
        if not (role.is_builtin and role.name == "project_manager"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=InitiativeMessages.OVERRIDE_PM_ONLY,
            )
        role.override_share_restrictions = role_in.override_share_restrictions
        session.add(role)

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
        session, initiative, current_user, guild_role=guild_context.role
    )

    role = await initiatives_service.get_role_by_id(
        session, role_id=role_id, initiative_id=initiative_id
    )
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=InitiativeMessages.ROLE_NOT_FOUND,
        )

    try:
        await initiatives_service.delete_role(session, role=role)
        await session.commit()
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{initiative_id}/my-permissions", response_model=MyInitiativePermissions)
async def get_my_initiative_permissions(
    initiative_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> MyInitiativePermissions:
    """Get the current user's permissions for an initiative."""
    initiative = await _get_initiative_or_404(
        initiative_id, session, guild_context.guild_id
    )

    # Whether a tool is available in this initiative at all: core tools always,
    # toggleable tools per their master switch.
    def tool_available(t: Tool) -> bool:
        return t in CORE_TOOLS or bool(getattr(initiative, t.view_permission))

    # Content writes are frozen (read_only lifecycle status): report create
    # permissions as denied so the UI hides its create affordances instead of
    # offering writes the database role will refuse. Never true on the PAM
    # branch — grants override the guild status.
    content_frozen = guild_context.content_read_only

    # Guild admins have all permissions
    if rls_service.is_guild_admin(guild_context.role):
        return MyInitiativePermissions(
            is_manager=True,
            # Guild admins view/edit everything regardless of sharing.
            override_share_restrictions=True,
            permissions={
                **{PermissionKey(t.view_permission): tool_available(t) for t in Tool},
                **{
                    PermissionKey(t.create_permission): tool_available(t)
                    and not content_frozen
                    for t in Tool
                },
            },
        )

    # Scoped PAM grantee: time-bound, guild-wide access with no membership
    # row. They can view every section (gated by the initiative's feature
    # switches), and a read_write grant edits *existing* content only —
    # authoring a new tool is an initiative-role permission a grantee never
    # holds, so every create flag stays off. (Break-glass never reaches this
    # branch: it is routed as a synthetic guild admin and answered above.)
    # A grant never confers management.
    if guild_context.is_pam:
        return MyInitiativePermissions(
            is_manager=False,
            permissions={
                **{PermissionKey(t.view_permission): tool_available(t) for t in Tool},
                **{PermissionKey(t.create_permission): False for t in Tool},
            },
        )

    membership = await initiatives_service.get_initiative_membership_with_role(
        session,
        initiative_id=initiative_id,
        user_id=current_user.id,
    )
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=InitiativeMessages.NOT_A_MEMBER,
        )

    role = membership.role_ref
    if not role:
        return MyInitiativePermissions()

    permissions = {
        perm.permission_key: perm.enabled for perm in (role.permissions or [])
    }

    # Initiative-level master switches override role-level permissions, so
    # members of an initiative whose toggle is off never see the tool
    # regardless of what their role permits.
    for t in TOGGLEABLE_TOOLS:
        if not tool_available(t):
            permissions[PermissionKey(t.view_permission)] = False
            permissions[PermissionKey(t.create_permission)] = False
    if content_frozen:
        for t in Tool:
            permissions[PermissionKey(t.create_permission)] = False

    return MyInitiativePermissions(
        role_id=role.id,
        role_name=role.name,
        role_display_name=role.display_name,
        is_manager=role.is_manager,
        override_share_restrictions=role.override_share_restrictions,
        permissions=permissions,
    )


# ============================================================================
# Member management
# ============================================================================


@router.get("/{initiative_id}/members", response_model=List[UserPublic])
async def get_initiative_members(
    initiative_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> Sequence[User]:
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
    if (
        not membership
        and not guild_context.is_pam
        and not rls_service.is_guild_admin(guild_context.role)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=InitiativeMessages.NOT_A_MEMBER,
        )

    # Get all initiative members
    stmt = (
        select(User)
        .join(InitiativeMember, InitiativeMember.user_id == User.id)
        .where(InitiativeMember.initiative_id == initiative_id)
        .order_by(User.full_name, User.id)
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
    if (
        not membership
        and not guild_context.is_pam
        and not rls_service.is_guild_admin(guild_context.role)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=InitiativeMessages.NOT_A_MEMBER,
        )

    base = (
        select(User)
        .join(InitiativeMember, InitiativeMember.user_id == User.id)
        .where(InitiativeMember.initiative_id == initiative_id)
    )
    if search and (term := search.strip()):
        base = base.where(User.full_name.ilike(f"%{term}%"))
    if user_id:
        base = base.where(User.id.in_(user_id))

    count_stmt = select(func.count()).select_from(base.subquery())
    data_stmt = base.order_by(User.full_name.asc(), User.id.asc())

    users, total_count, actual_page = await paginated_query(
        session, data_stmt, count_stmt, page=page, page_size=page_size
    )

    return UserSummaryListResponse(
        items=[UserSummary.model_validate(user) for user in users],
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
    """Add a member to an initiative or update their role."""
    initiative = await _get_initiative_or_404(
        initiative_id, session, guild_context.guild_id
    )
    await _require_manager_access(
        session,
        initiative,
        current_user,
        guild_role=guild_context.role,
    )

    user_stmt = await session.exec(select(User).where(User.id == payload.user_id))
    user = user_stmt.one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND
        )
    guild_membership = await guilds_service.get_membership(
        session,
        guild_id=initiative.guild_id,
        user_id=user.id,
    )
    if not guild_membership:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=InitiativeMessages.USER_NOT_IN_GUILD,
        )

    # Get the role to assign (default to member role if not specified)
    role_id = payload.role_id
    if role_id is None:
        resolved_role = await initiatives_service.get_member_role(
            session, initiative_id=initiative_id
        )
        if not resolved_role:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=InitiativeMessages.MEMBER_ROLE_NOT_FOUND,
            )
        role_id = resolved_role.id
    else:
        # Verify role exists and belongs to this initiative
        resolved_role = await initiatives_service.get_role_by_id(
            session, role_id=role_id, initiative_id=initiative_id
        )
        if not resolved_role:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=InitiativeMessages.ROLE_NOT_FOUND,
            )

    # Guild admins are implicit full-access members; they may only be elevated
    # to a manager role, never assigned a standard member or custom role.
    await _guard_guild_admin_role(
        session,
        guild_id=initiative.guild_id,
        target_user_id=payload.user_id,
        role=resolved_role,
        guild_membership=guild_membership,
    )

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
            membership.role_id = role_id
            session.add(membership)
    else:
        membership = InitiativeMember(
            initiative_id=initiative_id,
            user_id=payload.user_id,
            role_id=role_id,
            guild_id=initiative.guild_id,
        )
        session.add(membership)
        created = True

    await session.commit()
    # Re-fetch initiative with updated memberships
    initiative = await _get_initiative_or_404(
        initiative_id, session, guild_context.guild_id
    )
    if created:
        await notifications_service.notify_initiative_membership(
            session,
            user,
            initiative_id=initiative.id,
            initiative_name=initiative.name,
            guild_id=initiative.guild_id,
        )
    return serialize_initiative(initiative)


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
        guild_role=guild_context.role,
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
        # Removing a member is never blocked by them being the initiative's last
        # manager — the initiative is simply left without one until an admin
        # appoints another. (Demoting the last manager still is blocked; that
        # edits a live membership rather than ending it.)
        await session.delete(membership)
        await session.flush()

        project_ids_result = await session.exec(
            select(Project.id).where(Project.initiative_id == initiative_id)
        )
        project_ids = [project_id for project_id in project_ids_result.all()]

        if project_ids:
            # Drop this user's read/write project grants in the initiative —
            # access that came with the membership goes with it. Owner grants
            # are excluded: they record who the project belongs to, and grant
            # nothing on their own once the membership row is gone. A guild
            # admin re-homes them through the transfer-ownership action.
            delete_permissions_stmt = (
                delete(ResourceGrant)
                .where(ResourceGrant.resource_type == "project")
                .where(ResourceGrant.user_id == user_id)
                .where(ResourceGrant.level != ResourceAccessLevel.owner)
                .where(ResourceGrant.resource_id.in_(tuple(project_ids)))
            )
            await session.exec(delete_permissions_stmt)

            # Remove task assignments for this user in all initiative projects
            task_ids_result = await session.exec(
                select(Task.id).where(Task.project_id.in_(tuple(project_ids)))
            )
            task_ids = [task_id for task_id in task_ids_result.all()]
            if task_ids:
                delete_stmt = (
                    delete(TaskAssignee)
                    .where(TaskAssignee.user_id == user_id)
                    .where(TaskAssignee.task_id.in_(tuple(task_ids)))
                )
                await session.exec(delete_stmt)

        # Same for documents: read/write grants go, the owner grant stays.
        await session.exec(
            delete(ResourceGrant).where(
                ResourceGrant.resource_type == "document",
                ResourceGrant.user_id == user_id,
                ResourceGrant.level != ResourceAccessLevel.owner,
                ResourceGrant.resource_id.in_(
                    select(Document.id).where(Document.initiative_id == initiative_id)
                ),
            )
        )

        await session.commit()
        # Removed from the initiative — drop this user's live content streams in
        # the guild immediately (initiative-level access change).
        await stream_authority.revoke_user(guild_context.guild_id, user_id)

    # Re-fetch initiative with updated memberships
    initiative = await _get_initiative_or_404(
        initiative_id, session, guild_context.guild_id
    )
    return serialize_initiative(initiative)


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
        guild_role=guild_context.role,
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
        guild_id=initiative.guild_id,
        target_user_id=user_id,
        role=new_role,
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
        membership.role_id = payload.role_id
        session.add(membership)
        await session.commit()
        # Role change may reduce content access — re-check this user's live
        # content streams immediately (initiative-level access change).
        await stream_authority.revoke_user(guild_context.guild_id, user_id)

    # Re-fetch initiative with updated memberships
    initiative = await _get_initiative_or_404(
        initiative_id, session, guild_context.guild_id
    )
    return serialize_initiative(initiative)
