from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List

from sqlalchemy import func, update
from sqlmodel import select, delete
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.security import get_password_hash
from app.models.user import User
from app.models.guild import GuildMembership, GuildRole
from app.models.project import Project, ProjectPermission
from app.models.task import TaskAssignee
from app.models.document import Document, ProjectDocument
from app.models.comment import Comment
from app.models.notification import Notification
from app.models.project_order import ProjectOrder
from app.models.project_activity import ProjectFavorite, RecentProjectView
from app.models.api_key import UserApiKey
from app.models.user_token import UserToken
from app.models.task_assignment_digest import TaskAssignmentDigestItem
from app.models.user import UserRole

SYSTEM_USER_EMAIL = "deleted-user@system.internal"
SYSTEM_USER_FULL_NAME = "[Deleted User]"


class DeletionBlocker(Exception):
    """Raised when account deletion is blocked."""

    def __init__(self, blockers: List[str]):
        self.blockers = blockers
        super().__init__(", ".join(blockers))


async def get_or_create_system_user(session: AsyncSession) -> User:
    """Get or create the system user for deleted user content."""
    stmt = select(User).where(func.lower(User.email) == SYSTEM_USER_EMAIL.lower())
    result = await session.exec(stmt)
    system_user = result.one_or_none()

    if system_user:
        return system_user

    # Create system user
    now = datetime.now(timezone.utc)
    system_user = User(
        email=SYSTEM_USER_EMAIL,
        full_name=SYSTEM_USER_FULL_NAME,
        hashed_password=get_password_hash("SYSTEM_USER_NO_LOGIN"),
        is_active=False,
        email_verified=True,
        created_at=now,
        updated_at=now,
    )
    session.add(system_user)
    await session.flush()
    return system_user


async def is_last_admin_of_guild(
    session: AsyncSession, guild_id: int, user_id: int, *, for_update: bool = False
) -> bool:
    """
    Check if user is the last admin of a specific guild.

    Args:
        session: Database session
        guild_id: Guild ID to check
        user_id: User ID to check
        for_update: If True, lock rows to prevent race conditions during demotion
    """
    # Check if user is an admin of this guild
    if for_update:
        membership_stmt = (
            select(GuildMembership)
            .where(
                GuildMembership.guild_id == guild_id,
                GuildMembership.user_id == user_id,
            )
            .with_for_update()
        )
    else:
        membership_stmt = select(GuildMembership).where(
            GuildMembership.guild_id == guild_id,
            GuildMembership.user_id == user_id,
        )
    result = await session.exec(membership_stmt)
    membership = result.one_or_none()

    if not membership or membership.role != GuildRole.admin:
        return False

    # Count all admins in this guild (with lock if for_update)
    if for_update:
        admin_stmt = (
            select(GuildMembership)
            .where(
                GuildMembership.guild_id == guild_id,
                GuildMembership.role == GuildRole.admin,
            )
            .with_for_update()
        )
        admin_result = await session.exec(admin_stmt)
        admin_count = len(admin_result.all())
    else:
        count_stmt = select(func.count(GuildMembership.user_id)).where(
            GuildMembership.guild_id == guild_id,
            GuildMembership.role == GuildRole.admin,
        )
        count_result = await session.exec(count_stmt)
        admin_count = count_result.one()

    return admin_count <= 1


async def is_last_guild_admin(session: AsyncSession, user_id: int) -> List[str]:
    """
    Check if user is the last admin of any guild.
    Returns list of guild names where user is the last admin.
    """
    # Get all guilds where user is an admin
    stmt = (
        select(GuildMembership)
        .where(
            GuildMembership.user_id == user_id,
            GuildMembership.role == GuildRole.admin,
        )
    )
    result = await session.exec(stmt)
    user_admin_memberships = result.all()

    last_admin_guild_names = []

    for membership in user_admin_memberships:
        # Count other admins in this guild
        count_stmt = (
            select(func.count(GuildMembership.user_id))
            .where(
                GuildMembership.guild_id == membership.guild_id,
                GuildMembership.role == GuildRole.admin,
                GuildMembership.user_id != user_id,
            )
        )
        count_result = await session.exec(count_stmt)
        other_admin_count = count_result.one()

        if other_admin_count == 0:
            # User is the last admin, get guild name
            from app.models.guild import Guild
            guild_stmt = select(Guild).where(Guild.id == membership.guild_id)
            guild_result = await session.exec(guild_stmt)
            guild = guild_result.one_or_none()
            if guild:
                last_admin_guild_names.append(guild.name)

    return last_admin_guild_names


