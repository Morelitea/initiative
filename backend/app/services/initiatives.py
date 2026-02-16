from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlmodel import select, delete
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import InitiativeMessages
from app.models.initiative import (
    Initiative,
    InitiativeMember,
    InitiativeRole,
    InitiativeRoleModel,
    InitiativeRolePermission,
    BUILTIN_ROLE_PERMISSIONS,
)
from app.models.user import User
from app.schemas.user import UserInitiativeRole

# Backward compatibility — these security functions moved to rls.py
from app.services.rls import (  # noqa: F401
    is_initiative_manager,
    assert_initiative_manager,
    check_initiative_permission,
    has_feature_access,
)

DEFAULT_INITIATIVE_NAME = "Default Initiative"
DEFAULT_INITIATIVE_COLOR = "#2563eb"


async def get_role_by_name(
    session: AsyncSession,
    *,
    initiative_id: int,
    role_name: str,
) -> InitiativeRoleModel | None:
    """Get a role by name within an initiative."""
    stmt = select(InitiativeRoleModel).where(
        InitiativeRoleModel.initiative_id == initiative_id,
        InitiativeRoleModel.name == role_name,
    )
    result = await session.exec(stmt)
    return result.one_or_none()


async def get_pm_role(
    session: AsyncSession,
    *,
    initiative_id: int,
) -> InitiativeRoleModel | None:
    """Get the project_manager role for an initiative."""
    return await get_role_by_name(session, initiative_id=initiative_id, role_name="project_manager")


async def get_member_role(
    session: AsyncSession,
    *,
    initiative_id: int,
) -> InitiativeRoleModel | None:
    """Get the member role for an initiative."""
    return await get_role_by_name(session, initiative_id=initiative_id, role_name="member")


async def create_builtin_roles(
    session: AsyncSession,
    *,
    initiative_id: int,
) -> tuple[InitiativeRoleModel, InitiativeRoleModel]:
    """Create the built-in PM and Member roles for an initiative.

    Returns (pm_role, member_role).
    """
    # Create PM role
    pm_role = InitiativeRoleModel(
        initiative_id=initiative_id,
        name="project_manager",
        display_name="Project Manager",
        is_builtin=True,
        is_manager=True,
        position=0,
    )
    session.add(pm_role)
    await session.flush()

    # Create Member role
    member_role = InitiativeRoleModel(
        initiative_id=initiative_id,
        name="member",
        display_name="Member",
        is_builtin=True,
        is_manager=False,
        position=1,
    )
    session.add(member_role)
    await session.flush()

    # Add permissions for PM role
    for perm_key, enabled in BUILTIN_ROLE_PERMISSIONS["project_manager"].items():
        session.add(InitiativeRolePermission(
            initiative_role_id=pm_role.id,
            permission_key=perm_key.value,
            enabled=enabled,
        ))

    # Add permissions for Member role
    for perm_key, enabled in BUILTIN_ROLE_PERMISSIONS["member"].items():
        session.add(InitiativeRolePermission(
            initiative_role_id=member_role.id,
            permission_key=perm_key.value,
            enabled=enabled,
        ))

    await session.flush()
    return pm_role, member_role


async def ensure_default_initiative(session: AsyncSession, admin_user: User, *, guild_id: int) -> Initiative:
    statement = select(Initiative).where(
        Initiative.guild_id == guild_id,
        Initiative.is_default.is_(True),
    )
    result = await session.exec(statement)
    default_initiative = result.one_or_none()
    if default_initiative:
        await _ensure_membership_as_pm(
            session,
            initiative_id=default_initiative.id,
            user_id=admin_user.id,
            guild_id=guild_id,
        )
        await session.refresh(default_initiative, attribute_names=["memberships"])
        return default_initiative

    now = datetime.now(timezone.utc)
    default_initiative = Initiative(
        guild_id=guild_id,
        name=DEFAULT_INITIATIVE_NAME,
        description="Automatically created default initiative",
        color=DEFAULT_INITIATIVE_COLOR,
        is_default=True,
        created_at=now,
        updated_at=now,
    )
    session.add(default_initiative)
    await session.flush()

    # Create built-in roles for this initiative
    pm_role, _member_role = await create_builtin_roles(session, initiative_id=default_initiative.id)

    # Add admin as PM
    session.add(
        InitiativeMember(
            initiative_id=default_initiative.id,
            user_id=admin_user.id,
            role_id=pm_role.id,
            guild_id=guild_id,
        )
    )
    await session.flush()
    await session.refresh(default_initiative, attribute_names=["memberships"])
    return default_initiative


