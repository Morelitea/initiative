from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlmodel import select, delete

from app.api.deps import (
    RLSSessionDep,
    SessionDep,
    get_current_active_user,
    get_guild_membership,
    GuildContext,
    require_guild_roles,
)
from app.core.messages import AuthMessages, InitiativeMessages
from app.db.session import reapply_rls_context
from app.models.project import Project, ProjectPermission, ProjectPermissionLevel
from app.models.initiative import Initiative, InitiativeMember, InitiativeRoleModel
from app.models.guild import GuildRole
from app.models.task import Task, TaskAssignee
from app.models.user import User, UserRole
from app.schemas.initiative import (
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
from app.schemas.user import UserPublic
from app.services import notifications as notifications_service
from app.services import initiatives as initiatives_service
from app.services import guilds as guilds_service
from app.services import documents as documents_service
from app.services import rls as rls_service

GuildAdminContext = Annotated[GuildContext, Depends(require_guild_roles(GuildRole.admin))]

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
            selectinload(Initiative.memberships)
            .selectinload(InitiativeMember.user),
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=InitiativeMessages.NOT_FOUND)
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
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=InitiativeMessages.MANAGER_REQUIRED)


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
    statement = (
        select(Initiative)
        .where(Initiative.guild_id == guild_context.guild_id)
        .options(
            selectinload(Initiative.memberships).selectinload(InitiativeMember.user),
            selectinload(Initiative.memberships)
            .selectinload(InitiativeMember.role_ref)
            .selectinload(InitiativeRoleModel.permissions),
        )
    )
    if not rls_service.is_guild_admin(guild_context.role):
        statement = (
            statement.join(InitiativeMember, InitiativeMember.initiative_id == Initiative.id)
            .where(InitiativeMember.user_id == current_user.id)
            .distinct()
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
) -> InitiativeRead:
    statement = (
        select(Initiative)
        .where(Initiative.id == initiative_id, Initiative.guild_id == guild_context.guild_id)
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=InitiativeMessages.NOT_FOUND)
    # Check access: must be guild admin or initiative member
    if not rls_service.is_guild_admin(guild_context.role):
        is_member = any(m.user_id == current_user.id for m in initiative.memberships)
        if not is_member:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=InitiativeMessages.NOT_A_MEMBER)
    return serialize_initiative(initiative)


@router.post("/", response_model=InitiativeRead, status_code=status.HTTP_201_CREATED)
async def create_initiative(
    initiative_in: InitiativeCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(require_guild_roles(GuildRole.admin))],
) -> InitiativeRead:
    guild_id = guild_context.guild_id
    if await _initiative_name_exists(session, initiative_in.name, guild_id=guild_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=InitiativeMessages.NAME_EXISTS)
    initiative = Initiative(name=initiative_in.name, description=initiative_in.description, guild_id=guild_id)
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
    await reapply_rls_context(session)
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
    initiative = await _get_initiative_or_404(initiative_id, session, guild_context.guild_id)
    await _require_manager_access(session, initiative, current_user, guild_role=guild_context.role)

    update_data = initiative_in.dict(exclude_unset=True)
    if "name" in update_data and update_data["name"] is not None:
        if await _initiative_name_exists(
            session,
            update_data["name"],
            guild_id=initiative.guild_id,
            exclude_initiative_id=initiative_id,
        ):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=InitiativeMessages.NAME_EXISTS)
    for field, value in update_data.items():
        setattr(initiative, field, value)
    session.add(initiative)
    await session.commit()
    await reapply_rls_context(session)
    initiative = await _get_initiative_or_404(initiative_id, session, guild_context.guild_id)
    return serialize_initiative(initiative)


@router.delete("/{initiative_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_initiative(
    initiative_id: int,
    session: RLSSessionDep,
    guild_context: GuildAdminContext,
) -> None:
    initiative = await _get_initiative_or_404(initiative_id, session, guild_context.guild_id)
    if initiative.is_default:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=InitiativeMessages.CANNOT_DELETE_DEFAULT)
    project_stmt = await session.exec(select(Project).where(Project.initiative_id == initiative_id))
    projects = project_stmt.all()
    for project in projects:
        await session.delete(project)
    await session.delete(initiative)
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
    initiative = await _get_initiative_or_404(initiative_id, session, guild_context.guild_id)

    # Check access: must be guild admin or initiative member
    if not rls_service.is_guild_admin(guild_context.role):
        is_member = any(m.user_id == current_user.id for m in initiative.memberships)
        if not is_member:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=InitiativeMessages.NOT_A_MEMBER)

    roles = await initiatives_service.list_initiative_roles(session, initiative_id=initiative_id)

    # Get member counts for each role
    result = []
    for role in roles:
        member_count = await initiatives_service.count_role_members(session, role_id=role.id)
        result.append(serialize_role(role, member_count=member_count))
    return result