async def get_owned_projects(session: AsyncSession, user_id: int) -> List[Project]:
    """Get all projects owned by the user."""
    stmt = select(Project).where(Project.owner_id == user_id)
    result = await session.exec(stmt)
    return list(result.all())


async def check_deletion_eligibility(
    session: AsyncSession,
    user_id: int,
) -> tuple[bool, List[str], List[str], List[Project]]:
    """
    Check if user can be deleted.
    Returns: (can_delete, blockers, warnings, owned_projects)
    """
    from app.services import initiatives as initiatives_service

    blockers = []
    warnings = []

    # Check if user is last admin of any guild
    last_admin_guilds = await is_last_guild_admin(session, user_id)
    if last_admin_guilds:
        for guild_name in last_admin_guilds:
            blockers.append(
                f"You are the last admin of guild '{guild_name}'. "
                f"Promote another user to admin or delete the guild before deleting your account."
            )

    # Check if user is sole PM of any initiative
    sole_pm_initiatives = await initiatives_service.initiatives_requiring_new_pm(
        session, user_id
    )
    if sole_pm_initiatives:
        for initiative in sole_pm_initiatives:
            blockers.append(
                f"You are the sole project manager of initiative '{initiative.name}'. "
                f"Promote another member to project manager or delete the initiative before deleting your account."
            )

    # Get owned projects
    owned_projects = await get_owned_projects(session, user_id)
    if owned_projects:
        warnings.append(f"You own {len(owned_projects)} project(s) that must be transferred")

    can_delete = len(blockers) == 0

    return can_delete, blockers, warnings, owned_projects


async def soft_delete_user(session: AsyncSession, user_id: int) -> None:
    """Soft delete (deactivate) a user account and remove from all guilds/initiatives."""
    from app.services import initiatives as initiatives_service

    stmt = select(User).where(User.id == user_id)
    result = await session.exec(stmt)
    user = result.one()

    # Get all guild memberships to remove from initiatives
    guild_stmt = select(GuildMembership).where(GuildMembership.user_id == user_id)
    guild_result = await session.exec(guild_stmt)
    memberships = guild_result.all()

    # Remove from all guild initiatives
    for membership in memberships:
        await initiatives_service.remove_user_from_guild_initiatives(
            session,
            guild_id=membership.guild_id,
            user_id=user_id,
        )

    # Delete all guild memberships
    for membership in memberships:
        await session.delete(membership)

    # Deactivate user
    user.is_active = False
    user.active_guild_id = None
    user.updated_at = datetime.now(timezone.utc)
    session.add(user)
    await session.commit()


async def transfer_project_ownership(
    session: AsyncSession,
    project_id: int,
    new_owner_id: int,
) -> None:
    """Transfer project ownership to another user."""
    stmt = select(Project).where(Project.id == project_id)
    result = await session.exec(stmt)
    project = result.one()

    project.owner_id = new_owner_id
    project.updated_at = datetime.now(timezone.utc)
    session.add(project)
    await session.flush()

    # Ensure new owner has owner permission
    perm_stmt = select(ProjectPermission).where(
        ProjectPermission.project_id == project_id,
        ProjectPermission.user_id == new_owner_id,
    )
    perm_result = await session.exec(perm_stmt)
    permission = perm_result.one_or_none()

    if permission:
        from app.models.project import ProjectPermissionLevel
        permission.level = ProjectPermissionLevel.owner
        session.add(permission)
    else:
        from app.models.project import ProjectPermissionLevel
        permission = ProjectPermission(
            project_id=project_id,
            user_id=new_owner_id,
            level=ProjectPermissionLevel.owner,
        )
        session.add(permission)

    await session.flush()


async def reassign_user_content(
    session: AsyncSession,
    user_id: int,
    system_user_id: int,
) -> None:
    """Reassign user's created content to the system user."""
    # Update documents created_by
    await session.exec(
        update(Document)
        .where(Document.created_by_id == user_id)
        .values(created_by_id=system_user_id)
    )

    # Update documents updated_by
    await session.exec(
        update(Document)
        .where(Document.updated_by_id == user_id)
        .values(updated_by_id=system_user_id)
    )

    # Update comments author
    await session.exec(
        update(Comment)
        .where(Comment.author_id == user_id)
        .values(author_id=system_user_id)
    )

    # Update project documents attached_by (nullable)
    await session.exec(
        update(ProjectDocument)
        .where(ProjectDocument.attached_by_id == user_id)
        .values(attached_by_id=system_user_id)
    )

    await session.flush()