async def load_user_initiative_roles(session: AsyncSession, users: Sequence[User]) -> None:
    """Load initiative role information for users (for display purposes)."""
    user_ids = [user.id for user in users if user.id is not None]
    if not user_ids:
        return
    stmt = (
        select(
            InitiativeMember.user_id,
            InitiativeRoleModel.name,
            Initiative.id,
            Initiative.name,
        )
        .join(Initiative, Initiative.id == InitiativeMember.initiative_id)
        .outerjoin(InitiativeRoleModel, InitiativeRoleModel.id == InitiativeMember.role_id)
        .where(InitiativeMember.user_id.in_(tuple(user_ids)))
    )
    result = await session.exec(stmt)
    assignments: dict[int, list[UserInitiativeRole]] = {user_id: [] for user_id in user_ids}
    for user_id, role_name, initiative_id, initiative_name in result.all():
        # Convert role_name to legacy enum for backward compatibility
        legacy_role = InitiativeRole.project_manager if role_name == "project_manager" else InitiativeRole.member
        assignments.setdefault(user_id, []).append(
            UserInitiativeRole(initiative_id=initiative_id, initiative_name=initiative_name, role=legacy_role)
        )
    for user in users:
        user_assignments = assignments.get(user.id or 0, [])
        object.__setattr__(user, "initiative_roles", user_assignments)


async def _ensure_membership_as_pm(
    session: AsyncSession,
    *,
    initiative_id: int,
    user_id: int,
    guild_id: int,
) -> None:
    """Ensure user is a member with PM role."""
    pm_role = await get_pm_role(session, initiative_id=initiative_id)
    if not pm_role:
        # Create roles if they don't exist (migration safety)
        pm_role, _member_role = await create_builtin_roles(session, initiative_id=initiative_id)

    stmt = select(InitiativeMember).where(
        InitiativeMember.initiative_id == initiative_id,
        InitiativeMember.user_id == user_id,
    )
    result = await session.exec(stmt)
    membership = result.one_or_none()
    if membership:
        if membership.role_id != pm_role.id:
            membership.role_id = pm_role.id
            session.add(membership)
            await session.flush()
        return
    session.add(
        InitiativeMember(
            initiative_id=initiative_id,
            user_id=user_id,
            role_id=pm_role.id,
            guild_id=guild_id,
        )
    )
    await session.flush()


async def get_initiative_membership(
    session: AsyncSession,
    *,
    initiative_id: int,
    user_id: int,
) -> InitiativeMember | None:
    stmt = select(InitiativeMember).where(
        InitiativeMember.initiative_id == initiative_id,
        InitiativeMember.user_id == user_id,
    )
    result = await session.exec(stmt)
    return result.one_or_none()


async def get_initiative_membership_with_role(
    session: AsyncSession,
    *,
    initiative_id: int,
    user_id: int,
) -> InitiativeMember | None:
    """Get membership with role eagerly loaded."""
    stmt = (
        select(InitiativeMember)
        .options(selectinload(InitiativeMember.role_ref).selectinload(InitiativeRoleModel.permissions))
        .where(
            InitiativeMember.initiative_id == initiative_id,
            InitiativeMember.user_id == user_id,
        )
    )
    result = await session.exec(stmt)
    return result.one_or_none()