@router.post("/{initiative_id}/roles", response_model=InitiativeRoleRead, status_code=status.HTTP_201_CREATED)
async def create_initiative_role(
    initiative_id: int,
    role_in: InitiativeRoleCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> InitiativeRoleRead:
    """Create a new custom role for an initiative."""
    initiative = await _get_initiative_or_404(initiative_id, session, guild_context.guild_id)
    await _require_manager_access(session, initiative, current_user, guild_role=guild_context.role)

    # Check for duplicate name
    existing = await initiatives_service.get_role_by_name(
        session, initiative_id=initiative_id, role_name=role_in.name
    )
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=InitiativeMessages.ROLE_NAME_EXISTS)

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
    initiative = await _get_initiative_or_404(initiative_id, session, guild_context.guild_id)
    await _require_manager_access(session, initiative, current_user, guild_role=guild_context.role)

    role = await initiatives_service.get_role_by_id(
        session, role_id=role_id, initiative_id=initiative_id
    )
    if not role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=InitiativeMessages.ROLE_NOT_FOUND)

    # Prevent modifying PM role permissions
    if role.name == "project_manager" and role_in.permissions is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=InitiativeMessages.CANNOT_MODIFY_PM_PERMISSIONS,
        )

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
                    .join(InitiativeRoleModel, InitiativeRoleModel.id == InitiativeMember.role_id)
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
    await reapply_rls_context(session)
    member_count = await initiatives_service.count_role_members(session, role_id=role.id)
    return serialize_role(role, member_count=member_count)


@router.delete("/{initiative_id}/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_initiative_role(
    initiative_id: int,
    role_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> None:
    """Delete a custom role. Built-in roles cannot be deleted."""
    initiative = await _get_initiative_or_404(initiative_id, session, guild_context.guild_id)
    await _require_manager_access(session, initiative, current_user, guild_role=guild_context.role)

    role = await initiatives_service.get_role_by_id(
        session, role_id=role_id, initiative_id=initiative_id
    )
    if not role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=InitiativeMessages.ROLE_NOT_FOUND)

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
    await _get_initiative_or_404(initiative_id, session, guild_context.guild_id)

    # Guild admins have all permissions
    if rls_service.is_guild_admin(guild_context.role):
        return MyInitiativePermissions(
            is_manager=True,
            permissions={
                "docs_enabled": True,
                "projects_enabled": True,
                "create_docs": True,
                "create_projects": True,
            },
        )

    membership = await initiatives_service.get_initiative_membership_with_role(
        session,
        initiative_id=initiative_id,
        user_id=current_user.id,
    )
    if not membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=InitiativeMessages.NOT_A_MEMBER)

    role = membership.role_ref
    if not role:
        return MyInitiativePermissions()

    permissions = {
        perm.permission_key: perm.enabled
        for perm in (role.permissions or [])
    }

    return MyInitiativePermissions(
        role_id=role.id,
        role_name=role.name,
        role_display_name=role.display_name,
        is_manager=role.is_manager,
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
) -> List[User]:
    """Get all members of an initiative."""
    await _get_initiative_or_404(initiative_id, session, guild_context.guild_id)

    # Check that user has access to this initiative
    membership = await initiatives_service.get_initiative_membership(
        session,
        initiative_id=initiative_id,
        user_id=current_user.id,
    )
    if not membership and current_user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=InitiativeMessages.NOT_A_MEMBER)

    # Get all initiative members
    stmt = (
        select(User)
        .join(InitiativeMember, InitiativeMember.user_id == User.id)
        .where(InitiativeMember.initiative_id == initiative_id)
        .order_by(User.full_name, User.email)
    )
    result = await session.exec(stmt)
    return result.all()


