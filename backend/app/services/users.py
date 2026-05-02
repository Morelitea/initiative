from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List

from sqlalchemy import func, update
from sqlmodel import select, delete
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.encryption import encrypt_field, hash_email, SALT_EMAIL
from app.core.security import get_password_hash
from app.models.user import User, UserRole, UserStatus
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

SYSTEM_USER_EMAIL = "deleted-user@system.internal"
SYSTEM_USER_FULL_NAME = "[Deleted User]"


class DeletionBlocker(Exception):
    """Raised when account deletion is blocked."""

    def __init__(self, blockers: List[str]):
        self.blockers = blockers
        super().__init__(", ".join(blockers))


async def get_or_create_system_user(session: AsyncSession) -> User:
    """Get or create the system user for deleted user content."""
    stmt = select(User).where(User.email_hash == hash_email(SYSTEM_USER_EMAIL))
    result = await session.exec(stmt)
    system_user = result.one_or_none()

    if system_user:
        return system_user

    # Create system user
    now = datetime.now(timezone.utc)
    system_user = User(
        email_hash=hash_email(SYSTEM_USER_EMAIL),
        email_encrypted=encrypt_field(SYSTEM_USER_EMAIL, SALT_EMAIL),
        full_name=SYSTEM_USER_FULL_NAME,
        hashed_password=get_password_hash("SYSTEM_USER_NO_LOGIN"),
        status=UserStatus.deactivated,
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


async def get_guild_blocker_details(
    session: AsyncSession, user_id: int
) -> List[dict]:
    """
    Get detailed info about guilds where user is the last admin.
    Returns list of dicts with guild_id, guild_name, and other_members who could be promoted.
    """
    from app.models.guild import Guild

    stmt = (
        select(GuildMembership)
        .where(
            GuildMembership.user_id == user_id,
            GuildMembership.role == GuildRole.admin,
        )
    )
    result = await session.exec(stmt)
    user_admin_memberships = result.all()

    blockers = []

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
            # User is the last admin - get guild info and other members
            guild_stmt = select(Guild).where(Guild.id == membership.guild_id)
            guild_result = await session.exec(guild_stmt)
            guild = guild_result.one_or_none()
            if not guild:
                continue

            # Get other members who could be promoted
            members_stmt = (
                select(User)
                .join(GuildMembership, GuildMembership.user_id == User.id)
                .where(
                    GuildMembership.guild_id == membership.guild_id,
                    GuildMembership.user_id != user_id,
                    User.status == UserStatus.active,
                )
            )
            members_result = await session.exec(members_stmt)
            other_members = members_result.all()

            blockers.append({
                "guild_id": guild.id,
                "guild_name": guild.name,
                "other_members": other_members,
            })

    return blockers


async def get_initiative_blocker_details(
    session: AsyncSession, user_id: int
) -> List[dict]:
    """
    Get detailed info about initiatives where user is the sole PM.
    Returns list of dicts with initiative_id, initiative_name, guild_id, and other_members.
    """
    from app.models.initiative import Initiative, InitiativeMember, InitiativeRoleModel

    # Find initiatives where user is sole manager (PM).
    # InitiativeMember links to InitiativeRoleModel via role_id;
    # manager roles have is_manager=True.
    manager_count_subquery = (
        select(
            InitiativeMember.initiative_id,
            func.count().label("pm_count"),
        )
        .join(InitiativeRoleModel, InitiativeRoleModel.id == InitiativeMember.role_id)
        .where(InitiativeRoleModel.is_manager.is_(True))
        .group_by(InitiativeMember.initiative_id)
        .subquery()
    )

    user_manager_initiatives = (
        select(InitiativeMember.initiative_id)
        .join(InitiativeRoleModel, InitiativeRoleModel.id == InitiativeMember.role_id)
        .where(
            InitiativeMember.user_id == user_id,
            InitiativeRoleModel.is_manager.is_(True),
        )
    )

    stmt = (
        select(Initiative)
        .join(manager_count_subquery, manager_count_subquery.c.initiative_id == Initiative.id)
        .where(
            Initiative.id.in_(user_manager_initiatives),
            manager_count_subquery.c.pm_count == 1,
        )
    )
    result = await session.exec(stmt)
    initiatives = result.unique().all()

    blockers = []

    for initiative in initiatives:
        # Get other members who could be promoted to PM
        members_stmt = (
            select(User)
            .join(InitiativeMember, InitiativeMember.user_id == User.id)
            .where(
                InitiativeMember.initiative_id == initiative.id,
                InitiativeMember.user_id != user_id,
                User.status == UserStatus.active,
            )
        )
        members_result = await session.exec(members_stmt)
        other_members = members_result.all()

        blockers.append({
            "initiative_id": initiative.id,
            "initiative_name": initiative.name,
            "guild_id": initiative.guild_id,
            "other_members": other_members,
        })

    return blockers


async def get_owned_projects(session: AsyncSession, user_id: int) -> List[Project]:
    """Get all projects owned by the user."""
    stmt = select(Project).where(Project.owner_id == user_id)
    result = await session.exec(stmt)
    return list(result.all())


async def get_owned_projects_in_guild(
    session: AsyncSession, user_id: int, guild_id: int
) -> List[Project]:
    """Projects in a single guild whose ``owner_id`` is the user.

    Used by the leave-guild flow: if the user leaves without
    transferring these, the project's RLS guard (``InitiativeMember``)
    no longer matches for them, and there's no guild-admin DAC bypass,
    so the row becomes unreachable.
    """
    from app.models.initiative import Initiative

    stmt = (
        select(Project)
        .join(Initiative, Initiative.id == Project.initiative_id)
        .where(Project.owner_id == user_id, Initiative.guild_id == guild_id)
    )
    result = await session.exec(stmt)
    return list(result.all())


async def check_deletion_eligibility(
    session: AsyncSession,
    user_id: int,
    *,
    admin_context: bool = False,
) -> tuple[bool, List[str], List[str], List[Project]]:
    """
    Check if user can be deleted.
    Returns: (can_delete, blockers, warnings, owned_projects)

    Args:
        session: Database session
        user_id: ID of the user to check
        admin_context: If True, adjust message wording for admin perspective
    """
    from app.services import initiatives as initiatives_service

    blockers = []
    warnings = []

    # Check if user is last admin of any guild
    last_admin_guilds = await is_last_guild_admin(session, user_id)
    if last_admin_guilds:
        for guild_name in last_admin_guilds:
            if admin_context:
                blockers.append(
                    f"User is the last admin of guild '{guild_name}'. "
                    f"Another user must be promoted to admin or the guild must be deleted first."
                )
            else:
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
            if admin_context:
                blockers.append(
                    f"User is the sole project manager of initiative '{initiative.name}'. "
                    f"Another member must be promoted to project manager or the initiative must be deleted first."
                )
            else:
                blockers.append(
                    f"You are the sole project manager of initiative '{initiative.name}'. "
                    f"Promote another member to project manager or delete the initiative before deleting your account."
                )

    # Get owned projects
    owned_projects = await get_owned_projects(session, user_id)
    if owned_projects:
        if admin_context:
            warnings.append(f"User owns {len(owned_projects)} project(s) that must be transferred")
        else:
            warnings.append(f"You own {len(owned_projects)} project(s) that must be transferred")

    can_delete = len(blockers) == 0

    return can_delete, blockers, warnings, owned_projects


async def _drop_user_memberships(session: AsyncSession, user_id: int) -> User:
    """Remove the user from every guild and initiative they belong to,
    handing owned documents off to PMs along the way. Returns the loaded
    ``User`` row but does NOT commit — the caller is responsible for
    issuing exactly one commit so its own status / PII writes land in
    the same transaction as the membership cleanup.

    Splitting the membership work out of ``deactivate_user`` lets
    ``soft_delete_user`` perform PII erasure atomically: a failure
    during anonymization rolls back the membership delete too, instead
    of leaving the user as a half-deactivated row with PII intact.
    """
    from app.services import initiatives as initiatives_service

    user = (await session.exec(select(User).where(User.id == user_id))).one()

    memberships = (
        await session.exec(
            select(GuildMembership).where(GuildMembership.user_id == user_id)
        )
    ).all()

    for membership in memberships:
        await initiatives_service.remove_user_from_guild_initiatives(
            session,
            guild_id=membership.guild_id,
            user_id=user_id,
        )

    for membership in memberships:
        await session.delete(membership)

    return user


async def deactivate_user(session: AsyncSession, user_id: int) -> None:
    """Reversibly deactivate a user account.

    Sets ``status = deactivated``, drops the user from every guild and
    initiative they belong to, and bumps ``token_version`` so any
    outstanding JWTs stop authenticating. PII (name, email, avatar) is
    left intact so the user can be reactivated by an admin later.
    """
    user = await _drop_user_memberships(session, user_id)
    # Owned documents are handed off to other initiative PMs inside
    # ``_drop_user_memberships`` above, before the InitiativeMember
    # rows are dropped.
    user.status = UserStatus.deactivated
    user.token_version += 1
    user.updated_at = datetime.now(timezone.utc)
    session.add(user)
    await session.commit()


async def soft_delete_user(session: AsyncSession, user_id: int) -> None:
    """Soft-delete (anonymize) a user account.

    Drops memberships like ``deactivate_user``, then strips every PII
    field on the row, randomises ``email_hash`` / ``email_encrypted`` so
    no future signup or admin lookup can resolve to this row, blanks the
    password hash, and revokes auth artifacts (API keys, push tokens,
    user_tokens). The row stays so existing FKs (comment authors, task
    assignees, project owners, …) continue to resolve and the UI can
    render the placeholder "Deleted user #{id}" wherever the original
    user was referenced.

    All of this happens inside a single transaction with one commit at
    the end, so a "right to be forgotten" request never ends up in a
    half-applied state — either every change lands or none do.

    This is irreversible — there is no undo.
    """
    import secrets
    from app.models.push_token import PushToken

    user = await _drop_user_memberships(session, user_id)

    user.status = UserStatus.anonymized
    user.token_version += 1
    # Demote any platform admin to member. The row is now an empty husk
    # that can't act on anything; leaving the admin role on it would be
    # misleading in audit views and would inflate any role-only count
    # that doesn't also filter by status.
    user.role = UserRole.member

    # Replace email with a sentinel that won't collide on the unique index
    # and can't be looked up by anyone trying to authenticate. The
    # encrypted blob holds the same nonsense so decryption (if ever invoked)
    # yields a string that's obviously not a real email. Domain is
    # RFC 2606 example.com so EmailStr serialization on user-facing
    # endpoints (admin user list, etc.) doesn't reject the row.
    sentinel_email = f"anonymized-{user_id}-{secrets.token_hex(8)}@anonymized.example.com"
    user.email_hash = hash_email(sentinel_email)
    user.email_encrypted = encrypt_field(sentinel_email, SALT_EMAIL)

    # Unguessable random password hash — matches the SYSTEM_USER pattern.
    user.hashed_password = get_password_hash(secrets.token_urlsafe(32))

    # Strip the rest of the PII surface.
    user.full_name = None
    user.avatar_base64 = None
    user.avatar_url = None
    user.oidc_sub = None
    user.oidc_refresh_token_encrypted = None
    user.ai_api_key_encrypted = None

    # Reset notification + interface preferences to defaults so the row
    # doesn't leak the user's behavioural profile.
    user.email_initiative_addition = True
    user.email_task_assignment = True
    user.email_project_added = True
    user.email_overdue_tasks = True
    user.email_mentions = True
    user.push_initiative_addition = True
    user.push_task_assignment = True
    user.push_project_added = True
    user.push_overdue_tasks = True
    user.push_mentions = True

    user.updated_at = datetime.now(timezone.utc)
    session.add(user)

    # Revoke auth artifacts. Whatever short-lived tokens existed are now
    # meaningless because token_version was bumped, but we still drop the
    # rows so they don't sit in the DB attributed to a "Deleted user".
    await session.exec(delete(UserApiKey).where(UserApiKey.user_id == user_id))
    await session.exec(delete(UserToken).where(UserToken.user_id == user_id))
    await session.exec(delete(PushToken).where(PushToken.user_id == user_id))

    # Single commit: membership removal + PII wipe + auth-artifact
    # revocation either all succeed or all roll back together.
    await session.commit()


class InvalidTransferRecipient(Exception):
    """Raised when a project transfer target isn't a valid owner."""


async def transfer_project_ownership(
    session: AsyncSession,
    project_id: int,
    new_owner_id: int,
) -> None:
    """Transfer project ownership to another user.

    Refuses to transfer to a user who isn't ``active`` — anonymized
    husks and deactivated accounts can't act on projects, so handing
    one a project would strand it. The transfer-target picker on
    self-delete and admin-delete dialogs already filters non-active
    users out (``GET /users/me/initiative-members`` and
    ``GET /admin/initiatives/.../members``); this is the server-side
    safety net for clients that bypass those endpoints.

    Drops the previous owner's ``ProjectPermission`` row as part of
    the transfer. Every call site is a "user is leaving" path
    (self-deactivation, leave-guild, admin-removal, OIDC sync), so
    the departing user shouldn't retain access — and leaving the
    stale ``level=owner`` row behind has bitten us before: if that
    user is later reactivated and re-added, the project shows two
    owner-level permissions and the access dropdown can't reconcile
    the value.
    """
    project = (await session.exec(select(Project).where(Project.id == project_id))).one()

    new_owner = (
        await session.exec(select(User).where(User.id == new_owner_id))
    ).one_or_none()
    if new_owner is None or new_owner.status != UserStatus.active:
        raise InvalidTransferRecipient(
            f"Project {project_id} transfer target {new_owner_id} is not an active user"
        )

    previous_owner_id = project.owner_id
    project.owner_id = new_owner_id
    project.updated_at = datetime.now(timezone.utc)
    session.add(project)
    await session.flush()

    # Drop the previous owner's per-user permission row (if any) before
    # creating / upgrading the new owner's. Skipped when transferring
    # to oneself (no-op) or when the previous owner happens to be the
    # new owner — ``previous_owner_id != new_owner_id`` covers both.
    if previous_owner_id is not None and previous_owner_id != new_owner_id:
        await session.exec(
            delete(ProjectPermission).where(
                ProjectPermission.project_id == project_id,
                ProjectPermission.user_id == previous_owner_id,
            )
        )

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
    """Reassign shared content authored by the user to the system user.

    Hard delete vaporises the user row, but content the rest of the team
    can still see (documents, comments, uploaded files) must outlive the
    deletion. Reassign the authorship pointer to the dedicated system
    user so those rows remain valid.
    """
    from app.models.upload import Upload

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

    # Uploads (e.g. document images shared with other initiative members).
    # Reassign rather than delete so shared content keeps working.
    await session.exec(
        update(Upload)
        .where(Upload.uploader_user_id == user_id)
        .values(uploader_user_id=system_user_id)
    )

    # Queues created by the user (created_by_id is NOT NULL) get reassigned
    # to the system user so the queue itself survives. Items inside the
    # queue that point at the user (assigned-to) are nullable so we just
    # clear the pointer below in hard_delete_user.
    from app.models.queue import Queue

    await session.exec(
        update(Queue)
        .where(Queue.created_by_id == user_id)
        .values(created_by_id=system_user_id)
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
            User.status == UserStatus.active,
        ).with_for_update()
        result = await session.exec(stmt)
        admins = result.all()
        return len(admins)
    else:
        stmt = select(func.count(User.id)).where(
            User.role == UserRole.admin,
            User.status == UserStatus.active,
        )
        result = await session.exec(stmt)
        return result.one()


async def is_last_platform_admin(
    session: AsyncSession, user_id: int, *, for_update: bool = False
) -> bool:
    """True iff removing this user would leave zero active platform admins.

    A non-admin target, or an admin target whose ``status`` isn't
    ``active``, doesn't contribute to the active-admin count
    (``count_platform_admins`` filters by status), so removing them
    can't drop the count to zero — return False in those cases.
    Otherwise count OTHER active admins and return True iff none exist.

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
    if not user or user.role != UserRole.admin or user.status != UserStatus.active:
        return False

    # PostgreSQL rejects ``SELECT COUNT(...) FOR UPDATE`` (aggregates
    # can't take row locks), so the for_update path locks the candidate
    # rows themselves and counts them in Python — same trick
    # ``count_platform_admins`` uses for the same reason.
    if for_update:
        other_admins_stmt = (
            select(User)
            .where(
                User.role == UserRole.admin,
                User.status == UserStatus.active,
                User.id != user_id,
            )
            .with_for_update()
        )
        others = (await session.exec(other_admins_stmt)).all()
        return len(others) == 0
    else:
        other_admins_stmt = select(func.count(User.id)).where(
            User.role == UserRole.admin,
            User.status == UserStatus.active,
            User.id != user_id,
        )
        other_count = (await session.exec(other_admins_stmt)).one()
        return other_count == 0


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

    # Walk every guild the user is in and run the standard
    # initiative-removal flow so document ownership transfers to PMs
    # before the bulk DocumentPermission delete below would have wiped
    # the owner row entirely. Mirrors what ``deactivate_user`` does.
    from app.services import initiatives as initiatives_service

    guild_memberships_stmt = select(GuildMembership.guild_id).where(
        GuildMembership.user_id == user_id
    )
    guild_ids = list((await session.exec(guild_memberships_stmt)).all())
    for gid in guild_ids:
        await initiatives_service.remove_user_from_guild_initiatives(
            session, guild_id=gid, user_id=user_id,
        )

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

    # Other per-user state without ON DELETE CASCADE on the FK.
    from app.models.queue import QueueItem, QueuePermission
    from app.models.document import DocumentPermission
    from app.models.push_token import PushToken
    from app.models.calendar_event import CalendarEventAttendee
    from app.models.property import (
        TaskPropertyValue,
        DocumentPropertyValue,
        CalendarEventPropertyValue,
    )

    await session.exec(delete(QueuePermission).where(QueuePermission.user_id == user_id))
    # Queue items: assigned-to is nullable, so just clear the pointer
    # rather than dropping the queue entry.
    await session.exec(
        update(QueueItem).where(QueueItem.user_id == user_id).values(user_id=None)
    )
    await session.exec(delete(DocumentPermission).where(DocumentPermission.user_id == user_id))
    await session.exec(delete(PushToken).where(PushToken.user_id == user_id))
    await session.exec(
        delete(CalendarEventAttendee).where(CalendarEventAttendee.user_id == user_id)
    )

    # User-typed custom-property values: NULL the reference (the property
    # value rows belong to the entity, not the user, so we don't delete
    # them — we just clear the resolved user pointer).
    for table in (TaskPropertyValue, DocumentPropertyValue, CalendarEventPropertyValue):
        await session.exec(
            update(table)
            .where(table.value_user_id == user_id)
            .values(value_user_id=None)
        )

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