async def ensure_managers_remain(
    session: AsyncSession,
    *,
    initiative_id: int,
    excluded_user_ids: Iterable[int] | None = None,
) -> None:
    """Ensure at least one manager remains after excluding certain users."""
    excluded = set(excluded_user_ids or [])
    stmt = (
        select(InitiativeMember)
        .join(InitiativeRoleModel, InitiativeRoleModel.id == InitiativeMember.role_id)
        .where(
            InitiativeMember.initiative_id == initiative_id,
            InitiativeRoleModel.is_manager.is_(True),
        )
    )
    result = await session.exec(stmt)
    managers = [membership for membership in result.all() if membership.user_id not in excluded]
    if not managers:
        raise ValueError(InitiativeMessages.MUST_HAVE_PM)


async def initiatives_requiring_new_pm(
    session: AsyncSession,
    user_id: int,
    *,
    guild_id: int | None = None,
) -> list[Initiative]:
    """Find initiatives where user is the sole manager."""
    # Find initiatives where user has a manager role
    user_manager_initiatives = (
        select(InitiativeMember.initiative_id)
        .join(InitiativeRoleModel, InitiativeRoleModel.id == InitiativeMember.role_id)
        .where(
            InitiativeMember.user_id == user_id,
            InitiativeRoleModel.is_manager.is_(True),
        )
    )

    # Count managers per initiative
    manager_count_subquery = (
        select(
            InitiativeMember.initiative_id,
            func.count().label("manager_count"),
        )
        .join(InitiativeRoleModel, InitiativeRoleModel.id == InitiativeMember.role_id)
        .where(InitiativeRoleModel.is_manager.is_(True))
        .group_by(InitiativeMember.initiative_id)
        .subquery()
    )

    stmt = (
        select(Initiative)
        .join(manager_count_subquery, manager_count_subquery.c.initiative_id == Initiative.id)
        .where(
            Initiative.id.in_(user_manager_initiatives),
            manager_count_subquery.c.manager_count == 1,
        )
    )
    if guild_id is not None:
        stmt = stmt.where(Initiative.guild_id == guild_id)
    result = await session.exec(stmt)
    return list(result.unique().all())


async def ensure_user_not_sole_pm(
    session: AsyncSession,
    user_id: int,
    *,
    guild_id: int | None = None,
) -> None:
    initiatives = await initiatives_requiring_new_pm(session, user_id, guild_id=guild_id)
    if initiatives:
        names = ", ".join(initiative.name for initiative in initiatives)
        raise ValueError(f"User is the sole project manager for: {names}")


async def clear_user_task_assignments_for_initiative(
    session: AsyncSession,
    *,
    initiative_id: int,
    user_id: int,
) -> None:
    """Remove task assignments for a user across all projects in an initiative."""
    from app.models.task import Task, TaskAssignee
    from app.models.project import Project

    project_ids_result = await session.exec(
        select(Project.id).where(Project.initiative_id == initiative_id)
    )
    project_ids = list(project_ids_result.all())
    if not project_ids:
        return

    task_ids_result = await session.exec(
        select(Task.id).where(Task.project_id.in_(tuple(project_ids)))
    )
    task_ids = list(task_ids_result.all())
    if not task_ids:
        return

    await session.exec(
        delete(TaskAssignee)
        .where(TaskAssignee.user_id == user_id)
        .where(TaskAssignee.task_id.in_(tuple(task_ids)))
    )


async def remove_user_from_guild_initiatives(
    session: AsyncSession,
    *,
    guild_id: int,
    user_id: int,
) -> None:
    """Remove a user from all initiatives in a guild, clearing task assignments."""
    # Find initiatives in this guild where the user is a member
    initiative_ids_result = await session.exec(
        select(InitiativeMember.initiative_id).where(
            InitiativeMember.user_id == user_id,
            InitiativeMember.initiative_id.in_(
                select(Initiative.id).where(Initiative.guild_id == guild_id)
            ),
        )
    )
    initiative_ids = list(initiative_ids_result.all())

    # Clear task assignments for each initiative
    for init_id in initiative_ids:
        await clear_user_task_assignments_for_initiative(
            session, initiative_id=init_id, user_id=user_id,
        )

    # Remove initiative memberships
    stmt = delete(InitiativeMember).where(
        InitiativeMember.user_id == user_id,
        InitiativeMember.initiative_id.in_(
            select(Initiative.id).where(Initiative.guild_id == guild_id)
        ),
    )
    await session.exec(stmt)