async def count_platform_admins(session: AsyncSession, *, for_update: bool = False) -> int:
    """Count active platform admin users.

    Args:
        session: Database session
        for_update: If True, lock the admin user rows to prevent race conditions
    """
    if for_update:
        # Lock all admin users to prevent race condition when demoting
        stmt = select(User).where(
            User.role == UserRole.admin,
            User.is_active == True,  # noqa: E712
        ).with_for_update()
        result = await session.exec(stmt)
        admins = result.all()
        return len(admins)
    else:
        stmt = select(func.count(User.id)).where(
            User.role == UserRole.admin,
            User.is_active == True,  # noqa: E712
        )
        result = await session.exec(stmt)
        return result.one()


async def is_last_platform_admin(
    session: AsyncSession, user_id: int, *, for_update: bool = False
) -> bool:
    """Check if user is the last remaining platform admin.

    Args:
        session: Database session
        user_id: User ID to check
        for_update: If True, lock rows to prevent race conditions during demotion
    """
    if for_update:
        stmt = select(User).where(User.id == user_id).with_for_update()
    else:
        stmt = select(User).where(User.id == user_id)
    result = await session.exec(stmt)
    user = result.one_or_none()
    if not user or user.role != UserRole.admin:
        return False
    return await count_platform_admins(session, for_update=for_update) <= 1


async def hard_delete_user(
    session: AsyncSession,
    user_id: int,
    project_transfers: Dict[int, int],
) -> None:
    """
    Permanently delete a user account.

    Args:
        session: Database session
        user_id: ID of user to delete
        project_transfers: Dict mapping project_id to new_owner_id
    """
    # Get system user
    system_user = await get_or_create_system_user(session)

    # Transfer all owned projects
    owned_projects = await get_owned_projects(session, user_id)
    for project in owned_projects:
        if project.id not in project_transfers:
            raise ValueError(f"No transfer recipient specified for project {project.id}")

        new_owner_id = project_transfers[project.id]
        await transfer_project_ownership(session, project.id, new_owner_id)

    # Reassign user content to system user
    await reassign_user_content(session, user_id, system_user.id)

    # Delete user-specific data (not shared content)

    # Notifications
    await session.exec(delete(Notification).where(Notification.user_id == user_id))

    # Project UI state
    await session.exec(delete(ProjectOrder).where(ProjectOrder.user_id == user_id))
    await session.exec(delete(ProjectFavorite).where(ProjectFavorite.user_id == user_id))
    await session.exec(delete(RecentProjectView).where(RecentProjectView.user_id == user_id))

    # User API keys
    await session.exec(delete(UserApiKey).where(UserApiKey.user_id == user_id))

    # User tokens (password reset, email verification)
    await session.exec(delete(UserToken).where(UserToken.user_id == user_id))

    # Task assignment digest items
    await session.exec(delete(TaskAssignmentDigestItem).where(TaskAssignmentDigestItem.user_id == user_id))

    # Update TaskAssignmentDigestItem assigned_by to NULL (nullable field)
    await session.exec(
        update(TaskAssignmentDigestItem)
        .where(TaskAssignmentDigestItem.assigned_by_id == user_id)
        .values(assigned_by_id=None)
    )

    # Delete associations with composite keys (must be explicit)
    await session.exec(delete(ProjectPermission).where(ProjectPermission.user_id == user_id))
    await session.exec(delete(TaskAssignee).where(TaskAssignee.user_id == user_id))

    # Clear nullable foreign key references
    from app.models.guild import Guild, GuildInvite

    # Clear guild creator references
    await session.exec(
        update(Guild)
        .where(Guild.created_by_user_id == user_id)
        .values(created_by_user_id=None)
    )

    # Clear guild invite creator references
    await session.exec(
        update(GuildInvite)
        .where(GuildInvite.created_by_user_id == user_id)
        .values(created_by_user_id=None)
    )

    # The following will cascade delete automatically via SQLAlchemy relationships:
    # - GuildMemberships (cascade="all, delete-orphan")
    # - InitiativeMembers (cascade="all, delete-orphan")

    # Delete the user
    stmt = select(User).where(User.id == user_id)
    result = await session.exec(stmt)
    user = result.one()
    await session.delete(user)

    await session.commit()