@router.post("/{initiative_id}/members", response_model=InitiativeRead, status_code=status.HTTP_200_OK)
async def add_initiative_member(
    initiative_id: int,
    payload: InitiativeMemberAdd,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> InitiativeRead:
    """Add a member to an initiative or update their role."""
    initiative = await _get_initiative_or_404(initiative_id, session, guild_context.guild_id)
    await _require_manager_access(
        session, initiative, current_user, guild_role=guild_context.role,
    )

    user_stmt = await session.exec(select(User).where(User.id == payload.user_id))
    user = user_stmt.one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND)
    guild_membership = await guilds_service.get_membership(
        session,
        guild_id=initiative.guild_id,
        user_id=user.id,
    )
    if not guild_membership:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=InitiativeMessages.USER_NOT_IN_GUILD)

    # Get the role to assign (default to member role if not specified)
    role_id = payload.role_id
    if role_id is None:
        member_role = await initiatives_service.get_member_role(session, initiative_id=initiative_id)
        if not member_role:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=InitiativeMessages.MEMBER_ROLE_NOT_FOUND)
        role_id = member_role.id
    else:
        # Verify role exists and belongs to this initiative
        role = await initiatives_service.get_role_by_id(
            session, role_id=role_id, initiative_id=initiative_id
        )
        if not role:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=InitiativeMessages.ROLE_NOT_FOUND)

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
            old_role = await initiatives_service.get_role_by_id(session, role_id=membership.role_id)
            new_role = await initiatives_service.get_role_by_id(session, role_id=role_id)
            if old_role and old_role.is_manager and (not new_role or not new_role.is_manager):
                await _ensure_remaining_manager(session, initiative, exclude_user_ids={membership.user_id})
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
    await reapply_rls_context(session)
    # Re-fetch initiative with updated memberships
    initiative = await _get_initiative_or_404(initiative_id, session, guild_context.guild_id)
    if created:
        await notifications_service.notify_initiative_membership(
            session,
            user,
            initiative_id=initiative.id,
            initiative_name=initiative.name,
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
    initiative = await _get_initiative_or_404(initiative_id, session, guild_context.guild_id)
    await _require_manager_access(
        session, initiative, current_user, guild_role=guild_context.role,
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
        # Check if removing a manager
        if membership.role_ref and membership.role_ref.is_manager:
            await _ensure_remaining_manager(session, initiative, exclude_user_ids={user_id})
        await session.delete(membership)
        await session.flush()

        # Handle orphaned documents when owner is removed
        await documents_service.handle_owner_removal(
            session,
            initiative_id=initiative_id,
            user_id=user_id,
        )

        project_ids_result = await session.exec(select(Project.id).where(Project.initiative_id == initiative_id))
        project_ids = [project_id for project_id in project_ids_result.all()]

        if project_ids:
            # Handle orphaned projects - grant owner access to PMs before deleting
            owner_permissions_stmt = select(ProjectPermission).where(
                ProjectPermission.user_id == user_id,
                ProjectPermission.project_id.in_(tuple(project_ids)),
                ProjectPermission.level == ProjectPermissionLevel.owner,
            )
            owner_permissions_result = await session.exec(owner_permissions_stmt)
            owner_permissions = owner_permissions_result.all()

            if owner_permissions:
                # Get all initiative managers (users with is_manager role)
                pm_result = await session.exec(
                    select(InitiativeMember)
                    .join(InitiativeRoleModel, InitiativeRoleModel.id == InitiativeMember.role_id)
                    .where(
                        InitiativeMember.initiative_id == initiative_id,
                        InitiativeRoleModel.is_manager.is_(True),
                    )
                )
                pm_user_ids = {pm.user_id for pm in pm_result.all() if pm.user_id != user_id}

                # For each project where user had owner permission, grant owner to PMs
                for perm in owner_permissions:
                    # Get existing permissions for this project
                    existing_perms_stmt = select(ProjectPermission.user_id).where(
                        ProjectPermission.project_id == perm.project_id
                    )
                    existing_result = await session.exec(existing_perms_stmt)
                    existing_user_ids = set(existing_result.all())

                    # Grant owner access to PMs who don't have any permission yet
                    for pm_user_id in pm_user_ids:
                        if pm_user_id not in existing_user_ids:
                            pm_permission = ProjectPermission(
                                project_id=perm.project_id,
                                user_id=pm_user_id,
                                level=ProjectPermissionLevel.owner,
                                guild_id=initiative.guild_id,
                            )
                            session.add(pm_permission)

            # Remove project permissions for this user in all initiative projects
            delete_permissions_stmt = (
                delete(ProjectPermission)
                .where(ProjectPermission.user_id == user_id)
                .where(ProjectPermission.project_id.in_(tuple(project_ids)))
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

        await session.commit()
        await reapply_rls_context(session)

    # Re-fetch initiative with updated memberships
    initiative = await _get_initiative_or_404(initiative_id, session, guild_context.guild_id)
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
    initiative = await _get_initiative_or_404(initiative_id, session, guild_context.guild_id)
    await _require_manager_access(
        session, initiative, current_user, guild_role=guild_context.role,
    )

    # Verify role exists and belongs to this initiative
    new_role = await initiatives_service.get_role_by_id(
        session, role_id=payload.role_id, initiative_id=initiative_id
    )
    if not new_role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=InitiativeMessages.ROLE_NOT_FOUND)

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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=InitiativeMessages.MEMBER_NOT_FOUND)

    if membership.role_id != payload.role_id:
        # Check if demoting from manager role
        if membership.role_ref and membership.role_ref.is_manager and not new_role.is_manager:
            await _ensure_remaining_manager(session, initiative, exclude_user_ids={user_id})
        membership.role_id = payload.role_id
        session.add(membership)
        await session.commit()
        await reapply_rls_context(session)

    # Re-fetch initiative with updated memberships
    initiative = await _get_initiative_or_404(initiative_id, session, guild_context.guild_id)
    return serialize_initiative(initiative)