async def list_initiative_roles(
    session: AsyncSession,
    *,
    initiative_id: int,
) -> list[InitiativeRoleModel]:
    """List all roles for an initiative with their permissions."""
    stmt = (
        select(InitiativeRoleModel)
        .options(selectinload(InitiativeRoleModel.permissions))
        .where(InitiativeRoleModel.initiative_id == initiative_id)
        .order_by(InitiativeRoleModel.position, InitiativeRoleModel.id)
    )
    result = await session.exec(stmt)
    return list(result.all())


async def get_role_by_id(
    session: AsyncSession,
    *,
    role_id: int,
    initiative_id: int | None = None,
) -> InitiativeRoleModel | None:
    """Get a role by ID, optionally verifying it belongs to an initiative."""
    stmt = (
        select(InitiativeRoleModel)
        .options(selectinload(InitiativeRoleModel.permissions))
        .where(InitiativeRoleModel.id == role_id)
    )
    if initiative_id is not None:
        stmt = stmt.where(InitiativeRoleModel.initiative_id == initiative_id)
    result = await session.exec(stmt)
    return result.one_or_none()


async def create_custom_role(
    session: AsyncSession,
    *,
    initiative_id: int,
    name: str,
    display_name: str,
    is_manager: bool = False,
    permissions: dict[str, bool] | None = None,
) -> InitiativeRoleModel:
    """Create a custom role for an initiative."""
    # Get next position
    stmt = select(func.max(InitiativeRoleModel.position)).where(
        InitiativeRoleModel.initiative_id == initiative_id
    )
    result = await session.exec(stmt)
    max_position = result.one() or 0

    role = InitiativeRoleModel(
        initiative_id=initiative_id,
        name=name,
        display_name=display_name,
        is_builtin=False,
        is_manager=is_manager,
        position=max_position + 1,
    )
    session.add(role)
    await session.flush()

    # Add permissions (default to member permissions if not specified)
    perms = permissions or {k.value: v for k, v in BUILTIN_ROLE_PERMISSIONS["member"].items()}
    for perm_key, enabled in perms.items():
        session.add(InitiativeRolePermission(
            initiative_role_id=role.id,
            permission_key=perm_key,
            enabled=enabled,
        ))

    await session.flush()
    await session.refresh(role, attribute_names=["permissions"])
    return role


async def update_role_permissions(
    session: AsyncSession,
    *,
    role: InitiativeRoleModel,
    permissions: dict[str, bool],
) -> InitiativeRoleModel:
    """Update permissions for a role."""
    for perm_key, enabled in permissions.items():
        # Find existing permission
        existing = next(
            (p for p in role.permissions if p.permission_key == perm_key),
            None,
        )
        if existing:
            existing.enabled = enabled
            session.add(existing)
        else:
            session.add(InitiativeRolePermission(
                initiative_role_id=role.id,
                permission_key=perm_key,
                enabled=enabled,
            ))
    await session.flush()
    await session.refresh(role, attribute_names=["permissions"])
    return role


async def delete_role(
    session: AsyncSession,
    *,
    role: InitiativeRoleModel,
) -> None:
    """Delete a custom role. Cannot delete built-in roles."""
    if role.is_builtin:
        raise ValueError(InitiativeMessages.CANNOT_DELETE_BUILTIN)

    # Check if any members use this role
    stmt = select(func.count()).where(InitiativeMember.role_id == role.id)
    result = await session.exec(stmt)
    member_count = result.one()
    if member_count > 0:
        raise ValueError(InitiativeMessages.ROLE_HAS_MEMBERS)

    await session.delete(role)
    await session.flush()


async def count_role_members(
    session: AsyncSession,
    *,
    role_id: int,
) -> int:
    """Count members assigned to a role."""
    stmt = select(func.count()).where(InitiativeMember.role_id == role_id)
    result = await session.exec(stmt)
    return result.one()
