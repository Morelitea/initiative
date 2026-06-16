from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List

from sqlalchemy import func, update
from sqlmodel import select, delete
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.capabilities import Capability, roles_with_capability
from app.core.encryption import encrypt_field, hash_email, SALT_EMAIL
from app.core.security import get_password_hash
from app.db.session import set_rls_context
from app.models.user import User, UserRole, UserStatus
from app.models.guild import GuildMembership, GuildRole
from app.models.project import Project, ProjectPermission
from app.models.task import TaskAssignee
from app.models.document import Document, ProjectDocument
from app.models.comment import Comment
from app.models.notification import Notification
from app.models.project_order import ProjectOrder
from app.models.project_activity import ProjectFavorite
from app.models.recent_view import RecentView
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
    stmt = select(GuildMembership).where(
        GuildMembership.user_id == user_id,
        GuildMembership.role == GuildRole.admin,
    )
    result = await session.exec(stmt)
    user_admin_memberships = result.all()

    last_admin_guild_names = []

    for membership in user_admin_memberships:
        # Count other admins in this guild
        count_stmt = select(func.count(GuildMembership.user_id)).where(
            GuildMembership.guild_id == membership.guild_id,
            GuildMembership.role == GuildRole.admin,
            GuildMembership.user_id != user_id,
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


async def get_guild_blocker_details(session: AsyncSession, user_id: int) -> List[dict]:
    """
    Get detailed info about guilds where user is the last admin.
    Returns list of dicts with guild_id, guild_name, and other_members who could be promoted.
    """
    from app.models.guild import Guild

    stmt = select(GuildMembership).where(
        GuildMembership.user_id == user_id,
        GuildMembership.role == GuildRole.admin,
    )
    result = await session.exec(stmt)
    user_admin_memberships = result.all()

    blockers = []

    for membership in user_admin_memberships:
        # Count other admins in this guild
        count_stmt = select(func.count(GuildMembership.user_id)).where(
            GuildMembership.guild_id == membership.guild_id,
            GuildMembership.role == GuildRole.admin,
            GuildMembership.user_id != user_id,
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

            blockers.append(
                {
                    "guild_id": guild.id,
                    "guild_name": guild.name,
                    "other_members": other_members,
                }
            )

    return blockers


async def _user_guild_ids(session: AsyncSession, user_id: int) -> List[int]:
    """Guild ids the user belongs to. ``guild_memberships`` is shared/public, so
    this needs no guild routing — it's the entry point for fanning per-guild
    routed reads/writes out across the user's guilds."""
    return list(
        (
            await session.exec(
                select(GuildMembership.guild_id).where(
                    GuildMembership.user_id == user_id
                )
            )
        ).all()
    )


async def get_initiative_blocker_details(
    session: AsyncSession, user_id: int
) -> List[dict]:
    """
    Get detailed info about initiatives where user is the sole PM.
    Returns list of dicts with initiative_id, initiative_name, guild_id, and other_members.

    Initiatives live in per-guild schemas, so this fans out across the user's
    guilds and runs the sole-PM query routed into each schema as superadmin.
    A single cross-schema query is impossible; querying the unrouted (public)
    default would read the frozen backup and miss every real blocker.
    """
    from app.models.initiative import Initiative, InitiativeMember, InitiativeRoleModel

    blockers: List[dict] = []
    for gid in await _user_guild_ids(session, user_id):
        session.expunge_all()
        await set_rls_context(session, guild_id=gid, is_superadmin=True)

        # Find initiatives where user is sole manager (PM). InitiativeMember
        # links to InitiativeRoleModel via role_id; manager roles have
        # is_manager=True.
        manager_count_subquery = (
            select(
                InitiativeMember.initiative_id,
                func.count().label("pm_count"),
            )
            .join(
                InitiativeRoleModel, InitiativeRoleModel.id == InitiativeMember.role_id
            )
            .where(InitiativeRoleModel.is_manager.is_(True))
            .group_by(InitiativeMember.initiative_id)
            .subquery()
        )
        user_manager_initiatives = (
            select(InitiativeMember.initiative_id)
            .join(
                InitiativeRoleModel, InitiativeRoleModel.id == InitiativeMember.role_id
            )
            .where(
                InitiativeMember.user_id == user_id,
                InitiativeRoleModel.is_manager.is_(True),
            )
        )
        stmt = (
            select(Initiative)
            .join(
                manager_count_subquery,
                manager_count_subquery.c.initiative_id == Initiative.id,
            )
            .where(
                Initiative.id.in_(user_manager_initiatives),
                manager_count_subquery.c.pm_count == 1,
            )
        )
        initiatives = (await session.exec(stmt)).unique().all()

        for initiative in initiatives:
            members_stmt = (
                select(User)
                .join(InitiativeMember, InitiativeMember.user_id == User.id)
                .where(
                    InitiativeMember.initiative_id == initiative.id,
                    InitiativeMember.user_id != user_id,
                    User.status == UserStatus.active,
                )
            )
            other_members = (await session.exec(members_stmt)).all()
            blockers.append(
                {
                    "initiative_id": initiative.id,
                    "initiative_name": initiative.name,
                    "guild_id": initiative.guild_id,
                    "other_members": other_members,
                }
            )

    # Reset to the public baseline so callers' subsequent reads aren't trapped
    # in the last guild's schema.
    session.expunge_all()
    await set_rls_context(session, is_superadmin=True)
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


async def fetch_pm_candidates(
    session: AsyncSession,
    *,
    initiative_id: int,
    excluded_user_id: int,
) -> List["UserPublic"]:  # noqa: F821 — forward ref to avoid circular import
    """Active project-manager candidates for ``initiative_id``, with
    ``excluded_user_id`` filtered out.

    Project ownership only requires initiative membership in principle,
    but for transfer-on-departure UX we restrict the picker to
    initiative managers — they're the role that actually administers
    the project, so handing them the row matches the user's intent and
    keeps them empowered to make further changes (reassign, rename,
    archive). Non-manager members can still appear via direct
    ``ProjectPermission`` rows; this helper just narrows the picker.

    Shared between the leave-eligibility (``guilds.py``) and admin
    remove-eligibility (``users.py``) endpoints so the rules don't
    drift between the two flows.
    """
    from app.models.initiative import InitiativeMember, InitiativeRoleModel
    from app.schemas.user import UserPublic

    stmt = (
        select(User)
        .join(InitiativeMember, InitiativeMember.user_id == User.id)
        .join(InitiativeRoleModel, InitiativeRoleModel.id == InitiativeMember.role_id)
        .where(
            InitiativeMember.initiative_id == initiative_id,
            InitiativeRoleModel.is_manager.is_(True),
            User.status == UserStatus.active,
            User.id != excluded_user_id,
        )
        .order_by(User.full_name, User.id)
    )
    result = await session.exec(stmt)
    return [UserPublic.model_validate(u) for u in result.all()]


async def check_deletion_eligibility(
    session: AsyncSession,
    user_id: int,
    *,
    admin_context: bool = False,
) -> tuple[bool, List[str], List[str], List["ProjectBasic"]]:  # noqa: F821
    """
    Check if user can be deleted.
    Returns: (can_delete, blockers, warnings, owned_projects)

    ``owned_projects`` are ``ProjectBasic`` (carrying ``guild_id``, since the
    projects are aggregated across the user's per-guild schemas) — the UI uses
    that guild id to call the guild-scoped transfer / member-picker endpoints.

    Args:
        session: Database session
        user_id: ID of the user to check
        admin_context: If True, adjust message wording for admin perspective
    """
    from app.services import initiatives as initiatives_service
    from app.schemas.user import ProjectBasic

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

    # Sole-PM initiatives and owned projects are guild-scoped: fan out across
    # the user's guilds, routed into each schema as superadmin, and aggregate.
    # (initiatives_requiring_new_pm / get_owned_projects on the unrouted public
    # default would read the frozen backup and under-report blockers — letting
    # a deletion proceed that should have been blocked.) The detached ORM rows
    # collected here are only read for scalar fields downstream, so expunging
    # between guilds (to avoid id-collision cache hits) is safe.
    sole_pm_initiatives: List = []
    owned_projects: List[ProjectBasic] = []
    for gid in await _user_guild_ids(session, user_id):
        session.expunge_all()
        await set_rls_context(session, guild_id=gid, is_superadmin=True)
        sole_pm_initiatives.extend(
            await initiatives_service.initiatives_requiring_new_pm(session, user_id)
        )
        # Capture each project's guild id (known from the routed context) so the
        # UI can target the right per-guild schema for transfers.
        owned_projects.extend(
            ProjectBasic(
                id=p.id, name=p.name, initiative_id=p.initiative_id, guild_id=gid
            )
            for p in await get_owned_projects(session, user_id)
        )
    session.expunge_all()
    await set_rls_context(session, is_superadmin=True)

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

    if owned_projects:
        if admin_context:
            warnings.append(
                f"User owns {len(owned_projects)} project(s) that must be transferred"
            )
        else:
            warnings.append(
                f"You own {len(owned_projects)} project(s) that must be transferred"
            )

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

    # ``guild_memberships`` is a shared/public table, so this enumerates the
    # user's guilds without needing any guild routing.
    guild_ids = list(
        (
            await session.exec(
                select(GuildMembership.guild_id).where(
                    GuildMembership.user_id == user_id
                )
            )
        ).all()
    )

    # Initiative membership + owned-document handoff is guild-scoped — its rows
    # live in each guild's schema. Route into every guild as superadmin (system
    # cleanup, bypasses RESTRICTIVE policies) before the per-guild work. No
    # commit here: we ``flush`` so the SQL lands in the shared transaction the
    # caller will commit once, preserving the atomicity guarantee. ``expunge_all``
    # between guilds avoids ORM identity-map collisions (ids repeat per schema).
    for gid in guild_ids:
        session.expunge_all()
        await set_rls_context(session, guild_id=gid, is_superadmin=True)
        await initiatives_service.remove_user_from_guild_initiatives(
            session,
            guild_id=gid,
            user_id=user_id,
        )
        await session.flush()

    # Back to the public, login-role baseline for the shared-table work: the
    # membership rows themselves and the caller's PII/status writes.
    session.expunge_all()
    await set_rls_context(session, is_superadmin=True)
    memberships = (
        await session.exec(
            select(GuildMembership).where(GuildMembership.user_id == user_id)
        )
    ).all()
    for membership in memberships:
        await session.delete(membership)

    return (await session.exec(select(User).where(User.id == user_id))).one()


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
    sentinel_email = (
        f"anonymized-{user_id}-{secrets.token_hex(8)}@anonymized.example.com"
    )
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
    project = (
        await session.exec(select(Project).where(Project.id == project_id))
    ).one()

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


async def transfer_owned_projects(
    session: AsyncSession,
    user_id: int,
    project_transfers: Dict[str, int],
) -> None:
    """Transfer every project the user owns to its mapped recipient, routed
    per guild.

    Projects live in per-guild schemas, so this fans out across the user's
    guilds (routed as superadmin) and transfers the owned projects found in
    each. ``project_transfers`` is keyed by ``"guild_id:project_id"`` because a
    bare project id is ambiguous across guild schemas. Running the transfer on
    the unrouted public default would target the frozen backup and leave the
    live project still owned by the departing user. Propagates
    :class:`InvalidTransferRecipient` so the caller can surface a 400. Resets to
    the public baseline on the way out.
    """
    for gid in await _user_guild_ids(session, user_id):
        session.expunge_all()
        await set_rls_context(session, guild_id=gid, is_superadmin=True)
        for project in await get_owned_projects(session, user_id):
            key = f"{gid}:{project.id}"
            if key not in project_transfers:
                continue
            await transfer_project_ownership(
                session, project.id, project_transfers[key]
            )
    session.expunge_all()
    await set_rls_context(session, is_superadmin=True)


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
    from app.models.document import DocumentFileVersion
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

    # File-document version history (uploaded_by_id is NOT NULL with a RESTRICT
    # FK) — reassign so the version row, and the document blob it backs, survive.
    await session.exec(
        update(DocumentFileVersion)
        .where(DocumentFileVersion.uploaded_by_id == user_id)
        .values(uploaded_by_id=system_user_id)
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


async def count_capability_holders(
    session: AsyncSession, capability: Capability, *, for_update: bool = False
) -> int:
    """Count active users whose standing role grants ``capability``.

    Args:
        session: Database session
        capability: The platform capability to count holders of
        for_update: If True, lock the matching user rows to prevent race conditions
    """
    roles = list(roles_with_capability(capability))
    if not roles:
        return 0
    if for_update:
        # Lock the matching users to prevent a race when demoting/deleting.
        stmt = (
            select(User)
            .where(
                User.role.in_(roles),
                User.status == UserStatus.active,
            )
            .with_for_update()
        )
        result = await session.exec(stmt)
        return len(result.all())
    stmt = select(func.count(User.id)).where(
        User.role.in_(roles),
        User.status == UserStatus.active,
    )
    result = await session.exec(stmt)
    return result.one()


async def is_last_capability_holder(
    session: AsyncSession,
    user_id: int,
    capability: Capability,
    *,
    for_update: bool = False,
) -> bool:
    """True iff removing this user would leave zero active holders of ``capability``.

    A target whose role doesn't grant the capability, or whose ``status`` isn't
    ``active``, doesn't contribute to the count, so removing them can't drop it
    to zero — return False in those cases. Otherwise count OTHER active holders
    and return True iff none exist.
    """
    roles = list(roles_with_capability(capability))
    if for_update:
        stmt = select(User).where(User.id == user_id).with_for_update()
    else:
        stmt = select(User).where(User.id == user_id)
    result = await session.exec(stmt)
    user = result.one_or_none()
    if not user or user.role not in roles or user.status != UserStatus.active:
        return False

    # PostgreSQL rejects ``SELECT COUNT(...) FOR UPDATE`` (aggregates
    # can't take row locks), so the for_update path locks the candidate
    # rows themselves and counts them in Python.
    if for_update:
        others_stmt = (
            select(User)
            .where(
                User.role.in_(roles),
                User.status == UserStatus.active,
                User.id != user_id,
            )
            .with_for_update()
        )
        others = (await session.exec(others_stmt)).all()
        return len(others) == 0
    others_stmt = select(func.count(User.id)).where(
        User.role.in_(roles),
        User.status == UserStatus.active,
        User.id != user_id,
    )
    return (await session.exec(others_stmt)).one() == 0


# Backwards-compatible wrappers. The invariant we protect is "can the platform
# still manage its own configuration", i.e. at least one ``owner`` remains
# (``config.manage`` is owner-only).
async def count_platform_admins(
    session: AsyncSession, *, for_update: bool = False
) -> int:
    """Count active users who can manage platform configuration (owners)."""
    return await count_capability_holders(
        session, Capability.CONFIG_MANAGE, for_update=for_update
    )


async def is_last_platform_admin(
    session: AsyncSession, user_id: int, *, for_update: bool = False
) -> bool:
    """True iff removing this user would leave the platform with no config managers."""
    return await is_last_capability_holder(
        session, user_id, Capability.CONFIG_MANAGE, for_update=for_update
    )


async def hard_delete_user(
    session: AsyncSession,
    user_id: int,
    project_transfers: Dict[str, int],
) -> None:
    """
    Permanently delete a user account.

    Args:
        session: Database session
        user_id: ID of user to delete
        project_transfers: Dict mapping "guild_id:project_id" to new_owner_id
            (composite key, since project ids repeat across per-guild schemas)
    """
    from app.services import initiatives as initiatives_service
    from app.models.queue import QueueItem, QueuePermission
    from app.models.document import DocumentPermission
    from app.models.push_token import PushToken
    from app.models.calendar_event import CalendarEventAttendee
    from app.models.guild import Guild, GuildInvite
    from app.models.property import (
        TaskPropertyValue,
        DocumentPropertyValue,
        CalendarEventPropertyValue,
    )

    # Get system user (shared ``users`` row — no routing needed).
    system_user = await get_or_create_system_user(session)
    system_user_id = system_user.id

    # ``guild_memberships`` is shared/public, so enumerate the user's guilds on
    # the default context.
    guild_ids = list(
        (
            await session.exec(
                select(GuildMembership.guild_id).where(
                    GuildMembership.user_id == user_id
                )
            )
        ).all()
    )

    # Phase 1 — guild-scoped cleanup, ROUTED INTO EACH GUILD'S SCHEMA. Every
    # statement below targets a guild-scoped table whose live rows live in
    # ``guild_<id>``; running them on the default (public) context would hit the
    # frozen pre-conversion backup and silently leave the user's content behind
    # in every guild. ``flush`` (not commit) keeps everything in the single
    # transaction committed at the end, so a failure rolls the whole delete back.
    for gid in guild_ids:
        session.expunge_all()
        await set_rls_context(session, guild_id=gid, is_superadmin=True)

        # Transfer projects this user owns in THIS guild before their
        # permission rows are wiped. get_owned_projects is now guild-scoped by
        # the routed search_path; the transfer map is keyed by
        # "guild_id:project_id" to disambiguate ids that repeat across schemas.
        for project in await get_owned_projects(session, user_id):
            key = f"{gid}:{project.id}"
            if key not in project_transfers:
                raise ValueError(
                    f"No transfer recipient specified for project {project.id} "
                    f"in guild {gid}"
                )
            await transfer_project_ownership(
                session, project.id, project_transfers[key]
            )

        # Initiative removal hands owned documents off to PMs before the
        # DocumentPermission wipe below.
        await initiatives_service.remove_user_from_guild_initiatives(
            session, guild_id=gid, user_id=user_id
        )

        # Reassign authored content (documents, comments, uploads, queues, …)
        # to the system user so it survives the deletion.
        await reassign_user_content(session, user_id, system_user_id)

        # Per-user guild-scoped rows with no ON DELETE CASCADE: delete or NULL.
        await session.exec(delete(ProjectOrder).where(ProjectOrder.user_id == user_id))
        await session.exec(
            delete(ProjectFavorite).where(ProjectFavorite.user_id == user_id)
        )
        await session.exec(delete(RecentView).where(RecentView.user_id == user_id))
        await session.exec(
            delete(TaskAssignmentDigestItem).where(
                TaskAssignmentDigestItem.user_id == user_id
            )
        )
        await session.exec(
            update(TaskAssignmentDigestItem)
            .where(TaskAssignmentDigestItem.assigned_by_id == user_id)
            .values(assigned_by_id=None)
        )
        await session.exec(
            delete(ProjectPermission).where(ProjectPermission.user_id == user_id)
        )
        await session.exec(delete(TaskAssignee).where(TaskAssignee.user_id == user_id))
        await session.exec(
            delete(QueuePermission).where(QueuePermission.user_id == user_id)
        )
        # Queue items: assigned-to is nullable, so just clear the pointer.
        await session.exec(
            update(QueueItem).where(QueueItem.user_id == user_id).values(user_id=None)
        )
        await session.exec(
            delete(DocumentPermission).where(DocumentPermission.user_id == user_id)
        )
        await session.exec(
            delete(CalendarEventAttendee).where(
                CalendarEventAttendee.user_id == user_id
            )
        )
        # User-typed custom-property values: NULL the reference (the value rows
        # belong to the entity, not the user).
        for table in (
            TaskPropertyValue,
            DocumentPropertyValue,
            CalendarEventPropertyValue,
        ):
            await session.exec(
                update(table)
                .where(table.value_user_id == user_id)
                .values(value_user_id=None)
            )
        await session.flush()

    # Phase 2 — shared/public cleanup. Reset to the public, login-role baseline
    # (BYPASSRLS) so these shared-table writes aren't trapped in the last guild's
    # schema/role.
    session.expunge_all()
    await set_rls_context(session, is_superadmin=True)

    await session.exec(delete(Notification).where(Notification.user_id == user_id))
    await session.exec(delete(UserApiKey).where(UserApiKey.user_id == user_id))
    await session.exec(delete(UserToken).where(UserToken.user_id == user_id))
    await session.exec(delete(PushToken).where(PushToken.user_id == user_id))

    # Clear nullable creator references on shared guild rows.
    await session.exec(
        update(Guild)
        .where(Guild.created_by_user_id == user_id)
        .values(created_by_user_id=None)
    )
    await session.exec(
        update(GuildInvite)
        .where(GuildInvite.created_by_user_id == user_id)
        .values(created_by_user_id=None)
    )

    # GuildMemberships cascade-delete via the User relationship. InitiativeMembers
    # were already removed per guild above.
    user = (await session.exec(select(User).where(User.id == user_id))).one()
    await session.delete(user)

    await session.commit()
